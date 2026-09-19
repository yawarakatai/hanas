from __future__ import annotations

import asyncio
import contextlib
import fcntl
import json
import logging
import os
import tempfile
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import Config, ConfigError, valid_speed, valid_style_id
from .engine import Engine, EngineError
from .notification import notify
from .text import TextError, chunks, clean

PROTOCOL = 1
MAX_MESSAGE = 1024 * 1024
MAX_QUEUE = 16
LOG = logging.getLogger("hanas")


class RequestError(ValueError):
    pass


@dataclass
class Job:
    id: str
    parts: list[str]
    style_id: int
    speed: float
    generation: int
    accepted: float = field(default_factory=time.monotonic)
    result: asyncio.Future[dict[str, Any]] | None = None
    started: bool = False


class Daemon:
    def __init__(self, config: Config, runtime: Path):
        self.config = config
        self.runtime = runtime
        self.wav_dir = runtime / "wav"
        self.engine = Engine(config.url)
        self.queue: deque[Job] = deque()
        self.active: Job | None = None
        self.generation = 0
        self.wake = asyncio.Event()
        self.action_lock = asyncio.Lock()
        self.submit_lock = asyncio.Lock()
        self.player: asyncio.subprocess.Process | None = None
        self.last: dict[str, Any] | None = None
        self.synthesizing = False
        self.playing = False
        self.closing = False

    def valid(self, job: Job) -> bool:
        return job.generation == self.generation and job.result is not None and not job.result.done()

    async def notification(self, title: str, body: str = "", *, urgency: str = "normal") -> None:
        await asyncio.to_thread(notify, title, body, urgency=urgency)

    def finish(self, job: Job, state: str, error: str | None = None) -> None:
        if job.result is None or job.result.done():
            return
        result: dict[str, Any] = {"job_id": job.id, "state": state}
        if error:
            result["error"] = error
        job.result.set_result(result)
        self.last = result
        LOG.info("job=%s state=%s", job.id, state)

    async def cancel_all(self) -> None:
        self.generation += 1
        if self.active:
            self.finish(self.active, "cancelled")
        while self.queue:
            self.finish(self.queue.popleft(), "cancelled")
        await self.stop_player()

    async def stop_player(self) -> None:
        async with self.action_lock:
            proc = self.player
            if proc is None or proc.returncode is not None:
                return
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), 0.5)
            except TimeoutError:
                proc.kill()
                await proc.wait()

    def parse_job(self, message: dict[str, Any]) -> tuple[list[str], int, float]:
        text = message.get("text")
        if not isinstance(text, str):
            raise RequestError("text must be a string")
        if len(text.encode("utf-8")) > 64 * 1024 or len(text) > 10_000:
            raise RequestError("text exceeds the input limit")
        try:
            value = clean(text)
            speed = valid_speed(message.get("speed", self.config.speed))
            raw_style = message.get("style_id", self.config.style_id)
            if raw_style is None:
                raise RequestError("no style_id configured; run 'hanas voices' and configure one")
            style = valid_style_id(raw_style)
        except (TextError, ConfigError) as exc:
            raise RequestError(str(exc)) from None
        return chunks(value), style, speed

    async def submit(self, message: dict[str, Any]) -> Job:
        async with self.submit_lock:
            parts, style, speed = self.parse_job(message)
            enqueue = message.get("enqueue", False)
            if not isinstance(enqueue, bool):
                raise RequestError("enqueue must be boolean")
            if enqueue and len(self.queue) >= MAX_QUEUE:
                raise RequestError("the waiting queue is full")
            voices = await asyncio.to_thread(self.engine.voices)
            if style not in {voice.style_id for voice in voices}:
                raise RequestError(f"style_id {style} is not available; run 'hanas voices'")
            if not enqueue:
                await self.cancel_all()
            loop = asyncio.get_running_loop()
            job = Job(uuid.uuid4().hex, parts, style, speed, self.generation, result=loop.create_future())
            self.queue.append(job)
            self.wake.set()
            LOG.info("job=%s state=accepted chunks=%d", job.id, len(parts))
            return job

    async def play(self, job: Job, wav: bytes) -> None:
        if not self.valid(job):
            return
        fd, name = tempfile.mkstemp(prefix="hanas-", suffix=".wav", dir=self.wav_dir)
        path = Path(name)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(wav)
            async with self.action_lock:
                if not self.valid(job):
                    return
                command = os.environ.get("HANAS_PW_PLAY", "pw-play")
                try:
                    proc = await asyncio.create_subprocess_exec(command, str(path))
                except (OSError, ValueError):
                    raise RuntimeError("could not start pw-play") from None
                self.player = proc
                self.playing = True
                first_part = not job.started
                job.started = True
            if first_part:
                preview = job.parts[0].replace("\n", " ")
                if len(preview) > 120:
                    preview = preview[:117] + "..."
                await self.notification("読み上げを開始しました", preview)
            rc = await proc.wait()
            if self.valid(job) and rc != 0:
                raise RuntimeError(f"pw-play exited with status {rc}")
        finally:
            self.playing = False
            if self.player is locals().get("proc"):
                self.player = None
            with contextlib.suppress(FileNotFoundError):
                path.unlink()

    async def synth(self, job: Job, part: str) -> bytes:
        self.synthesizing = True
        try:
            return await asyncio.to_thread(self.engine.synthesize, part, job.style_id, job.speed)
        finally:
            self.synthesizing = False

    async def run_job(self, job: Job) -> None:
        try:
            wav = await self.synth(job, job.parts[0])
            for index in range(len(job.parts)):
                if not self.valid(job):
                    return
                play_task = asyncio.create_task(self.play(job, wav))
                next_task = None
                if index + 1 < len(job.parts):
                    next_task = asyncio.create_task(self.synth(job, job.parts[index + 1]))
                if next_task:
                    try:
                        next_wav = await next_task
                    except Exception:
                        await self.stop_player()
                        with contextlib.suppress(Exception):
                            await play_task
                        raise
                try:
                    await play_task
                except Exception:
                    if next_task and not next_task.done():
                        next_task.cancel()
                    raise
                if next_task:
                    wav = next_wav
            if self.valid(job):
                self.finish(job, "completed")
        except EngineError as exc:
            if self.valid(job):
                error = str(exc)
                self.finish(job, "failed", error)
                await self.notification("読み上げに失敗しました", error, urgency="critical")
        except Exception as exc:  # noqa: BLE001 -- one failed job must not stop the worker.
            if self.valid(job):
                error = str(exc) or "playback failed"
                self.finish(job, "failed", error)
                await self.notification("読み上げに失敗しました", error, urgency="critical")

    async def worker(self) -> None:
        while not self.closing:
            if not self.queue:
                self.wake.clear()
                await self.wake.wait()
                continue
            job = self.queue.popleft()
            self.active = job
            await self.run_job(job)
            if self.active is job:
                self.active = None

    def status(self) -> dict[str, Any]:
        active = self.active if self.active and self.valid(self.active) else None
        return {
            "active_job_id": active.id if active else None,
            "waiting": len(self.queue),
            "synthesizing": self.synthesizing,
            "playing": self.playing,
            "last": self.last,
        }

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        op: object = None
        try:
            try:
                line = await asyncio.wait_for(reader.readline(), 5)
            except (TimeoutError, ValueError):
                raise RequestError("invalid or oversized request") from None
            if not line or len(line) > MAX_MESSAGE or not line.endswith(b"\n"):
                raise RequestError("invalid or oversized request")
            try:
                message = json.loads(line.decode("utf-8"))
            except (UnicodeError, json.JSONDecodeError):
                raise RequestError("request is not valid UTF-8 JSON") from None
            if not isinstance(message, dict) or message.get("version") != PROTOCOL:
                raise RequestError("unsupported protocol version")
            op = message.get("op")
            if op == "speak":
                job = await self.submit(message)
                await self.send(writer, {"ok": True, "job_id": job.id, "state": "accepted"})
                if message.get("wait") is True:
                    assert job.result is not None
                    await self.send(writer, await asyncio.shield(job.result))
            elif op == "stop":
                await self.cancel_all()
                await self.send(writer, {"ok": True})
            elif op == "status":
                await self.send(writer, {"ok": True, **self.status()})
            else:
                raise RequestError("unknown operation")
        except RequestError as exc:
            if op == "speak":
                await self.notification("読み上げに失敗しました", str(exc), urgency="critical")
            await self.send(writer, {"ok": False, "kind": "input", "error": str(exc)})
        except EngineError as exc:
            if op == "speak":
                await self.notification("読み上げに失敗しました", str(exc), urgency="critical")
            kind = "connection" if exc.category == "connection" else "processing"
            await self.send(writer, {"ok": False, "kind": kind, "error": str(exc)})
        except (ConnectionError, BrokenPipeError):
            pass
        finally:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    @staticmethod
    async def send(writer: asyncio.StreamWriter, value: dict[str, Any]) -> None:
        writer.write(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode() + b"\n")
        await writer.drain()

    async def shutdown(self) -> None:
        self.closing = True
        await self.cancel_all()
        self.wake.set()


