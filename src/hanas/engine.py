from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

MAX_RESPONSE = 32 * 1024 * 1024
TIMEOUT = 30


class EngineError(RuntimeError):
    def __init__(self, category: str, message: str):
        super().__init__(message)
        self.category = category


@dataclass(frozen=True)
class Voice:
    speaker: str
    style: str
    style_id: int


class Engine:
    def __init__(self, base_url: str, timeout: float = TIMEOUT):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        # Deliberately do not use HTTP(S)_PROXY for a local speech engine.
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def _request(self, path: str, body: bytes | None = None, content_type: str | None = None) -> bytes:
        headers = {"Content-Type": content_type} if content_type else {}
        req = urllib.request.Request(self.base_url + path, data=body, headers=headers)
        try:
            with self.opener.open(req, timeout=self.timeout) as response:
                data = response.read(MAX_RESPONSE + 1)
        except urllib.error.HTTPError as exc:
            raise EngineError("http", f"engine returned HTTP {exc.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise EngineError("connection", "could not connect to the speech engine") from None
        if len(data) > MAX_RESPONSE:
            raise EngineError("response-size", "engine response exceeds 32 MiB")
        return data

    @staticmethod
    def _json(data: bytes, what: str) -> Any:
        try:
            return json.loads(data.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            raise EngineError("json", f"engine returned invalid {what} JSON") from None

    def voices(self) -> list[Voice]:
        raw = self._json(self._request("/speakers"), "speakers")
        if not isinstance(raw, list):
            raise EngineError("json", "engine returned an invalid speakers list")
        voices: list[Voice] = []
        try:
            for speaker in raw:
                for style in speaker["styles"]:
                    sid = style["id"]
                    if isinstance(sid, bool) or not isinstance(sid, int):
                        raise TypeError
                    voices.append(Voice(str(speaker["name"]), str(style["name"]), sid))
        except (KeyError, TypeError):
            raise EngineError("json", "engine returned an invalid speakers list") from None
        return voices

    def synthesize(self, text: str, style_id: int, speed: float) -> bytes:
        query = urllib.parse.urlencode({"text": text, "speaker": style_id})
        audio_query = self._json(
            self._request("/audio_query?" + query, b"", "application/octet-stream"), "audio_query"
        )
        if not isinstance(audio_query, dict):
            raise EngineError("json", "engine returned invalid audio_query JSON")
        audio_query["speedScale"] = speed
        body = json.dumps(audio_query, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        speaker = urllib.parse.urlencode({"speaker": style_id})
        wav = self._request("/synthesis?" + speaker, body, "application/json")
        if not self._valid_wav(wav):
            raise EngineError("wav", "engine returned an invalid WAV file")
        return wav

    @staticmethod
    def _valid_wav(data: bytes) -> bool:
        if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WAVE":
            return False
        end = int.from_bytes(data[4:8], "little") + 8
        if end > len(data) or end < 12:
            return False
        found_fmt = found_data = False
        offset = 12
        while offset + 8 <= end:
            kind = data[offset:offset + 4]
            size = int.from_bytes(data[offset + 4:offset + 8], "little")
            offset += 8
            if offset + size > end:
                return False
            found_fmt |= kind == b"fmt " and size >= 16
            found_data |= kind == b"data"
            offset += size + (size & 1)
        return offset == end and found_fmt and found_data
