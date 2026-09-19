from __future__ import annotations

import re

MAX_BYTES = 64 * 1024
MAX_CHARS = 10_000
MAX_CHUNK = 120

# ECMA-48 CSI and OSC (BEL or ST terminated). The visible portion around OSC 8 links remains.
_CSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_OSC = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)")
_C0 = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_END = set("。！？")
_CLOSERS = set("」』】）》〉〕］）\"'”’")


class TextError(ValueError):
    pass


def decode_input(data: bytes) -> str:
    if len(data) > MAX_BYTES:
        raise TextError("input exceeds 64 KiB")
    try:
        value = data.decode("utf-8")
    except UnicodeDecodeError:
        raise TextError("input is not valid UTF-8") from None
    if len(value) > MAX_CHARS:
        raise TextError("input exceeds 10,000 characters")
    return value


def clean(value: str) -> str:
    value = _OSC.sub("", _CSI.sub("", value))
    value = value.replace("\r\n", "\n").replace("\r", "\n").replace("\t", " ")
    value = _C0.sub("", value)
    value = re.sub(r"[ \f\v]*\n[ \f\v]*\n(?:[ \f\v]*\n)*", "\n\n", value)
    value = re.sub(r"(?<!\n)\n(?!\n)", " ", value)
    value = value.strip()
    if not value:
        raise TextError("input is empty or whitespace only")
    return value


def chunks(value: str, limit: int = MAX_CHUNK) -> list[str]:
    """Split without dropping characters, preferring paragraphs and Japanese stops."""
    if limit < 1:
        raise ValueError("limit must be positive")
    result: list[str] = []
    start = 0
    while start < len(value):
        hard = min(start + limit, len(value))
        if hard == len(value):
            result.append(value[start:])
            break
        cut = -1
        para = value.rfind("\n\n", start + 1, hard + 1)
        if para >= start:
            cut = para + 2
        else:
            for pos in range(hard - 1, start - 1, -1):
                if value[pos] in _END:
                    cut = pos + 1
                    while cut < hard and value[cut] in _CLOSERS:
                        cut += 1
                    break
        if cut <= start:
            cut = hard
        result.append(value[start:cut])
        start = cut
    return result


def prepare(data: bytes) -> tuple[str, list[str]]:
    value = clean(decode_input(data))
    return value, chunks(value)
