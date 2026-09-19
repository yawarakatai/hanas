import unittest

from hanas.text import TextError, chunks, clean, decode_input


class TextTests(unittest.TestCase):
    def test_terminal_sequences_and_newlines(self):
        value = "\x1b[31m赤\x1b[0m\r\n次\x1b]8;;https://example.test\x07リンク\x1b]8;;\x07"
        self.assertEqual(clean(value), "赤 次リンク")

    def test_chunking_has_no_loss_or_duplication(self):
        value = "あ" * 119 + "。）" + "次です！" + "x" * 250
        parts = chunks(value)
        self.assertEqual("".join(parts), value)
        self.assertTrue(all(0 < len(part) <= 120 for part in parts))

    def test_limits_and_utf8(self):
        with self.assertRaises(TextError):
            decode_input(b"x" * (64 * 1024 + 1))
        with self.assertRaises(TextError):
            decode_input(b"\xff")
        with self.assertRaises(TextError):
            clean(" \n\t ")


if __name__ == "__main__":
    unittest.main()
