"""Frozen Entry Course Index v1 reference calculation.

This pure module defines the development-selected course distribution. It does
not read a database, update a rating, or integrate with Prediction.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable


EDOGAWA_VENUE_CODE = 3
HISTORY_START = date(2017, 1, 1)
COURSES = (1, 2, 3, 4, 5, 6)
READY = "READY"
NOT_EVALUABLE = "NOT_EVALUABLE"


@dataclass(frozen=True)
class CourseEntry:
    boat_no: int
    actual_course: int | None
    finish_position: int | None
    has_result: bool = True


@dataclass(frozen=True)
class CourseRace:
    race_date: date
    venue_code: int
    result_state: str
    entries: tuple[CourseEntry, ...]


@dataclass(frozen=True)
class CourseProbability:
    status: str
    probabilities: tuple[float, ...] | None


def window_start(prediction_date: date) -> date:
    """Inclusive start: same month/day in the previous year, Feb 29 -> Feb 28."""
    try:
        return prediction_date.replace(year=prediction_date.year - 1)
    except ValueError:
        return prediction_date.replace(year=prediction_date.year - 1, day=28)


def eligible(race: CourseRace) -> bool:
    """Match the development course-specific cohort, independent of Rating STRICT."""
    entries = race.entries
    return (
        len(entries) == 6
        and {entry.boat_no for entry in entries} == set(COURSES)
        and race.result_state == "RESULT_RECORDS_PRESENT"
        and all(entry.has_result for entry in entries)
        and {entry.actual_course for entry in entries} == set(COURSES)
        and any(entry.finish_position is not None for entry in entries)
    )


def course_counts_for_day(
    prediction_date: date, races: Iterable[CourseRace]
) -> dict[int, tuple[int, ...]]:
    """Count only nationally eligible results in [D minus one year, D)."""
    start = window_start(prediction_date)
    counts = {boat_no: [0] * 6 for boat_no in COURSES}
    for race in races:
        if not (HISTORY_START <= race.race_date and start <= race.race_date < prediction_date):
            continue
        if race.venue_code == EDOGAWA_VENUE_CODE or not eligible(race):
            continue
        for entry in race.entries:
            counts[entry.boat_no][entry.actual_course - 1] += 1
    return {boat_no: tuple(values) for boat_no, values in counts.items()}


def probabilities_from_counts(counts: tuple[int, ...]) -> CourseProbability:
    """No smoothing or fallback; a zero cell has probability zero."""
    if len(counts) != 6 or any(not isinstance(value, int) or value < 0 for value in counts):
        raise ValueError("expected six nonnegative integer course counts")
    total = sum(counts)
    if total == 0:
        return CourseProbability(NOT_EVALUABLE, None)
    probabilities = tuple(value / total for value in counts)
    assert all(0.0 <= value <= 1.0 for value in probabilities)
    assert abs(sum(probabilities) - 1.0) < 1e-12
    return CourseProbability(READY, probabilities)


def probabilities_for_day(
    prediction_date: date, races: Iterable[CourseRace]
) -> dict[int, CourseProbability]:
    """Each D race uses the same per-boat D-1 state; D results never enter it."""
    return {
        boat_no: probabilities_from_counts(counts)
        for boat_no, counts in course_counts_for_day(prediction_date, races).items()
    }
