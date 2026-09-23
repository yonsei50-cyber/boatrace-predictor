"""Pure reference for frozen Motor A v1; no database or Prediction side effects.

The source-meeting reconstruction and day replay mirror the 2017-2024
development code. Scores are continuous residual summaries, not probabilities.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Iterable, Mapping


FINISH_POINTS = {1: 10, 2: 8, 3: 6, 4: 4, 5: 2, 6: 1}
READY = "READY"
NOT_EVALUABLE = "NOT_EVALUABLE"
MeetingKey = tuple[int, date]
SourceDays = Mapping[tuple[int, date], tuple[str, str]]


@dataclass(frozen=True)
class MotorIdentity:
    venue_code: int
    generation_start_year: int
    motor_no: int


@dataclass(frozen=True)
class MeetingDay:
    status: str
    start: date | None
    end: date | None
    reasons: tuple[str, ...]

    @property
    def current_known(self) -> bool:
        # Exactly the development read_mapping rule, including NO_FINAL_9.
        return self.start is not None and (
            self.status == "CERTIFIED" or self.reasons == ("NO_FINAL_9",)
        )


@dataclass(frozen=True)
class MotorEntry:
    day: date
    venue_code: int
    race_no: int
    boat_no: int
    player_id: int | None
    motor: MotorIdentity | None
    finish_state: str | None
    finish_position: int | None
    has_canonical_result: bool
    national_win_rate_status: str | None
    national_win_rate: float | None


@dataclass(frozen=True)
class MotorAFeature:
    day: date
    venue_code: int
    race_no: int
    boat_no: int
    motor: MotorIdentity
    meeting: MeetingKey | None
    base_status: str
    motor_a_base3: float | None
    base_n_meetings: int
    base_n_uses: int
    base_residual_sum: float  # Companion quantity, not a third model score.
    current_status: str
    motor_a_current: float | None
    current_n_uses: int


def eligibility_reason(entry: MotorEntry) -> str | None:
    """First failing development condition; None means eligible."""
    if entry.motor is None:
        return "MOTOR_UNKNOWN"
    if entry.motor.venue_code != entry.venue_code:
        raise ValueError("motor venue disagrees with the canonical race")
    if entry.player_id is None:
        return "PLAYER_UNKNOWN"
    if not entry.has_canonical_result or entry.finish_state == "NO_INDIVIDUAL_RESULT":
        return "RESULT_MISSING"
    if entry.finish_state != "NUMERIC_VALID" or entry.finish_position not in FINISH_POINTS:
        return "FINISH_" + str(entry.finish_state)
    if entry.national_win_rate_status != "VALID" or entry.national_win_rate is None:
        return "RATE_" + str(entry.national_win_rate_status)
    return None


def motor_residual(entry: MotorEntry) -> float:
    if eligibility_reason(entry) is not None:
        raise ValueError("residual requires an eligible canonical entry")
    return FINISH_POINTS[entry.finish_position] - float(entry.national_win_rate)


def build_meeting_days(l1: SourceDays, b1: SourceDays, k1: SourceDays) -> dict[tuple[int, date], MeetingDay]:
    """Port of the supported development builder; source markers, never date gaps."""
    by_venue: dict[int, list[date]] = defaultdict(list)
    for venue, day in l1:
        by_venue[venue].append(day)
    meetings: list[dict] = []
    for venue, days in sorted(by_venue.items()):
        active = None
        for day in sorted(days):
            lnum, title = l1[(venue, day)]
            b = b1.get((venue, day))
            k = k1.get((venue, day))
            bnum = b[0] if b else None
            valid_source = b is not None and k is not None and bnum == k[0] and (
                lnum in ("", "9") or lnum == bnum
            )
            start_signal = lnum == "1" or (lnum == "" and bnum == "1")
            repeated_start = (
                active is not None and active["title"] == title
                and active["last_lnum"] == "" and active["last_bnum"] == "1"
                and bnum == "1"
            )
            if start_signal and not repeated_start:
                if active is not None:
                    active["reasons"].add("NO_FINAL_9")
                    meetings.append(active)
                active = {"venue": venue, "start": day, "end": None, "days": [],
                          "title": title, "last_lnum": None, "last_bnum": None,
                          "reasons": set()}
            elif active is None:
                active = {"venue": venue, "start": None, "end": None, "days": [],
                          "title": title, "last_lnum": None, "last_bnum": None,
                          "reasons": {"NO_START_1"}}
            if not valid_source:
                active["reasons"].add("L1_B1_K1_DAY_DISAGREEMENT")
            if title != active["title"]:
                active["reasons"].add("L1_TITLE_CHANGE")
            if not start_signal and active["last_bnum"] is not None and bnum is not None:
                prev = int(active["last_bnum"])
                current = int(bnum)
                if current > prev + 1 or current < prev - 1:
                    active["reasons"].add("UNSUPPORTED_DAY_NUMBER_JUMP")
                elif current == prev and lnum and active["last_lnum"]:
                    active["reasons"].add("REPEATED_COMPLETED_RACE_DAY")
                elif current < prev and lnum and active["last_lnum"]:
                    active["reasons"].add("REVERSED_COMPLETED_RACE_DAY")
            active["days"].append(day)
            active["last_lnum"] = lnum
            active["last_bnum"] = bnum
            if lnum == "9":
                active["end"] = day
                meetings.append(active)
                active = None
        if active is not None:
            active["reasons"].add("NO_FINAL_9")
            meetings.append(active)
    mapped = {}
    for meeting in meetings:
        if meeting["end"] is None:
            meeting["reasons"].add("NO_FINAL_9")
        status = "CERTIFIED" if not meeting["reasons"] else "UNKNOWN"
        for day in meeting["days"]:
            mapped[(meeting["venue"], day)] = MeetingDay(
                status, meeting["start"], meeting["end"],
                tuple(sorted(meeting["reasons"])),
            )
    return mapped


def replay_development(
    entries: Iterable[MotorEntry], meeting_days: Mapping[tuple[int, date], MeetingDay]
) -> list[MotorAFeature]:
    """Score eligible rows from frozen D-1 state, then commit all D labels at day end.

    Ineligible rows still mark motor/meeting visits, as in the development scan.
    Input is canonical entry data and a previously source-verified day mapping.
    """
    ends: dict[date, set[MeetingKey]] = defaultdict(set)
    for (venue, _), info in meeting_days.items():
        if info.status == "CERTIFIED" and info.end is not None:
            ends[info.end].add((venue, info.start))
    certified = {key for groups in ends.values() for key in groups}
    meeting_sum: dict[tuple[MotorIdentity, MeetingKey], float] = defaultdict(float)
    meeting_n: dict[tuple[MotorIdentity, MeetingKey], int] = defaultdict(int)
    meeting_motors: dict[MeetingKey, set[MotorIdentity]] = defaultdict(set)
    completed: dict[MotorIdentity, list[tuple[MeetingKey, float, int]]] = defaultdict(list)
    last_meeting: dict[MotorIdentity, MeetingKey | None] = {}
    pending: list[tuple[MotorIdentity, MeetingKey | None, float]] = []
    features: list[MotorAFeature] = []
    day_now = None

    def finish_day(day: date) -> None:
        for motor, meeting, residual in pending:
            if meeting is None:
                completed[motor].clear()
            else:
                key = (motor, meeting)
                meeting_sum[key] += residual
                meeting_n[key] += 1
        pending.clear()
        for meeting in ends.get(day, ()):
            for motor in meeting_motors.get(meeting, ()):
                key = (motor, meeting)
                if meeting_n[key]:
                    completed[motor].append((
                        meeting, meeting_sum[key] / meeting_n[key], meeting_n[key]
                    ))

    ordered = sorted(entries, key=lambda e: (e.day, e.venue_code, e.race_no, e.boat_no))
    for entry in ordered:
        if entry.day != day_now:
            if day_now is not None:
                finish_day(day_now)
            day_now = entry.day
        info = meeting_days.get((entry.venue_code, entry.day))
        if info is None:
            raise ValueError("no source meeting record for canonical venue-day")
        meeting = (entry.venue_code, info.start) if info.current_known else None
        if meeting is not None and not (
            info.start <= entry.day and (info.end is None or entry.day <= info.end)
        ):
            raise ValueError("meeting date interval mismatch")
        motor = entry.motor
        if motor is not None:
            previous = last_meeting.get(motor)
            if meeting is None:
                completed[motor].clear()
                last_meeting[motor] = None
            elif previous != meeting:
                if previous is not None and previous not in certified:
                    completed[motor].clear()
                last_meeting[motor] = meeting
        if motor is not None and meeting is not None:
            meeting_motors[meeting].add(motor)
        if eligibility_reason(entry) is not None:
            continue
        residual = motor_residual(entry)
        if meeting is None:
            selected = []
            current_n = 0
        else:
            selected = completed[motor][-3:]
            current_n = meeting_n[(motor, meeting)]
        base_n = sum(item[2] for item in selected)
        features.append(MotorAFeature(
            day=entry.day, venue_code=entry.venue_code,
            race_no=entry.race_no, boat_no=entry.boat_no, motor=motor,
            meeting=meeting,
            base_status=READY if selected else NOT_EVALUABLE,
            motor_a_base3=(sum(item[1] for item in selected) / len(selected)
                           if selected else None),
            base_n_meetings=len(selected), base_n_uses=base_n,
            base_residual_sum=sum(item[1] * item[2] for item in selected),
            current_status=READY if current_n else NOT_EVALUABLE,
            motor_a_current=(meeting_sum[(motor, meeting)] / current_n
                             if current_n else None),
            current_n_uses=current_n,
        ))
        pending.append((motor, meeting, residual))
    if day_now is not None:
        finish_day(day_now)
    return features
