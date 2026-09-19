import tempfile
import unittest
from pathlib import Path

from hanas.config import ConfigError, load


class ConfigTests(unittest.TestCase):
    def test_load(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text('[engine]\nurl="http://localhost:50021/"\nstyle_id=-2\nspeed=1.2\n')
            config = load(str(path))
            self.assertEqual(config.url, "http://localhost:50021")
            self.assertEqual(config.style_id, -2)

    def test_unknown_and_bad_speed_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.toml"
            path.write_text("[engine]\nspeeed=1.0\n")
            with self.assertRaises(ConfigError):
                load(str(path))
            path.write_text("[engine]\nspeed=nan\n")
            with self.assertRaises(ConfigError):
                load(str(path))


if __name__ == "__main__":
    unittest.main()
