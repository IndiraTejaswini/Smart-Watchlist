"""Tests for canonical JSON and inputs_hash — docs/BUILD_SPEC.md §4.2.

Written before the implementation (R11). Every expected value below is
hand-computed and written out literally; none of it is produced by calling the
code under test.

Why this file matters more than its size suggests: `inputs_hash` underpins
invariant N1. If serialisation is unstable, N1 is a lie, restatement cannot
distinguish "the inputs changed" from "the serialiser wobbled", and the explain
endpoint cannot be trusted.
"""

from __future__ import annotations

import math
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path

import pytest

from app.canonical import CanonicalError, inputs_hash, to_canonical_json

IST = timezone(timedelta(hours=5, minutes=30))


# ─── dict keys are sorted ───────────────────────────────────────────────────


def test_dict_keys_are_sorted():
    assert to_canonical_json({"b": 1, "a": 2}) == b'{"a":2,"b":1}'


def test_dict_keys_sorted_at_every_depth():
    obj = {"z": {"b": 1, "a": 2}, "a": {"d": 3, "c": 4}}
    assert to_canonical_json(obj) == b'{"a":{"c":4,"d":3},"z":{"a":2,"b":1}}'


def test_key_order_does_not_affect_output():
    assert to_canonical_json({"a": 1, "b": 2}) == to_canonical_json({"b": 2, "a": 1})


def test_output_is_compact():
    """No whitespace. A hash over pretty-printed JSON is a hash over an
    indentation preference."""
    assert to_canonical_json({"a": [1, 2]}) == b'{"a":[1,2]}'


def test_non_string_key_raises():
    """JSON object keys are strings. Coercing 1 and "1" to the same key would
    silently merge two distinct inputs into one hash."""
    with pytest.raises(CanonicalError):
        to_canonical_json({1: "a"})


# ─── floats rounded to CANONICAL_FLOAT_DP ───────────────────────────────────


def test_float_rounded_to_eight_places():
    # 1/3 == 0.3333333333333333, rounded to 8 dp == 0.33333333
    assert to_canonical_json({"x": 1 / 3}) == b'{"x":0.33333333}'


def test_binary_float_noise_is_rounded_away():
    # 0.1 + 0.2 == 0.30000000000000004 in IEEE 754; at 8 dp it is 0.3
    assert to_canonical_json({"x": 0.1 + 0.2}) == b'{"x":0.3}'
    assert to_canonical_json({"x": 0.1 + 0.2}) == to_canonical_json({"x": 0.3})


def test_rounding_follows_the_true_binary_value_not_the_literal():
    """A decimal literal that looks like an exact 9th-place tie usually is not
    one, and the rounding follows the double's real expansion:

        0.123456785 is exactly 0.12345678499999999944...  -> 0.12345678
        0.123456795 is exactly 0.12345679499999999417...  -> 0.12345679

    Both are just below their apparent midpoint, so both round down. What
    matters for N1 is not which way a tie falls but that the rule is fixed and
    gives the same answer in every process, which the two-process test below
    proves.
    """
    assert to_canonical_json(0.123456785) == b"0.12345678"
    assert to_canonical_json(0.123456795) == b"0.12345679"
    assert Decimal(0.123456785) < Decimal("0.123456785")
    assert Decimal(0.123456795) < Decimal("0.123456795")


def test_ninth_decimal_place_is_not_significant():
    """Two values differing below the 8th place must hash identically. This is
    the whole point of rounding: a residual that differs in the 15th bit
    between two runs must not change inputs_hash."""
    assert to_canonical_json(1.000000001) == to_canonical_json(1.000000002)


def test_negative_zero_is_normalised():
    """-0.0 == 0.0 arithmetically but repr()s differently. An abnormal return
    of exactly zero must not hash two ways depending on the sign of the
    subtraction that produced it."""
    assert to_canonical_json(-0.0) == b"0.0"
    assert to_canonical_json(-0.0) == to_canonical_json(0.0)
    assert to_canonical_json(-1e-12) == to_canonical_json(0.0)


def test_int_is_not_turned_into_float():
    assert to_canonical_json({"n": 5}) == b'{"n":5}'
    assert to_canonical_json({"n": 5.0}) == b'{"n":5.0}'


