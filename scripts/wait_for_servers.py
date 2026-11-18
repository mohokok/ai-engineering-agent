"""Wait until local backend and frontend URLs respond with HTTP 200."""

from __future__ import annotations

import sys
import time
import urllib.error
import urllib.request


def wait_for_urls(urls: list[str], timeout_seconds: float = 20.0) -> bool:
    """Poll all URLs until every URL responds or timeout elapses."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        all_ready = True
        for url in urls:
            try:
                with urllib.request.urlopen(url, timeout=2.0) as resp:
                    if resp.status >= 400:
                        all_ready = False
                        break
            except (urllib.error.URLError, TimeoutError, OSError):
                all_ready = False
                break
        if all_ready:
            return True
        time.sleep(0.5)
    return False


if __name__ == "__main__":
    targets = sys.argv[1:]
    if not targets:
        raise SystemExit("Usage: wait_for_servers.py <url1> [<url2> ...]")
    raise SystemExit(0 if wait_for_urls(targets) else 1)
