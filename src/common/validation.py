"""Tiny schema validator (no external deps)."""
from __future__ import annotations
from typing import Any


def validate_schema(data: dict[str, Any], schema: dict[str, Any]) -> tuple[bool, str]:
    """schema: {field: {type: 'string'|'number'|'integer'|'boolean'|'array'|'object', required: bool}}"""
    if not isinstance(data, dict):
        return False, "input must be object"
    for field, spec in schema.items():
        req = bool(spec.get("required", False))
        if field not in data:
            if req:
                return False, f"missing required field: {field}"
            continue
        val = data[field]
        want = spec.get("type")
        if want == "string" and not isinstance(val, str):
            return False, f"{field} must be string"
        if want == "number" and not isinstance(val, (int, float)):
            return False, f"{field} must be number"
        if want == "integer" and not isinstance(val, int):
            return False, f"{field} must be integer"
        if want == "boolean" and not isinstance(val, bool):
            return False, f"{field} must be boolean"
        if want == "array" and not isinstance(val, list):
            return False, f"{field} must be array"
        if want == "object" and not isinstance(val, dict):
            return False, f"{field} must be object"
    return True, "ok"


def ok_result(tool: str, data: dict[str, Any], elapsed_ms: int = 0) -> dict[str, Any]:
    return {"ok": True, "tool": tool, "elapsed_ms": elapsed_ms, "data": data}


def err_result(tool: str, error: str, *, hint: str = "", elapsed_ms: int = 0,
               code: str = "ERROR") -> dict[str, Any]:
    return {"ok": False, "tool": tool, "elapsed_ms": elapsed_ms,
            "error": {"code": code, "message": error, "hint": hint}}
