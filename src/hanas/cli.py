from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import selectors
import socket
import subprocess
import sys
import time
from typing import Any

from . import __version__
from .config import ConfigError, load, valid_speed, valid_style_id
from .daemon import MAX_MESSAGE, runtime_paths, serve
from .engine import Engine, EngineError
from .text import MAX_BYTES, TextError, prepare


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="hanas")
    root.add_argument("--version", action="version", version=__version__)
    commands = root.add_subparsers(dest="command", required=True)
    daemon = commands.add_parser("daemon", help="run the foreground daemon")
    daemon.add_argument("--config")
    voices = commands.add_parser("voices", help="list speaker styles")
    voices.add_argument("--config")
    speak = commands.add_parser("speak", help="speak text")
    source = speak.add_mutually_exclusive_group(required=True)
    source.add_argument("text", nargs="?")
    source.add_argument("--stdin", action="store_true")
    source.add_argument("--selection", action="store_true")
    source.add_argument("--clipboard", action="store_true")
    speak.add_argument("--enqueue", action="store_true")
    speak.add_argument("--wait", action="store_true")
    speak.add_argument("--style-id", type=int)
    speak.add_argument("--speed", type=float)
    commands.add_parser("stop", help="stop playback and clear the queue")
    status = commands.add_parser("status", help="show daemon status")
    status.add_argument("--json", action="store_true")
    return root


def clipboard(primary: bool) -> bytes:
    args = [os.environ.get("HANAS_WL_PASTE", "wl-paste")]
    if primary:
        args.append("--primary")
    args += ["--no-newline", "--type", "text"]
    try:
        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except OSError:
        raise TextError("could not start wl-paste; copy the text and try --clipboard") from None
    assert proc.stdout is not None
    selector = selectors.DefaultSelector()
    selector.register(proc.stdout, selectors.EVENT_READ)
    output = bytearray()
    deadline = time.monotonic() + 3
    try:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not selector.select(remaining):
                proc.kill()
                raise TextError("wl-paste timed out after 3 seconds")
            block = os.read(proc.stdout.fileno(), min(8192, MAX_BYTES + 1 - len(output)))
            if not block:
                break
            output.extend(block)
            if len(output) > MAX_BYTES:
                proc.kill()
                raise TextError("clipboard input exceeds 64 KiB")
        try:
            rc = proc.wait(timeout=max(0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            proc.kill()
            raise TextError("wl-paste timed out after 3 seconds") from None
        if rc != 0:
            hint = "copy the text and use --clipboard" if primary else "ensure the clipboard contains text"
            raise TextError(f"could not read selection: {hint}")
        return bytes(output)
    finally:
        selector.close()
        if proc.poll() is None:
            proc.kill()
        proc.wait()


def input_bytes(args: argparse.Namespace) -> bytes:
    if args.text is not None:
        return args.text.encode("utf-8")
    if args.stdin:
        return sys.stdin.buffer.read(MAX_BYTES + 1)
    return clipboard(args.selection)


def exchange(message: dict[str, Any], responses: int = 1) -> list[dict[str, Any]]:
    try:
        _, path, _ = runtime_paths()
        sock = socket.socket(socket.AF_UNIX)
        sock.connect(str(path))
        payload = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode() + b"\n"
        if len(payload) > MAX_MESSAGE:
            raise TextError("request exceeds the IPC limit")
        sock.sendall(payload)
        stream = sock.makefile("rb")
        result = []
        for _ in range(responses):
            line = stream.readline(MAX_MESSAGE + 1)
            if not line or len(line) > MAX_MESSAGE:
                raise OSError("invalid daemon response")
            result.append(json.loads(line.decode("utf-8")))
        return result
    except ConfigError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ConnectionError("could not connect to the hanas daemon") from None
    finally:
        if "sock" in locals():
            sock.close()


def run(args: argparse.Namespace) -> int:
    if args.command == "daemon":
        config = load(args.config)
        logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
        try:
            asyncio.run(serve(config))
        except KeyboardInterrupt:
            pass
        return 0
    if args.command == "voices":
        config = load(args.config)
        voices = Engine(config.url).voices()
        for voice in voices:
            print(f"{voice.style_id}\t{voice.speaker}\t{voice.style}")
        return 0
    if args.command == "speak":
        text, _ = prepare(input_bytes(args))
        message: dict[str, Any] = {
            "version": 1, "op": "speak", "text": text,
            "enqueue": args.enqueue, "wait": args.wait,
        }
        if args.style_id is not None:
            message["style_id"] = valid_style_id(args.style_id)
        if args.speed is not None:
            message["speed"] = valid_speed(args.speed)
        replies = exchange(message, 2 if args.wait else 1)
        accepted = replies[0]
        if not accepted.get("ok"):
            print(accepted.get("error", "request rejected"), file=sys.stderr)
            if accepted.get("kind") == "connection":
                return 3
            if accepted.get("kind") == "processing":
                return 4
            return 2
        print(accepted["job_id"])
        if args.wait:
            terminal = replies[1]
            state = terminal.get("state")
            if state == "completed":
                return 0
            if state == "cancelled":
                print("reading was cancelled", file=sys.stderr)
                return 5
            print(terminal.get("error", "reading failed"), file=sys.stderr)
            return 4
        return 0
    if args.command == "stop":
        exchange({"version": 1, "op": "stop"})
        return 0
    if args.command == "status":
        result = exchange({"version": 1, "op": "status"})[0]
        if args.json:
            print(json.dumps(result, ensure_ascii=False))
        else:
            print(f"active: {result.get('active_job_id') or '-'}")
            print(f"waiting: {result.get('waiting', 0)}")
            print(f"synthesizing: {str(bool(result.get('synthesizing'))).lower()}")
            print(f"playing: {str(bool(result.get('playing'))).lower()}")
            last = result.get("last")
            if last:
                detail = f" ({last['error']})" if last.get("error") else ""
                print(f"last: {last.get('job_id')} {last.get('state')}{detail}")
            else:
                print("last: -")
        return 0
    return 2


def main() -> None:
    try:
        code = run(parser().parse_args())
    except (TextError, ConfigError, ValueError) as exc:
        print(f"hanas: {exc}", file=sys.stderr)
        code = 2
    except ConnectionError as exc:
        print(f"hanas: {exc}", file=sys.stderr)
        code = 3
    except EngineError as exc:
        print(f"hanas: {exc}", file=sys.stderr)
        code = 3 if exc.category == "connection" else 4
    raise SystemExit(code)
