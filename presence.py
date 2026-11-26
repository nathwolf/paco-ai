"""Paco works only while your session is in use.

Resting when: the screen is locked, no display is awake (lid closed without an external monitor, or the
displays are asleep), or another user is on the console (fast user switching). In that state every loop
stops: no reminders, call-outs, model calls or syncing. Agents you started (Claude Code, Codex) keep running;
Paco just stops checking in. A lid closed with an external monitor in use counts as active.
"""
import json
from pathlib import Path
import subprocess
import sys
import threading
import time

TTL = 10
_LOCK = threading.Lock()
_CACHE = {'at': 0.0, 'value': (True, None)}


def _native_activity():
    binary = Path(__file__).parent / 'build/Paco.app/Contents/MacOS/Paco'
    return json.loads(subprocess.check_output([str(binary), '--capture', 'activity'], text=True, stderr=subprocess.DEVNULL, timeout=3))


def evaluate(meta):
    """(active, reason) from the native activity snapshot."""
    if meta.get('locked') is True:
        return False, 'Screen locked'
    if meta.get('on_console') is False:
        return False, 'Another user is using this Mac'
    if meta.get('displays') == 0 or meta.get('display_asleep') is True:
        return False, 'Display asleep or lid closed'
    return True, None


def check(now=None, reader=None):
    """Cached for a few seconds. When the signal is unavailable (not macOS, app not built) Paco stays active."""
    now = time.time() if now is None else now
    with _LOCK:
        if reader is None and 0 <= now - _CACHE['at'] < TTL:
            return _CACHE['value']
    if reader is None and sys.platform != 'darwin':
        value = (True, None)
    else:
        try:
            value = evaluate((reader or _native_activity)())
        except (OSError, subprocess.SubprocessError, ValueError, TypeError):
            value = (True, None)
    if reader is None:
        with _LOCK:
            _CACHE.update(at=now, value=value)
    return value


def active(now=None):
    return check(now)[0]
