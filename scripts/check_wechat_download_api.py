"""Check the external wechat-download-api health endpoint."""

from __future__ import annotations

import os
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


def main() -> None:
    base_url = os.getenv("WECHAT_DOWNLOAD_API_BASE_URL", "http://localhost:5000").rstrip("/")
    health_url = f"{base_url}/api/health"

    print(f"Checking {health_url}")
    try:
        with urlopen(health_url, timeout=5) as response:
            print(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP {exc.code}: {body}") from exc
    except URLError as exc:
        raise SystemExit(f"Request failed: {exc.reason}") from exc


if __name__ == "__main__":
    main()