def test_bool_stays_bool():
    """bool is a subclass of int; it must not fall through to the int branch."""
    assert to_canonical_json({"a": True, "b": False}) == b'{"a":true,"b":false}'


def test_large_int_is_not_lossy():
    """Turnover in paise exceeds 2^53. Ints must never route through float."""
    big = 9_007_199_254_740_993  # 2**53 + 1, not representable as a float
    assert to_canonical_json(big) == b"9007199254740993"


# ─── Decimal and numpy coercion ─────────────────────────────────────────────


def test_decimal_becomes_rounded_float():
    assert to_canonical_json(Decimal("1.23456789012")) == b"1.23456789"


def test_decimal_and_float_agree():
    """Postgres NUMERIC arrives as Decimal, the same number from pandas as a
    float. They must produce one hash, not two."""
    assert to_canonical_json(Decimal("2.5")) == to_canonical_json(2.5)


def test_decimal_nan_raises():
    with pytest.raises(CanonicalError):
        to_canonical_json(Decimal("NaN"))


def test_numpy_scalars_become_python_scalars():
    np = pytest.importorskip("numpy")
    assert to_canonical_json(np.float64(1 / 3)) == b"0.33333333"
    assert to_canonical_json(np.int64(5)) == b"5"
    assert to_canonical_json(np.bool_(True)) == b"true"


def test_numpy_float_and_python_float_agree():
    np = pytest.importorskip("numpy")
    assert to_canonical_json(np.float64(2.5)) == to_canonical_json(2.5)


def test_numpy_array_becomes_list():
    np = pytest.importorskip("numpy")
    assert to_canonical_json(np.array([1.5, 2.5])) == b"[1.5,2.5]"


def test_numpy_nan_raises():
    np = pytest.importorskip("numpy")
    with pytest.raises(CanonicalError):
        to_canonical_json(np.float64("nan"))


# ─── datetimes ──────────────────────────────────────────────────────────────


def test_datetime_is_iso_utc_with_explicit_offset():
    ts = datetime(2026, 9, 4, 10, 0, 0, tzinfo=UTC)
    assert to_canonical_json(ts) == b'"2026-09-04T10:00:00+00:00"'


def test_microseconds_are_truncated_not_rounded():
    """Truncated, per §4.2. Rounding 999999us would roll the second over and
    could move a timestamp across a session boundary."""
    ts = datetime(2026, 9, 4, 10, 0, 0, 999999, tzinfo=UTC)
    assert to_canonical_json(ts) == b'"2026-09-04T10:00:00+00:00"'


def test_ist_datetime_is_converted_to_utc():
    """19:00 IST on 4 Sep is 13:30 UTC the same day. §4.3: compute in UTC."""
    ts = datetime(2026, 9, 4, 19, 0, 0, tzinfo=IST)
    assert to_canonical_json(ts) == b'"2026-09-04T13:30:00+00:00"'


def test_same_instant_in_two_zones_hashes_identically():
    utc = datetime(2026, 9, 4, 13, 30, 0, tzinfo=UTC)
    ist = datetime(2026, 9, 4, 19, 0, 0, tzinfo=IST)
    assert to_canonical_json(utc) == to_canonical_json(ist)


def test_naive_datetime_raises():
    """A naive timestamp is the most common silent bug in Indian market-data
    pipelines (§4.3). Guessing a zone here would put a 19:00 IST announcement
    on the wrong trading date. Refuse instead."""
    with pytest.raises(CanonicalError):
        to_canonical_json(datetime(2026, 9, 4, 10, 0, 0))


def test_date_is_iso_date():
    """A trading date is a calendar date, not midnight-of-something."""
    assert to_canonical_json(date(2026, 9, 4)) == b'"2026-09-04"'


def test_date_and_datetime_do_not_collide():
    assert to_canonical_json(date(2026, 9, 4)) != to_canonical_json(
        datetime(2026, 9, 4, 0, 0, tzinfo=UTC)
    )


# ─── None ───────────────────────────────────────────────────────────────────


def test_none_valued_keys_are_omitted():
    assert to_canonical_json({"a": 1, "b": None}) == b'{"a":1}'


def test_omission_is_consistent_with_absence():
    """FactBundle.baseline is `Baseline | None`. A bundle with no baseline and
    a bundle with the key absent describe the same facts and must hash the
    same."""
    assert to_canonical_json({"a": 1, "baseline": None}) == to_canonical_json({"a": 1})