def runtime_paths() -> tuple[Path, Path, Path]:
    value = os.environ.get("XDG_RUNTIME_DIR")
    if not value:
        raise ConfigError("XDG_RUNTIME_DIR is not set")
    runtime = Path(value) / "hanas"
    return runtime, runtime / "daemon.sock", runtime / "daemon.lock"


async def serve(config: Config) -> None:
    runtime, socket_path, lock_path = runtime_paths()
    runtime.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(runtime, 0o700)
    lock = lock_path.open("a+")
    try:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ConfigError("another hanas daemon is already running") from None
        wav_dir = runtime / "wav"
        wav_dir.mkdir(mode=0o700, exist_ok=True)
        os.chmod(wav_dir, 0o700)
        for old in wav_dir.glob("hanas-*.wav"):
            with contextlib.suppress(OSError):
                old.unlink()
        with contextlib.suppress(FileNotFoundError):
            socket_path.unlink()
        daemon = Daemon(config, runtime)
        daemon.wav_dir = wav_dir
        server = await asyncio.start_unix_server(daemon.handle, path=socket_path, limit=MAX_MESSAGE + 1)
        os.chmod(socket_path, 0o600)
        worker = asyncio.create_task(daemon.worker())
        try:
            async with server:
                await server.serve_forever()
        except asyncio.CancelledError:
            pass
        finally:
            await daemon.shutdown()
            worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await worker
            server.close()
            await server.wait_closed()
            with contextlib.suppress(FileNotFoundError):
                socket_path.unlink()
    finally:
        lock.close()
