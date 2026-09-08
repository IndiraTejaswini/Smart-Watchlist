"""Canonical JSON and inputs_hash — docs/BUILD_SPEC.md §4.2.

`json.dumps` cannot serialise numpy scalars, `Decimal` or `datetime`, and
unrounded float repr is not stable across platforms. Since `inputs_hash`
underpins invariant N1 — every displayed number must be recomputable from
stored inputs — the serialiser is part of the contract, not an implementation
detail.

The mandatory rules, from §4.2:

  - dict keys sorted
  - all floats rounded to CANONICAL_FLOAT_DP (=8) before serialisation
  - numpy scalars -> python scalars; Decimal -> float, then rounded
  - datetimes -> ISO 8601 with explicit UTC offset, microseconds truncated
  - None handled consistently (omit, never sometimes-null)
  - sets -> sorted lists
  - NaN / Infinity -> raise, never emit non-standard JSON

Three properties this file defends, each of which has bitten a real pipeline:

  Determinism across processes. Set iteration order follows str hashing, which
  is seeded per process by PYTHONHASHSEED. A serialiser that emits a set in
  iteration order produces a different hash in every interpreter. Sets are
  sorted here, by their canonical form, so ordering is imposed rather than
  inherited.

  Determinism across representations. The same number arrives as a Decimal from
  Postgres NUMERIC, as a float from pandas, and as a numpy.float64 from the
  regression. All three must reach one hash, or restatement cannot tell "the
  inputs changed" from "a different code path loaded them".

  Refusal over guessing. A naive datetime, a None inside a bar series, an
  unknown type: every one of these is a bug upstream, and every silent
  resolution of one produces numbers that look plausible and are wrong. They
  raise. R5 — fail visibly.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any

from app.constants import CANONICAL_FLOAT_DP


class CanonicalError(TypeError):
    """A value cannot be canonically serialised.

    Always a defect in the caller — an unsupported type, a naive timestamp, a
    non-finite float — never a recoverable condition. Subclasses TypeError so
    that code catching serialisation problems catches this too.
    """


def _round_float(value: float, *, path: str) -> float:
    """Round to CANONICAL_FLOAT_DP and normalise the sign of zero.

    Rounding is what makes the hash insensitive to the last bits of an IEEE 754
    result: a residual that differs in the 15th decimal between two runs must
    not change `inputs_hash`, or every signal would restate on every recompute.

    Negative zero is normalised because -0.0 and 0.0 are arithmetically equal
    but repr differently. An abnormal return of exactly zero must not hash two
    ways depending on the sign of the subtraction that produced it.
    """
    if math.isnan(value):
        raise CanonicalError(f"NaN at {path}: not valid JSON and never a valid input")
    if math.isinf(value):
        raise CanonicalError(
            f"{'-' if value < 0 else ''}Infinity at {path}: not valid JSON. "
            "MPM_TIER_THRESHOLDS carries inf as a tier sentinel; it is a "
            "threshold, never an input, and must not reach a hash."
        )
    rounded = round(value, CANONICAL_FLOAT_DP)
    return rounded + 0.0 if rounded == 0.0 else rounded


def _canonicalise(obj: Any, *, path: str = "$") -> Any:
    """Convert `obj` into the subset of Python that json.dumps renders stably.

    The accepted set is deliberately closed: anything not listed raises, so a
    new type entering a FactBundle is a loud failure rather than a silently
    different hash.
    """
    # bool before int: bool is a subclass of int, and True must render as
    # `true`, not `1`.
    if isinstance(obj, bool):
        return obj

    if obj is None:
        raise CanonicalError(
            f"None at {path}. None is omitted as a mapping value; anywhere else "
            "it is a loader bug, because dropping a sequence element shifts "
            "every later index and emitting null contradicts the §4.2 rule."
        )

    if isinstance(obj, int):
        # Never routed through float: turnover in paise exceeds 2**53, where
        # float silently loses integer precision.
        return obj

    if isinstance(obj, float):
        return _round_float(obj, path=path)

    if isinstance(obj, str):
        return obj

    if isinstance(obj, Decimal):
        try:
            as_float = float(obj)
        except (ValueError, OverflowError, InvalidOperation) as exc:
            raise CanonicalError(f"Decimal at {path} is not finite: {obj!r}") from exc
        return _round_float(as_float, path=path)

    # datetime before date: datetime is a subclass of date.
    if isinstance(obj, datetime):
        if obj.tzinfo is None or obj.tzinfo.utcoffset(obj) is None:
            raise CanonicalError(
                f"naive datetime at {path}. IST is UTC+5:30, so guessing a zone "
                "puts a 19:00 IST event on the wrong trading date — the most "
                "common silent bug in Indian market-data pipelines (§4.3)."
            )
        # Truncated, not rounded: rounding 999999us rolls the second over and
        # can move a timestamp across a session boundary.
        return obj.astimezone(UTC).replace(microsecond=0).isoformat()

    if isinstance(obj, date):
        return obj.isoformat()

    if isinstance(obj, Enum):
        return _canonicalise(obj.value, path=f"{path}.value")

    # numpy scalars and arrays, without importing numpy. `.item()` on a 0-d
    # value yields the python scalar; `.tolist()` on an array yields nested
    # lists of python scalars. Both then re-enter the normal path, so numpy
    # floats round exactly as python floats do.
    if _is_numpy_scalar(obj):
        return _canonicalise(obj.item(), path=path)
    if _is_numpy_array(obj):
        return _canonicalise(obj.tolist(), path=path)

    if isinstance(obj, Mapping):
        return _canonicalise_mapping(obj, path=path)

    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        # FactBundle and the records inside it are frozen dataclasses (§4.2).
        # Walked field by field rather than via dataclasses.asdict, because
        # asdict deep-copies with its own recursion and would bypass every
        # converter above.
        fields = {f.name: getattr(obj, f.name) for f in dataclasses.fields(obj)}
        return _canonicalise_mapping(fields, path=path)

    if isinstance(obj, (set, frozenset)):
        # Sorted by each element's canonical form, so ordering is total even
        # for a mixed-type set and never depends on PYTHONHASHSEED.
        items = [_canonicalise(v, path=f"{path}{{}}") for v in obj]
        return [item for _, item in sorted(_with_sort_keys(items))]

    if isinstance(obj, Sequence) and not isinstance(obj, (str, bytes, bytearray)):
        # Positional: order is preserved, never sorted. Sorting a bar series
        # would destroy the series.
        return [_canonicalise(v, path=f"{path}[{i}]") for i, v in enumerate(obj)]

    raise CanonicalError(
        f"unsupported type {type(obj).__name__} at {path}. Add an explicit rule "
        "rather than letting it fall through: a default that hashes repr() "
        "would make inputs_hash depend on a memory address."
    )


def _canonicalise_mapping(obj: Mapping, *, path: str) -> dict:
    """Sort keys and omit None values.

    Omission is the §4.2 rule, and it is what makes `{"baseline": None}` and a
    bundle with no baseline key hash identically — they describe the same
    facts, so they must.
    """
    out = {}
    for key in sorted(obj):
        if not isinstance(key, str):
            raise CanonicalError(
                f"non-string key {key!r} at {path}. Coercing it would let 1 and "
                '"1" collide into one hash.'
            )
        value = obj[key]
        if value is None:
            continue
        out[key] = _canonicalise(value, path=f"{path}.{key}")
    return out


def _with_sort_keys(items: list) -> list[tuple[str, Any]]:
    """Pair each already-canonical item with the text used to order it."""
    return [
        (json.dumps(item, sort_keys=True, ensure_ascii=True, separators=(",", ":")), item)
        for item in items
    ]


def _is_numpy_scalar(obj: Any) -> bool:
    module = type(obj).__module__.split(".")[0]
    return module == "numpy" and hasattr(obj, "item") and getattr(obj, "ndim", None) == 0


def _is_numpy_array(obj: Any) -> bool:
    return type(obj).__module__.split(".")[0] == "numpy" and hasattr(obj, "tolist")


def to_canonical_json(obj: Any) -> bytes:
    """Serialise `obj` to the one byte string that represents it.

    Pure ASCII: non-ASCII is \\u-escaped, so the bytes cannot vary with a
    filesystem or locale encoding. Compact separators, because a hash over
    pretty-printed JSON is partly a hash over an indentation preference.
    """
    prepared = _canonicalise(obj)
    text = json.dumps(
        prepared,
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return text.encode("ascii")


def inputs_hash(bundle: Any) -> str:
    """The N1 hash: SHA-256 over the canonical JSON of a bundle's inputs.

    Stored on every `signal_events` row and returned by
    `/api/brief/explain/{id}`, so that any displayed number can be traced back
    to the exact inputs it was computed from.
    """
    return hashlib.sha256(to_canonical_json(bundle)).hexdigest()
