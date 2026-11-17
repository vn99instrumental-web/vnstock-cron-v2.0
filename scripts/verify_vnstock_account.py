"""Verify the GitHub runner uses an authenticated Vnstock Silver-or-higher account."""

from __future__ import annotations

import json
import os

import vnstock


TIER_RANK = {
    "guest": 0,
    "free": 1,
    "bronze": 2,
    "silver": 3,
    "golden": 4,
    "diamond": 5,
}


def verify_status(status: dict[str, object], minimum_tier: str = "silver") -> dict[str, object]:
    """Return a secret-free account summary or reject an insufficient tier."""
    tier = str(status.get("tier") or "guest").lower()
    authenticated = bool(status.get("authenticated"))
    if not authenticated:
        raise RuntimeError("Vnstock account is not authenticated")
    if TIER_RANK.get(tier, -1) < TIER_RANK[minimum_tier]:
        raise RuntimeError(
            f"Vnstock tier {tier!r} is below the required {minimum_tier!r} tier"
        )
    return {
        "authenticated": True,
        "tier": tier,
        "expires_at": status.get("expires_at"),
    }


def main() -> None:
    api_key = os.environ.get("VNSTOCK_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("Missing VNSTOCK_API_KEY")
    summary = verify_status(vnstock.login(api_key))
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
