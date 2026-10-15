#!/usr/bin/env python3
"""Apply the bounded Supabase serving retention policy via a service-role RPC."""
from __future__ import annotations
import json
import logging
import os
import sys
import time
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("prune_supabase_retention")
RPC_TIMEOUT_SECONDS = 75


def post_rpc(url: str, key: str, function_name: str) -> tuple[bool, object]:
    started = time.monotonic()
    try:
        response = requests.post(
            f"{url}/rest/v1/rpc/{function_name}",
            headers={
                "apikey": key,
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
            json={},
            timeout=(10, RPC_TIMEOUT_SECONDS),
        )
    except requests.RequestException as exc:
        log.error("RPC %s failed after %.1fs: %s", function_name, time.monotonic() - started, exc)
        return False, None
    if response.status_code >= 300:
        log.error(
            "RPC %s failed after %.1fs: HTTP %s %s",
            function_name, time.monotonic() - started, response.status_code, response.text[:500],
        )
        return False, None
    payload = response.json() if response.content else None
    log.info("RPC %s completed in %.1fs", function_name, time.monotonic() - started)
    return True, payload

def main() -> int:
    url = (os.environ.get("SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL") or "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        log.error("Missing SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY")
        return 2
    retention_ok, payload = post_rpc(url, key, "prune_v4_legacy_intraday")
    if not retention_ok:
        return 1
    orphan_ok, orphan_runs = post_rpc(url, key, "prune_v4_orphan_runs")
    if not orphan_ok:
        return 1
    log.info(
        "Supabase retention applied: %s; orphan runs removed: %s",
        json.dumps(payload or {}, ensure_ascii=False, sort_keys=True),
        orphan_runs,
    )
    return 0

if __name__ == "__main__":
    sys.exit(main())