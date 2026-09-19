import tempfile
import unittest
from pathlib import Path

from hanas.config import Config
from hanas.daemon import MAX_QUEUE, Daemon
from hanas.engine import Voice


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


if __name__ == "__main__":
    unittest.main()
