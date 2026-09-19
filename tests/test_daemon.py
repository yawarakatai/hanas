import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from hanas.config import Config
from hanas.daemon import MAX_QUEUE, Daemon
from hanas.engine import EngineError, Voice


class DaemonStateTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        runtime = Path(self.tmp.name)
        (runtime / "wav").mkdir()
        self.daemon = Daemon(Config(style_id=1), runtime)
        self.daemon.wav_dir = runtime / "wav"
        self.daemon.engine.voices = lambda: [Voice("speaker", "style", 1)]

    async def asyncTearDown(self):
        self.tmp.cleanup()

    async def test_replace_cancels_old_jobs(self):
        first = await self.daemon.submit({"text": "A", "enqueue": True})
        second = await self.daemon.submit({"text": "B", "enqueue": False})
        self.assertEqual((await first.result)["state"], "cancelled")
        self.assertEqual(list(self.daemon.queue), [second])

    async def test_stop_is_idempotent_and_clears_queue(self):
        job = await self.daemon.submit({"text": "A", "enqueue": True})
        await self.daemon.cancel_all()
        await self.daemon.cancel_all()
        self.assertEqual((await job.result)["state"], "cancelled")
        self.assertFalse(self.daemon.queue)

    async def test_enqueue_limit_does_not_change_existing_jobs(self):
        for n in range(MAX_QUEUE):
            await self.daemon.submit({"text": str(n), "enqueue": True})
        with self.assertRaisesRegex(ValueError, "queue is full"):
            await self.daemon.submit({"text": "overflow", "enqueue": True})
        self.assertEqual(len(self.daemon.queue), MAX_QUEUE)

    async def test_notifies_once_when_playback_starts(self):
        job = await self.daemon.submit({"text": "読み上げる文章", "enqueue": True})
        self.daemon.notification = AsyncMock()

        class Player:
            returncode = None

            async def wait(self):
                self.returncode = 0
                return 0

        with patch("hanas.daemon.asyncio.create_subprocess_exec", side_effect=[Player(), Player()]):
            await self.daemon.play(job, b"wav")
            await self.daemon.play(job, b"wav")

        self.daemon.notification.assert_awaited_once_with("読み上げを開始しました", "読み上げる文章")

    async def test_notifies_when_synthesis_fails(self):
        job = await self.daemon.submit({"text": "A", "enqueue": True})
        self.daemon.notification = AsyncMock()

        def fail(*_args):
            raise EngineError("connection", "engine unavailable")

        self.daemon.engine.synthesize = fail
        await self.daemon.run_job(job)

        self.assertEqual((await job.result)["state"], "failed")
        self.daemon.notification.assert_awaited_once_with(
            "読み上げに失敗しました", "engine unavailable", urgency="critical"
        )


if __name__ == "__main__":
    unittest.main()
