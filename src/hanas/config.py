from __future__ import annotations

import math
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit


class ConfigError(ValueError):
    pass


@dataclass(frozen=True)
class Config:
    url: str = "http://127.0.0.1:10101"
    style_id: int | None = None
    speed: float = 1.0


def default_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME")
    return Path(base) / "hanas/config.toml" if base else Path.home() / ".config/hanas/config.toml"


def valid_style_id(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not -(2**31) <= value < 2**31:
        raise ConfigError("style_id must be a signed 32-bit integer")
    return value


def valid_speed(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError("speed must be a number")
    result = float(value)
    if not math.isfinite(result) or not 0.5 <= result <= 2.0:
        raise ConfigError("speed must be finite and between 0.5 and 2.0")
    return result


def load(path: str | None = None) -> Config:
    filename = Path(path) if path else default_path()
    if not filename.exists():
        if path:
            raise ConfigError(f"config file does not exist: {filename}")
        return Config()
    try:
        data = tomllib.loads(filename.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"cannot read config: {exc}") from None
    if set(data) != {"engine"} or not isinstance(data["engine"], dict):
        raise ConfigError("config must contain only an [engine] table")
    engine = data["engine"]
    unknown = set(engine) - {"url", "style_id", "speed"}
    if unknown:
        raise ConfigError(f"unknown engine setting: {min(unknown)}")
    url = engine.get("url", Config.url)
    if not isinstance(url, str) or urlsplit(url).scheme not in {"http", "https"} or not urlsplit(url).netloc:
        raise ConfigError("engine.url must be an http or https URL")
    style = valid_style_id(engine["style_id"]) if "style_id" in engine else None
    speed = valid_speed(engine.get("speed", Config.speed))
    return Config(url.rstrip("/"), style, speed)
