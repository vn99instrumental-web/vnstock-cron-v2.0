#!/usr/bin/env python3
"""Refresh small dashboard-serving snapshots after Supabase sync and IC export."""
from __future__ import annotations

import json
import logging
import os
import sys

import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("refresh_dashboard_snapshots")


def main() -> int:
    url = (os.environ.get("SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL") or "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        log.error("Missing SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY")
        return 2
    response = requests.post(
        f"{url}/rest/v1/rpc/refresh_v4_dashboard_snapshots",
        headers={"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        data="{}",
        timeout=300,
    )
    if response.status_code >= 300:
        log.error("Snapshot refresh failed: HTTP %s %s", response.status_code, response.text[:500])
        return 1
    payload = response.json() if response.content else {}
    log.info("Dashboard snapshots refreshed: %s", json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
