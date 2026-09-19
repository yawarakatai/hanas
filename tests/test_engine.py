import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from hanas.engine import Engine


class Handler(BaseHTTPRequestHandler):
    query_path = ""
    synthesis = None

    def do_GET(self):
        body = json.dumps([{"name": "話者", "styles": [{"name": "通常", "id": -3}]}]).encode()
        self.send_response(200); self.end_headers(); self.wfile.write(body)

    def do_POST(self):
        if self.path.startswith("/audio_query?"):
            Handler.query_path = self.path
            body = json.dumps({"speedScale": 1, "unknown": {"kept": True}, "kana": "原文"}).encode()
        else:
            length = int(self.headers.get("Content-Length", 0))
            Handler.synthesis = json.loads(self.rfile.read(length))
            body = (
                b"RIFF\x24\x00\x00\x00WAVE"
                b"fmt \x10\x00\x00\x00\x01\x00\x01\x00\x80\xbb\x00\x00\x00w\x01\x00\x02\x00\x10\x00"
                b"data\x00\x00\x00\x00"
            )
        self.send_response(200); self.end_headers(); self.wfile.write(body)

    def log_message(self, *args):
        pass


class EngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join()

    def test_voices_and_synthesis_preserve_query(self):
        engine = Engine(f"http://127.0.0.1:{self.server.server_port}")
        self.assertEqual(engine.voices()[0].style_id, -3)
        engine.synthesize("改行\n&?", -3, 1.25)
        self.assertIn("text=%E6%94%B9%E8%A1%8C%0A%26%3F", Handler.query_path)
        self.assertEqual(Handler.synthesis["speedScale"], 1.25)
        self.assertEqual(Handler.synthesis["unknown"], {"kept": True})
        self.assertEqual(Handler.synthesis["kana"], "原文")


if __name__ == "__main__":
    unittest.main()
