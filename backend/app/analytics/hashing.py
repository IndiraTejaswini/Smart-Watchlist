"""Cross-process deterministic serialization and input hashing."""

from __future__ import annotations

import dataclasses
import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from app.analytics.fact_bundle import FactBundle


def canonicalize_for_hash(obj: Any) -> Any:
    if isinstance(obj, Enum):
        return canonicalize_for_hash(obj.value)
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return str(obj.normalize())
    if isinstance(obj, float):
        return f"{obj:.8f}"
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {
            field.name: canonicalize_for_hash(getattr(obj, field.name))
            for field in sorted(dataclasses.fields(obj), key=lambda item: item.name)
        }
    if isinstance(obj, dict):
        return {
            str(key): canonicalize_for_hash(obj[key])
            for key in sorted(obj, key=str)
        }
    if isinstance(obj, (set, frozenset, list, tuple)):
        values = [canonicalize_for_hash(value) for value in obj]
        return sorted(values, key=str) if isinstance(obj, (set, frozenset)) else values
    if obj is None or isinstance(obj, (bool, int, str)):
        return obj
    raise TypeError(f"unsupported hash input: {type(obj).__name__}")


def compute_inputs_hash(bundle: FactBundle) -> str:
    canonical = canonicalize_for_hash(bundle)
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