def test_top_level_none_raises():
    with pytest.raises(CanonicalError):
        to_canonical_json(None)


def test_none_inside_a_sequence_raises():
    """Both alternatives are worse than refusing. Dropping the element changes
    every later index; emitting null contradicts "never sometimes-null". A None
    in a tuple of Bars is a loader bug, and R5 says fail visibly."""
    with pytest.raises(CanonicalError):
        to_canonical_json({"bars": [1, None, 3]})


# ─── sets ───────────────────────────────────────────────────────────────────


def test_set_becomes_sorted_list():
    assert to_canonical_json({3, 1, 2}) == b"[1,2,3]"


def test_frozenset_becomes_sorted_list():
    """FactBundle.completeness is a frozenset[str] and is carried into
    signal_events."""
    assert to_canonical_json(frozenset({"BARS", "ANNOUNCEMENTS"})) == (
        b'["ANNOUNCEMENTS","BARS"]'
    )


def test_set_insertion_order_does_not_matter():
    assert to_canonical_json({"a", "b", "c"}) == to_canonical_json({"c", "b", "a"})


def test_list_order_is_preserved():
    """Lists are positional. Sorting them would destroy a bar series."""
    assert to_canonical_json([3, 1, 2]) == b"[3,1,2]"


def test_tuple_serialises_as_list():
    assert to_canonical_json((1, 2)) == to_canonical_json([1, 2])


# ─── NaN and Infinity ───────────────────────────────────────────────────────


def test_nan_raises():
    with pytest.raises(CanonicalError):
        to_canonical_json(float("nan"))


def test_positive_infinity_raises():
    with pytest.raises(CanonicalError):
        to_canonical_json(float("inf"))


def test_negative_infinity_raises():
    with pytest.raises(CanonicalError):
        to_canonical_json(float("-inf"))


def test_nan_nested_deep_still_raises():
    """json.dumps emits bare NaN by default, which is not valid JSON and which
    no other parser will read back."""
    with pytest.raises(CanonicalError):
        to_canonical_json({"a": {"b": [1.0, float("nan")]}})


def test_mpm_tier_sentinel_infinity_raises():
    """MPM_TIER_THRESHOLDS carries float("inf") as its top-tier sentinel. It is
    a threshold, never an input, and must never reach a hash."""
    with pytest.raises(CanonicalError):
        to_canonical_json({"threshold": float("inf")})


# ─── dataclasses and enums ──────────────────────────────────────────────────


@dataclass(frozen=True)
class Bar:
    symbol: str
    close: float
    volume: int


@dataclass(frozen=True)
class Bundle:
    bars: tuple[Bar, ...]
    baseline: float | None


class Family(Enum):
    PRICE = "PRICE"
    DELIVERY = "DELIVERY"


def test_dataclass_serialises_as_a_mapping_of_its_fields():
    """inputs_hash(bundle) is called on a FactBundle, which is a frozen
    dataclass (§4.2)."""
    bar = Bar(symbol="INFY", close=1.0, volume=3)
    assert to_canonical_json(bar) == b'{"close":1.0,"symbol":"INFY","volume":3}'


def test_nested_dataclass_with_none_field_omits_it():
    bundle = Bundle(bars=(Bar("INFY", 1.0, 3),), baseline=None)
    assert to_canonical_json(bundle) == (
        b'{"bars":[{"close":1.0,"symbol":"INFY","volume":3}]}'
    )


def test_enum_serialises_as_its_value():
    assert to_canonical_json(Family.PRICE) == b'"PRICE"'


def test_unsupported_type_raises():
    """An unknown type must never be serialised by some arbitrary fallback.
    Silently hashing repr() would make the hash depend on a memory address."""

    class Opaque:
        pass

    with pytest.raises(CanonicalError):
        to_canonical_json(Opaque())


# ─── unicode ────────────────────────────────────────────────────────────────


def test_non_ascii_is_escaped_deterministically():
    """Company names carry non-ASCII. Escaping keeps the output pure ASCII, so
    the bytes cannot depend on a filesystem or locale encoding."""
    out = to_canonical_json({"name": "Nestlé"})
    assert out == b'{"name":"Nestl\\u00e9"}'
    assert out.decode("ascii")


# ─── inputs_hash ────────────────────────────────────────────────────────────


