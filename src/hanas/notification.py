from __future__ import annotations

import os
import subprocess


def notify(title: str, body: str = "", *, urgency: str = "normal") -> bool:
    """Send a best-effort desktop notification without affecting speech."""
    command = os.environ.get("HANAS_NOTIFY_SEND", "notify-send")
    try:
        result = subprocess.run(
            [command, "--app-name=hanas", f"--urgency={urgency}", title, body],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0
