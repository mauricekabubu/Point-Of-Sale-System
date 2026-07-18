"""
network_status.py
------------------
Tracks whether THIS SERVER (not the client browser) currently has internet
connectivity, by periodically pinging a couple of low-cost external
endpoints in a background thread.

Why on the server, not the browser?
The POS frontend talks only to http://localhost:5000. If the browser tried
to reach an external URL directly to check "internet", it would hit CORS
issues and would say nothing about whether the SERVER (which is what
actually needs to reach Daraja / WhatsApp / Email / cloud sync) can get
out. So the backend checks its own connectivity and exposes the result via
/services/sync/status, which the frontend polls over localhost (always
reachable on the same machine).

Import and call `start_network_monitor()` once, at app startup.
Import and call `is_internet_available()` anywhere you need a quick,
non-blocking answer before attempting a cloud call.
"""

import logging
import threading
import time

import requests

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_internet_available = False
_last_checked = None

# Small, fast, unauthenticated endpoints — good general internet reachability
# probes without depending on Safaricom/WhatsApp/Email themselves being up.
_CHECK_URLS = [
    "https://clients3.google.com/generate_204",
    "https://www.google.com",
    "https://1.1.1.1",
]

CHECK_INTERVAL_SECONDS = 10
CHECK_TIMEOUT_SECONDS = 3


class NoInternetError(Exception):
    """Raised when a cloud-dependent operation is attempted while offline."""
    pass


def _check_once() -> bool:
    for url in _CHECK_URLS:
        try:
            resp = requests.get(url, timeout=CHECK_TIMEOUT_SECONDS)
            if resp.status_code < 500:
                return True
        except requests.exceptions.RequestException:
            continue
    return False


def is_internet_available() -> bool:
    with _lock:
        return _internet_available


def get_status() -> dict:
    with _lock:
        return {
            "internet": _internet_available,
            "last_checked": _last_checked,
        }


def _background_loop():
    global _internet_available, _last_checked
    while True:
        try:
            result = _check_once()
        except Exception as e:  # never let the monitor thread die
            logger.exception("network_status | check failed: %s", e)
            result = False

        with _lock:
            changed = result != _internet_available
            _internet_available = result
            _last_checked = time.time()

        if changed:
            logger.info("network_status | internet connectivity changed -> %s", result)

        time.sleep(CHECK_INTERVAL_SECONDS)


_monitor_started = False


def start_network_monitor():
    """Idempotent — safe to call multiple times (e.g. under a reloader)."""
    global _monitor_started
    if _monitor_started:
        return
    _monitor_started = True
    thread = threading.Thread(target=_background_loop, name="network-monitor", daemon=True)
    thread.start()
    logger.info("network_status | background monitor started")


def require_internet():
    """Raise NoInternetError if offline. Use at the top of cloud-only routes/helpers."""
    if not is_internet_available():
        raise NoInternetError("Internet unavailable. This feature requires an internet connection.")