"""Lightweight FHSC statement probes used only by daily maintenance."""
from __future__ import annotations

import hashlib
import json
from typing import Any

import vnstock_oapi as oapi

STATEMENT_TYPES = ("income-statement", "balance-sheet", "cash-flow")


def _error(exc: Exception) -> dict[str, Any]:
    return {
        "type": type(exc).__name__,
        "code": getattr(exc, "code", None),
        "action": getattr(exc, "action", None),
    }


def _period(row: dict[str, Any]) -> str | None:
    year = row.get("year")
    quarter = row.get("quarter")
    return (
        f"{year}-Q{quarter}" if year is not None and quarter is not None
        else str(year) if year is not None else None
    )


def latest_statement_probe(symbol: str, source: str) -> dict[str, Any]:
    """Fingerprint the newest quarterly row from every FHSC statement set.

    The normalized ``Fundamental`` reader follows every FHSC statement page.
    Daily maintenance only needs a change detector, so this deliberately uses one
    raw ``limit=1`` page for income, balance sheet and cash flow. Full statements
    remain the source of truth and are materialized only after the combined
    fingerprint changes.
    """
    request_count = 0
    try:
        client = oapi.source(source)
        latest_rows: dict[str, dict[str, Any]] = {}
        periods: dict[str, str | None] = {}
        signatures: dict[str, str] = {}
        for statement_type in STATEMENT_TYPES:
            request_count += 1
            envelopes = client.raw(
                "financial-statement/statement",
                only_page=1,
                symbol=symbol,
                type=statement_type,
                period="quarterly",
                limit=1,
            )
            if not envelopes:
                raise ValueError(
                    f"FHSC latest {statement_type} probe returned no envelope"
                )
            body = envelopes[0].body
            rows = body.get("data") if isinstance(body, dict) else body
            if not isinstance(rows, list) or not rows or not isinstance(rows[0], dict):
                raise ValueError(
                    f"FHSC latest {statement_type} probe returned no report row"
                )
            latest = rows[0]
            canonical = json.dumps(
                latest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            latest_rows[statement_type] = latest
            periods[statement_type] = _period(latest)
            signatures[statement_type] = hashlib.sha256(canonical).hexdigest()

        combined = json.dumps(
            latest_rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return {
            "signature": hashlib.sha256(combined).hexdigest(),
            "period": periods["income-statement"],
            "periods": periods,
            "statement_signatures": signatures,
            "rows": len(latest_rows),
            "statement_types": list(STATEMENT_TYPES),
            "request_count": request_count,
        }
    except Exception as exc:
        return {"error": _error(exc), "request_count": request_count}


def latest_income_statement_probe(symbol: str, source: str) -> dict[str, Any]:
    """Backward-compatible name for the complete latest-statement probe."""
    return latest_statement_probe(symbol, source)
