"""Pure, pre-2025 tide features for Natural Environment v1.

The caller supplies rows read from ``pckyotei.public.apd_choihyo``.  This
module performs no database access and deliberately rejects a race timestamp
in 2025 or later so the development boundary cannot be crossed accidentally.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
import math
from typing import Iterable, Mapping, Any


SOURCE_TABLE = "pckyotei.public.apd_choihyo"
PREHOLDOUT_END = datetime(2025, 1, 1)

VENUE_TO_CHITEN_CODE = {
    "19": "WH",
    "16": "UN",
    "03": "TK",
    "04": "TK",
    "22": "QF",
    "18": "QA",
    "17": "Q8",
    "24": "NS",
    "20": "N1",
    "06": "MI",
    "14": "KM",
    "15": "AX",
}

_LOW = "LOW_TIDE"
_HIGH = "HIGH_TIDE"
_REQUIRED_FIELDS = (
    "data_kubun",
    "chiten_code",
    "kaisai_nen",
    "kaisai_tsukihi",
    "jikoku",
    "choi",
)


@dataclass(frozen=True)
class _Extremum:
    timestamp: datetime
    kind: str
    height: Decimal
    lineage: dict[str, Any]


def _two_digit_venue(value: object) -> str:
    text = str(value).strip()
    return text.zfill(2) if text.isdigit() and len(text) <= 2 else text


def tide_chiten_code(kyoteijo_code: object) -> str | None:
    """Return the confirmed tide station mapping, or ``None`` if inapplicable."""
    return VENUE_TO_CHITEN_CODE.get(_two_digit_venue(kyoteijo_code))


def _digits(value: object, width: int, field: str) -> str:
    text = str(value).strip()
    if not text.isdigit() or len(text) > width:
        raise ValueError(f"invalid {field}")
    return text.zfill(width)


def race_deadline_timestamp(
    kaisai_nen: object,
    kaisai_tsukihi: object,
    shimekiri_yotei_jikoku: object,
) -> datetime:
    """Parse the L2 year, MMDD, and scheduled deadline HHMM fields."""
    stamp = datetime.strptime(
        _digits(kaisai_nen, 4, "kaisai_nen")
        + _digits(kaisai_tsukihi, 4, "kaisai_tsukihi")
        + _digits(shimekiri_yotei_jikoku, 4, "shimekiri_yotei_jikoku"),
        "%Y%m%d%H%M",
    )
    _require_preholdout(stamp)
    return stamp


def _require_preholdout(timestamp: datetime) -> None:
    if timestamp.tzinfo is not None and timestamp.utcoffset() is not None:
        raise ValueError("source timestamps must be naive local timestamps")
    if timestamp >= PREHOLDOUT_END:
        raise ValueError("Natural Environment v1 calculation is limited to 2024-12-31")


def _empty_feature(
    *,
    source_available: bool,
    status: str,
    reason: str | None,
    lineage: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "tide_source_available": source_available,
        "tide_height": None,
        "tide_direction": None,
        "tide_change_speed": None,
        "tide_status": status,
        "tide_unresolved_reason": reason,
        "tide_extrema_lineage": [] if lineage is None else lineage,
    }


def _timestamp_from_row(row: Mapping[str, Any]) -> datetime:
    return datetime.strptime(
        _digits(row["kaisai_nen"], 4, "kaisai_nen")
        + _digits(row["kaisai_tsukihi"], 4, "kaisai_tsukihi")
        + _digits(row["jikoku"], 4, "jikoku"),
        "%Y%m%d%H%M",
    )


def _extremum(row: Mapping[str, Any]) -> _Extremum:
    missing = [field for field in _REQUIRED_FIELDS if field not in row]
    if missing:
        raise ValueError("missing source field: " + ",".join(missing))
    timestamp = _timestamp_from_row(row)
    _require_preholdout(timestamp)
    data_kubun_text = str(row["data_kubun"]).strip()
    if data_kubun_text == "1":
        kind = _LOW
    elif data_kubun_text == "2":
        kind = _HIGH
    else:
        raise ValueError("invalid data_kubun")
    try:
        height = Decimal(str(row["choi"]).strip())
    except (InvalidOperation, ValueError):
        raise ValueError("invalid choi") from None
    if not height.is_finite():
        raise ValueError("non-finite choi")
    lineage = {
        "source_table": SOURCE_TABLE,
        "data_kubun_raw": row["data_kubun"],
        "chiten_code_raw": row["chiten_code"],
        "kaisai_nen_raw": row["kaisai_nen"],
        "kaisai_tsukihi_raw": row["kaisai_tsukihi"],
        "jikoku_raw": row["jikoku"],
        "choi_raw": row["choi"],
        "extremum_timestamp": timestamp.isoformat(timespec="minutes"),
        "extremum_kind": kind,
    }
    return _Extremum(timestamp, kind, height, lineage)


def _available_feature(
    *, height: Decimal, direction: str, speed: Decimal,
    extrema: Iterable[_Extremum],
) -> dict[str, Any]:
    height_float = float(height)
    speed_float = float(speed)
    if not math.isfinite(height_float) or not math.isfinite(speed_float):
        return _empty_feature(
            source_available=True, status="UNRESOLVED",
            reason="NON_FINITE_CALCULATION",
            lineage=[item.lineage for item in extrema],
        )
    return {
        "tide_source_available": True,
        "tide_height": height_float,
        "tide_direction": direction,
        "tide_change_speed": speed_float,
        "tide_status": "AVAILABLE",
        "tide_unresolved_reason": None,
        "tide_extrema_lineage": [item.lineage for item in extrema],
    }


def derive_tide_feature(
    kyoteijo_code: object,
    race_deadline: datetime,
    source_rows: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Derive one race-level tide feature from surrounding source extrema.

    Rows for other tide stations may be present and are ignored.  For an
    applicable venue, all rows for its mapped station must be structurally
    valid.  The closest strict predecessor and successor may be on the prior
    or following calendar day.
    """
    _require_preholdout(race_deadline)
    chiten_code = tide_chiten_code(kyoteijo_code)
    if chiten_code is None:
        return _empty_feature(
            source_available=False, status="NOT_APPLICABLE", reason=None,
        )

    matching = [
        row for row in source_rows
        if str(row.get("chiten_code", "")).strip().upper() == chiten_code
    ]
    if not matching:
        return _empty_feature(
            source_available=True, status="UNRESOLVED",
            reason="NO_EXTREMA_FOR_LOCATION",
        )
    try:
        extrema = sorted((_extremum(row) for row in matching), key=lambda x: x.timestamp)
    except (KeyError, TypeError, ValueError):
        return _empty_feature(
            source_available=True, status="UNRESOLVED",
            reason="INVALID_EXTREMUM_ROW",
        )

    timestamps = [item.timestamp for item in extrema]
    if len(timestamps) != len(set(timestamps)):
        duplicate_lineage = [
            item.lineage for item in extrema if timestamps.count(item.timestamp) > 1
        ]
        return _empty_feature(
            source_available=True, status="UNRESOLVED",
            reason="DUPLICATE_EXTREMUM_TIMESTAMP", lineage=duplicate_lineage,
        )

    exact = [item for item in extrema if item.timestamp == race_deadline]
    if exact:
        item = exact[0]
        return _available_feature(
            height=item.height, direction=item.kind, speed=Decimal(0),
            extrema=exact,
        )

    before = [item for item in extrema if item.timestamp < race_deadline]
    after = [item for item in extrema if item.timestamp > race_deadline]
    if not before or not after:
        relevant = (before[-1:] + after[:1])
        return _empty_feature(
            source_available=True, status="UNRESOLVED",
            reason="NO_BRACKETING_EXTREMA",
            lineage=[item.lineage for item in relevant],
        )
    previous, following = before[-1], after[0]
    pair = [previous, following]
    if (previous.kind, following.kind) == (_LOW, _HIGH):
        direction = "RISING"
    elif (previous.kind, following.kind) == (_HIGH, _LOW):
        direction = "FALLING"
    else:
        return _empty_feature(
            source_available=True, status="UNRESOLVED",
            reason="INVALID_EXTREMUM_SEQUENCE",
            lineage=[item.lineage for item in pair],
        )

    elapsed_seconds = Decimal(str((following.timestamp - previous.timestamp).total_seconds()))
    offset_seconds = Decimal(str((race_deadline - previous.timestamp).total_seconds()))
    if elapsed_seconds <= 0:
        return _empty_feature(
            source_available=True, status="UNRESOLVED",
            reason="INVALID_EXTREMUM_INTERVAL",
            lineage=[item.lineage for item in pair],
        )
    fraction = offset_seconds / elapsed_seconds
    height = previous.height + (following.height - previous.height) * fraction
    elapsed_hours = elapsed_seconds / Decimal(3600)
    speed = abs(following.height - previous.height) / elapsed_hours
    return _available_feature(
        height=height, direction=direction, speed=speed, extrema=pair,
    )
