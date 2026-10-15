#!/usr/bin/env python3
"""Apply the bounded Supabase serving retention policy via a service-role RPC."""
from __future__ import annotations
import json
import logging
import os
import sys
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("prune_supabase_retention")

def main() -> int:
    url = (os.environ.get("SUPABASE_URL") or os.environ.get("NEXT_PUBLIC_SUPABASE_URL") or "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        log.error("Missing SUPABASE_URL/SUPABASE_SERVICE_ROLE_KEY")
        return 2
    response = requests.post(
        f"{url}/rest/v1/rpc/prune_v4_legacy_intraday",
        headers={"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        data="{}", timeout=300,
    )
    if response.status_code >= 300:
        log.error("Retention prune failed: HTTP %s %s", response.status_code, response.text[:500])
        return 1
    payload = response.json() if response.content else {}
    orphan_response = requests.post(
        f"{url}/rest/v1/rpc/prune_v4_orphan_runs",
        headers={"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        data="{}", timeout=300,
    )
    if orphan_response.status_code >= 300:
        log.error("Orphan-run cleanup failed: HTTP %s %s", orphan_response.status_code, orphan_response.text[:500])
        return 1
    orphan_runs = orphan_response.json() if orphan_response.content else 0
    log.info(
        "Supabase retention applied: %s; orphan runs removed: %s",
        json.dumps(payload, ensure_ascii=False, sort_keys=True),
        orphan_runs,
    )
    return 0

if __name__ == "__main__":
    sys.exit(main())