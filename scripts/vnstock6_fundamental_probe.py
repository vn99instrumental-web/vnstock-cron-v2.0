"""Lightweight FHSC statement probes used only by daily maintenance."""
from __future__ import annotations

import hashlib
import json
from typing import Any

import vnstock_oapi as oapi


def _error(exc: Exception) -> dict[str, Any]:
    return {
        "type": type(exc).__name__,
        "code": getattr(exc, "code", None),
        "action": getattr(exc, "action", None),
    }


def latest_income_statement_probe(symbol: str, source: str) -> dict[str, Any]:
    """Fetch only the newest quarterly income-statement row and fingerprint it.

    The normalized ``Fundamental`` reader follows every FHSC statement page.
    Daily maintenance only needs a change detector, so this deliberately uses
    the raw endpoint with ``limit=1`` and exactly page 1. Full statements remain
    the source of truth and are materialized only after this fingerprint changes.
    """
    try:
        envelopes = oapi.source(source).raw(
            "financial-statement/statement",
            only_page=1,
            symbol=symbol,
            type="income-statement",
            period="quarterly",
            limit=1,
        )
        if not envelopes:
            raise ValueError("FHSC latest income-statement probe returned no envelope")
        body = envelopes[0].body
        rows = body.get("data") if isinstance(body, dict) else body
        if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
            raise ValueError("FHSC latest income-statement probe returned no report row")
        latest = rows[0]
        canonical = json.dumps(
            latest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        year = latest.get("year")
        quarter = latest.get("quarter")
        period = (
            f"{year}-Q{quarter}" if year is not None and quarter is not None
            else str(year) if year is not None else None
        )
        return {
            "signature": hashlib.sha256(canonical).hexdigest(),
            "period": period,
            "rows": len(rows),
        }
    except Exception as exc:
        return {"error": _error(exc)}