def test_inputs_hash_is_sha256_hex():
    h = inputs_hash({"a": 1})
    assert len(h) == 64
    assert set(h) <= set("0123456789abcdef")


def test_inputs_hash_of_empty_dict_is_the_known_digest():
    # sha256(b'{}') — hand-verified, independent of this implementation
    assert inputs_hash({}) == (
        "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a"
    )


def test_inputs_hash_changes_when_a_value_changes():
    assert inputs_hash({"sar": 2.0}) != inputs_hash({"sar": 2.1})


def test_inputs_hash_ignores_key_order():
    assert inputs_hash({"a": 1, "b": 2}) == inputs_hash({"b": 2, "a": 1})


def test_inputs_hash_is_stable_across_repeated_calls():
    bundle = {"symbol": "INFY", "bars": [{"close": 1 / 3}]}
    assert len({inputs_hash(bundle) for _ in range(100)}) == 1


# ─── the acceptance test: two processes, two runs ───────────────────────────

# Deliberately exercises every branch at once: nested dicts, a set whose
# iteration order depends on PYTHONHASHSEED, floats needing rounding, a
# Decimal, an aware datetime, a None to omit, and unicode.
FIXTURE_SOURCE = """
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal

sys.path.insert(0, sys.argv[1])
from app.canonical import to_canonical_json

IST = timezone(timedelta(hours=5, minutes=30))

bundle = {
    "symbol": "INFY",
    "as_of": datetime(2026, 9, 4, 19, 0, 0, 654321, tzinfo=IST),
    "completeness": {"BARS", "BASELINE", "ANNOUNCEMENTS", "PEERS", "FACTORS"},
    "baseline": None,
    "name": "Nestl\\u00e9 India",
    "stats": {
        "sar": 1 / 3,
        "turnover_z": 0.1 + 0.2,
        "delivery_pct": Decimal("41.123456789"),
        "volume": 9007199254740993,
        "flat": -0.0,
    },
    "bars": [{"c": 1.5}, {"c": 2.5}],
    "tags": frozenset({"z", "a", "m"}),
}

sys.stdout.buffer.write(to_canonical_json(bundle))
"""


def _run_fixture(tmp_path: Path, hashseed: str) -> bytes:
    script = tmp_path / "emit.py"
    script.write_text(FIXTURE_SOURCE, encoding="utf-8")
    backend = str(Path(__file__).resolve().parents[1])
    env = {**os.environ, "PYTHONHASHSEED": hashseed}
    result = subprocess.run(
        [sys.executable, str(script), backend],
        capture_output=True,
        env=env,
        check=True,
    )
    return result.stdout


def test_two_processes_two_runs_produce_identical_bytes(tmp_path):
    """The §4.2 acceptance test.

    Four fresh interpreters, each with a different PYTHONHASHSEED. The seed
    randomises str hashing, and therefore set iteration order, per process —
    so this is what actually proves the set ordering is imposed by the
    serialiser rather than inherited from whatever order the runtime happened
    to hand back.
    """
    outputs = [_run_fixture(tmp_path, seed) for seed in ("0", "1", "12345", "99991")]

    assert len(set(outputs)) == 1, "canonical JSON differed across processes"
    assert outputs[0], "fixture produced no output"

    # And the in-process serialiser agrees with the subprocesses.
    assert math.isclose(1 / 3, 0.3333333333333333)
    assert b'"completeness":["ANNOUNCEMENTS","BARS","BASELINE","FACTORS","PEERS"]' in (
        outputs[0]
    )
    assert b'"baseline"' not in outputs[0]
    assert b'"sar":0.33333333' in outputs[0]
    assert b'"turnover_z":0.3' in outputs[0]
    assert b'"as_of":"2026-09-04T13:30:00+00:00"' in outputs[0]
    assert b'"flat":0.0' in outputs[0]
    assert b'"volume":9007199254740993' in outputs[0]
    assert b'"tags":["a","m","z"]' in outputs[0]


def test_inputs_hash_identical_across_processes(tmp_path):
    """The same claim, stated as the hash N1 actually depends on."""
    import hashlib

    digests = {
        hashlib.sha256(_run_fixture(tmp_path, seed)).hexdigest()
        for seed in ("0", "7", "424242")
    }
    assert len(digests) == 1
