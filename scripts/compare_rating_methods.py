"""Read-only 2017-2024 chronological comparison of three rating methods.

The database query has a literal upper bound before 2025.  All predictions for
one day are made from the preceding-day state; result and course updates are
applied only after every race on that day has been scored.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from datetime import date
import hashlib
import json
import math
from pathlib import Path
from statistics import fmean
from time import perf_counter

from scripts.db import target_connection


QUERY_VERSION = "rating-method-comparison-2017-2024-v2"
BASE_RATING = 1000.0
RATING_SCALE = 400.0
CONFIRMED_NEWCOMER = "CONFIRMED_NEWCOMER"
NEWCOMER_UNCERTAIN = "NEWCOMER_UNCERTAIN"
ESTABLISHED = "ESTABLISHED"

# Keep the date bound literal and non-configurable: 2025 is the untouched holdout.
EXTRACT_SQL = r"""
WITH boats AS (
  SELECT r.race_id,r.race_date,r.venue_code,r.race_no,e.boat_no,e.player_id,
         b.finish_state,b.finish_position,b.actual_course,s.result_state,
         (z.race_id IS NOT NULL) AS canonical_result
  FROM core.race r
  JOIN core.race_entry e USING(race_id)
  JOIN core.boat_finish_state b USING(race_id,boat_no)
  JOIN core.race_result_state s USING(race_id)
  LEFT JOIN core.race_result z USING(race_id,boat_no)
  WHERE r.race_date >= DATE '2017-01-01'
    AND r.race_date < DATE '2025-01-01'
), flags AS (
  SELECT race_id,
         count(*)=6
         AND bool_and(result_state='RESULT_RECORDS_PRESENT')
         AND bool_and(canonical_result)
         AND count(*) FILTER (WHERE finish_state='NUMERIC_VALID')=6
         AND count(DISTINCT finish_position)=6
         AND min(finish_position)=1 AND max(finish_position)=6 AS common_strict
  FROM boats GROUP BY race_id
)
SELECT b.race_id,b.race_date,b.venue_code,b.race_no,b.boat_no,b.player_id,
       b.finish_state,b.finish_position,b.actual_course,b.result_state,
       b.canonical_result,f.common_strict
FROM boats b JOIN flags f USING(race_id)
ORDER BY b.race_date,b.venue_code,b.race_no,b.race_id,b.boat_no
"""


@dataclass(frozen=True)
class Entry:
    boat_no: int
    player_id: int
    finish_state: str
    finish: int | None
    actual_course: int | None
    canonical_result: bool


@dataclass(frozen=True)
class Race:
    race_id: int
    day: date
    venue: int
    race_no: int
    result_state: str
    common_strict: bool
    entries: tuple[Entry, ...]


def softmax(values):
    if not values:
        return []
    scaled = [v / RATING_SCALE for v in values]
    top = max(scaled)
    weights = [math.exp(v - top) for v in scaled]
    total = sum(weights)
    return [v / total for v in weights]


def pl_second(values):
    """Exact second-place marginals under one Plackett-Luce strength vector."""
    first = softmax(values)
    out = [0.0] * len(values)
    for winner, p_first in enumerate(first):
        denominator = 1.0 - first[winner]
        if denominator <= 0.0:
            continue
        for second in range(len(values)):
            if second != winner:
                out[second] += p_first * first[second] / denominator
    return out


def average_ranks(values, descending=False):
    """One-based average ranks; exact ties remain ties instead of boat-order wins."""
    order = sorted(range(len(values)), key=lambda i: values[i], reverse=descending)
    ranks = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start + 1
        while end < len(order) and values[order[end]] == values[order[start]]:
            end += 1
        rank = ((start + 1) + end) / 2
        for position in range(start, end):
            ranks[order[position]] = rank
        start = end
    return ranks


def spearman_probability_finish(probabilities, entries):
    predicted = average_ranks(probabilities, descending=True)
    actual = [float(e.finish) for e in entries]
    p_mean, a_mean = fmean(predicted), fmean(actual)
    numerator = sum((p - p_mean) * (a - a_mean) for p, a in zip(predicted, actual))
    p_ss = sum((p - p_mean) ** 2 for p in predicted)
    a_ss = sum((a - a_mean) ** 2 for a in actual)
    denominator = math.sqrt(p_ss * a_ss)
    return numerator / denominator if denominator else None


def initialize_rating_map(ratings, players, statuses, base=BASE_RATING):
    """Insert a day's players using one frozen pre-insertion population mean."""
    new_players = sorted(set(players) - ratings.keys())
    if not new_players:
        return {}
    mean = fmean(ratings.values()) if ratings else base
    assigned = {}
    for player in new_players:
        status = statuses.get(player, NEWCOMER_UNCERTAIN)
        # Uncertain debut status must not silently receive the 0.8 discount.
        value = mean * 0.8 if status == CONFIRMED_NEWCOMER else base
        ratings[player] = value
        assigned[player] = value
    return assigned


class MetricSet:
    def __init__(self):
        self.races = 0
        self.log_first = self.log_second = 0.0
        self.brier_first = self.brier_second = 0.0
        self.hit_first = self.hit_second = 0
        self.pl_ranking_log = self.pairwise_log = 0.0
        self.pairwise_comparisons = 0
        self.spearman_sum = 0.0
        self.spearman_evaluable = 0
        self.cal_first = [[0, 0.0, 0] for _ in range(10)]
        self.cal_second = [[0, 0.0, 0] for _ in range(10)]

    def add(self, p_first, p_second, entries):
        first = next(i for i, e in enumerate(entries) if e.finish == 1)
        second = next(i for i, e in enumerate(entries) if e.finish == 2)
        eps = 1e-15
        self.races += 1
        self.log_first -= math.log(max(p_first[first], eps))
        self.log_second -= math.log(max(p_second[second], eps))
        self.brier_first += sum((p - (i == first)) ** 2 for i, p in enumerate(p_first))
        self.brier_second += sum((p - (i == second)) ** 2 for i, p in enumerate(p_second))
        self.hit_first += max(range(6), key=p_first.__getitem__) == first
        self.hit_second += max(range(6), key=p_second.__getitem__) == second
        remaining = set(range(6))
        for index in sorted(range(6), key=lambda i: entries[i].finish):
            denominator = sum(p_first[i] for i in remaining)
            self.pl_ranking_log -= math.log(max(p_first[index] / denominator, eps))
            remaining.remove(index)
        for better in range(6):
            for worse in range(6):
                if entries[better].finish < entries[worse].finish:
                    probability = p_first[better] / (p_first[better] + p_first[worse])
                    self.pairwise_log -= math.log(max(probability, eps))
                    self.pairwise_comparisons += 1
        correlation = spearman_probability_finish(p_first, entries)
        if correlation is not None:
            self.spearman_sum += correlation
            self.spearman_evaluable += 1
        for probs, actual, bins in ((p_first, first, self.cal_first),
                                    (p_second, second, self.cal_second)):
            for i, probability in enumerate(probs):
                b = min(9, int(probability * 10))
                bins[b][0] += 1
                bins[b][1] += probability
                bins[b][2] += i == actual

    def json(self):
        if not self.races:
            return {"races": 0}
        n = self.races
        def calibration(bins):
            return [{"lower": i / 10, "upper": (i + 1) / 10,
                     "observations": row[0],
                     "mean_probability": row[1] / row[0] if row[0] else None,
                     "event_rate": row[2] / row[0] if row[0] else None}
                    for i, row in enumerate(bins)]
        return {
            "races": n,
            "combined_log_loss": (self.log_first + self.log_second) / (2 * n),
            "ranking": {
                "pl_full_ranking_log_loss_per_race": self.pl_ranking_log / n,
                "pairwise_log_loss": self.pairwise_log / self.pairwise_comparisons,
                "pairwise_comparisons": self.pairwise_comparisons,
                "spearman_mean": (self.spearman_sum / self.spearman_evaluable
                                  if self.spearman_evaluable else None),
                "spearman_evaluable_races": self.spearman_evaluable,
                "spearman_undefined_tied_races": n - self.spearman_evaluable,
            },
            "first": {"log_loss": self.log_first / n,
                      "brier": self.brier_first / n,
                      "top1_hit_rate": self.hit_first / n,
                      "calibration": calibration(self.cal_first)},
            "exact_second": {"log_loss": self.log_second / n,
                             "brier": self.brier_second / n,
                             "top1_hit_rate": self.hit_second / n,
                             "calibration": calibration(self.cal_second)},
        }


class BaseModel:
    method = None

    def __init__(self, candidate_id, config):
        self.candidate_id = candidate_id
        self.config = config
        self.metrics = {2023: MetricSet(), 2024: MetricSet()}
        self.selection_2023 = MetricSet()
        self.quarters = {(year, q): MetricSet() for year in (2023, 2024)
                         for q in range(1, 5)}
        self.counts = Counter()
        self.compute_seconds = 0.0
        self.started = config["initialization"] == "WARMUP_2017_2022"

    def reset(self):
        raise NotImplementedError

    def maybe_start(self, day):
        if not self.started and day >= date(2023, 1, 1):
            self.reset()
            self.started = True

    def prepare_day(self, players, statuses):
        raise NotImplementedError

    def predict(self, race):
        raise NotImplementedError

    def deltas(self, race):
        raise NotImplementedError

    def apply(self, deltas):
        raise NotImplementedError

    def combine_day(self, pending):
        raise NotImplementedError

    def after_day(self, races):
        pass

    def update_eligible(self, race):
        return race.common_strict

    def process_day(self, day, races, statuses, collect_validation):
        self.maybe_start(day)
        if not self.started:
            return
        players = {e.player_id for race in races for e in race.entries}
        self.prepare_day(players, statuses)
        pending = []
        for race in races:
            if day.year in (2023, 2024):
                if race.common_strict:
                    prediction = self.predict(race)
                    if day.year == 2023 or collect_validation:
                        self.metrics[day.year].add(*prediction, race.entries)
                        q = (day.month - 1) // 3 + 1
                        self.quarters[(day.year, q)].add(*prediction, race.entries)
                        if day.year == 2023 and day.month >= 4:
                            self.selection_2023.add(*prediction, race.entries)
                else:
                    self.counts[f"{day.year}_scoring_excluded_non_strict"] += 1
            if self.update_eligible(race):
                pending.append(self.deltas(race))
                self.counts[f"{day.year}_update_races"] += 1
        # The model state is unchanged until all D predictions/deltas are fixed.
        if pending:
            self.apply(self.combine_day(pending))
        self.after_day(races)

    def output(self, selected):
        quarter_values = [self.quarters[(2024, q)].json().get("combined_log_loss")
                          for q in range(1, 5)]
        finite_quarters = [value for value in quarter_values if value is not None]
        out = {"candidate_id": self.candidate_id, "status": "SUPPORTED",
               "method": self.method, "config": self.config,
               "counts": dict(sorted(self.counts.items())),
               "tuning_2023": self.metrics[2023].json(),
               "selection_2023_q2_q4_prequential": self.selection_2023.json(),
               "tuning_2023_quarters": {f"Q{q}": self.quarters[(2023, q)].json()
                                         for q in range(1, 5)},
               "selected_by_2023": selected,
               "compute_seconds": self.compute_seconds,
               "stability_2024": {
                   "quarter_combined_log_loss": quarter_values,
                   "min": min(finite_quarters) if finite_quarters else None,
                   "max": max(finite_quarters) if finite_quarters else None,
                   "range": (max(finite_quarters) - min(finite_quarters)
                             if finite_quarters else None)},
               "validation_2024": self.metrics[2024].json(),
               "validation_2024_quarters": {
                   f"Q{q}": self.quarters[(2024, q)].json() for q in range(1, 5)}}
        return out


class CourseSoftmax(BaseModel):
    method = "A_COURSE_SOFTMAX_FIRST_EXACT_SECOND"

    def reset(self):
        self.first = [dict() for _ in range(6)]
        self.second = [dict() for _ in range(6)]
        self.course_counts = defaultdict(lambda: [1] * 6)

    def __init__(self, candidate_id, config):
        super().__init__(candidate_id, config)
        self.reset()

    def prepare_day(self, players, statuses):
        for series in self.first + self.second:
            assigned = initialize_rating_map(series, players, statuses)
            self.counts["initialized_players"] += len(assigned)

    def course_probabilities(self, venue, boat_no):
        counts = self.course_counts[(venue, boat_no)]
        total = sum(counts)
        return [v / total for v in counts]

    def _expected(self, series, race):
        values = []
        for entry in race.entries:
            cp = self.course_probabilities(race.venue, entry.boat_no)
            values.append(sum(cp[c] * series[c][entry.player_id] for c in range(6)))
        return values

    def predict(self, race):
        return softmax(self._expected(self.first, race)), softmax(self._expected(self.second, race))

    def deltas(self, race):
        actual_values_first = [self.first[e.actual_course - 1][e.player_id] for e in race.entries]
        actual_values_second = [self.second[e.actual_course - 1][e.player_id] for e in race.entries]
        pf, ps = softmax(actual_values_first), softmax(actual_values_second)
        rate = self.config["learning_rate"]
        return [(e.player_id, e.actual_course - 1,
                 rate * ((e.finish == 1) - pf[i]),
                 rate * ((e.finish == 2) - ps[i]))
                for i, e in enumerate(race.entries)]

    def update_eligible(self, race):
        courses = [e.actual_course for e in race.entries]
        return (race.common_strict and all(c in range(1, 7) for c in courses)
                and sorted(courses) == [1, 2, 3, 4, 5, 6])

    def apply(self, deltas):
        for player, course, first, second in deltas:
            self.first[course][player] += first
            self.second[course][player] += second

    def combine_day(self, pending):
        combined = defaultdict(lambda: [0.0, 0.0])
        for race_delta in pending:
            for player, course, first, second in race_delta:
                combined[(player, course)][0] += first
                combined[(player, course)][1] += second
        return [(player, course, values[0], values[1])
                for (player, course), values in combined.items()]

    def after_day(self, races):
        for race in races:
            if race.result_state != "RESULT_RECORDS_PRESENT":
                continue
            for entry in race.entries:
                if entry.canonical_result and entry.actual_course in range(1, 7):
                    self.course_counts[(race.venue, entry.boat_no)][entry.actual_course - 1] += 1


class PairwiseElo(BaseModel):
    method = "B_PAIRWISE_ELO_OVERALL"

    def reset(self):
        self.ratings = {}

    def __init__(self, candidate_id, config):
        super().__init__(candidate_id, config)
        self.reset()

    def prepare_day(self, players, statuses):
        self.counts["initialized_players"] += len(
            initialize_rating_map(self.ratings, players, statuses))

    def predict(self, race):
        values = [self.ratings[e.player_id] for e in race.entries]
        return softmax(values), pl_second(values)

    def _valid(self, race):
        return [e for e in race.entries if e.finish_state == "NUMERIC_VALID"
                and e.finish is not None]

    def update_eligible(self, race):
        if self.config["eligibility"] == "STRICT":
            return race.common_strict
        valid = self._valid(race)
        return (race.result_state == "RESULT_RECORDS_PRESENT"
                and len(race.entries) == 6 and len(valid) >= 2
                and len({e.finish for e in valid}) == len(valid))

    def deltas(self, race):
        valid = self._valid(race)
        pairs = len(valid) * (len(valid) - 1) // 2
        weight = 1 / pairs if self.config["pair_weight"] == "RACE_NORMALIZED" else 1.0
        k = self.config["k_factor"] * weight
        delta = defaultdict(float)
        for i, left in enumerate(valid):
            for right in valid[i + 1:]:
                expected = 1 / (1 + math.exp((self.ratings[right.player_id]
                                              - self.ratings[left.player_id]) / RATING_SCALE))
                observed = 1.0 if left.finish < right.finish else 0.0
                change = k * (observed - expected)
                delta[left.player_id] += change
                delta[right.player_id] -= change
        self.counts["numeric_pairs"] += pairs
        return delta

    def apply(self, deltas):
        for player, change in deltas.items():
            self.ratings[player] += change

    def combine_day(self, pending):
        combined = defaultdict(float)
        for race_delta in pending:
            for player, change in race_delta.items():
                combined[player] += change
        return combined


class PlackettLuce(BaseModel):
    method = "C_ONLINE_PLACKETT_LUCE_OVERALL"

    def reset(self):
        self.ratings = {}

    def __init__(self, candidate_id, config):
        super().__init__(candidate_id, config)
        self.reset()

    def prepare_day(self, players, statuses):
        self.counts["initialized_players"] += len(
            initialize_rating_map(self.ratings, players, statuses))

    def predict(self, race):
        values = [self.ratings[e.player_id] for e in race.entries]
        return softmax(values), pl_second(values)

    def deltas(self, race):
        ordered = sorted(race.entries, key=lambda e: e.finish)
        remaining = list(ordered)
        delta = defaultdict(float)
        rate = self.config["learning_rate"]
        while len(remaining) > 1:
            probs = softmax([self.ratings[e.player_id] for e in remaining])
            chosen = remaining[0]
            for entry, probability in zip(remaining, probs):
                delta[entry.player_id] += rate * ((entry is chosen) - probability)
            remaining.pop(0)
        return delta

    def apply(self, deltas):
        for player, change in deltas.items():
            self.ratings[player] += change

    def combine_day(self, pending):
        combined = defaultdict(float)
        for race_delta in pending:
            for player, change in race_delta.items():
                combined[player] += change
        return combined


class Short50Model(BaseModel):
    """Bounded rolling-finish comparator for the deferred SHORT_50 series."""
    method = "SHORT50_ROLLING_FINISH_COMPARATOR"

    def reset(self):
        self.history = defaultdict(lambda: deque(maxlen=50))
        self.overall_sum = defaultdict(float)
        self.overall_count = Counter()
        self.overall_ratings = {}
        self.known_players = set()
        self.short_initials = {}

    def __init__(self, candidate_id, config):
        super().__init__(candidate_id, config)
        self.reset()

    def prepare_day(self, players, statuses):
        confirmed = sorted(p for p in players - self.known_players
                           if statuses.get(p) == CONFIRMED_NEWCOMER)
        if confirmed:
            mean = (fmean(self._current_value(p) for p in self.known_players)
                    if self.known_players else BASE_RATING)
            for player in confirmed:
                self.short_initials[player] = mean * 0.8
        self.known_players.update(players)
        initialize_rating_map(self.overall_ratings, players, statuses)

    @staticmethod
    def _performance(finish):
        return (3.5 - finish) / 2.5

    def _current_value(self, player):
        """Effective D-1 short value without changing metric counters."""
        history = self.history.get(player, ())
        numeric = [value for value in history if value is not None]
        if numeric and (len(history) == 50 or
                        self.config["fallback"] == "AVAILABLE_HISTORY"):
            return BASE_RATING + 100.0 * fmean(numeric)
        if not numeric and player in self.short_initials:
            return self.short_initials[player]
        if self.config["fallback"] == "OVERALL_RATING":
            return self.overall_ratings.get(player, BASE_RATING)
        if self.config["fallback"] == "CAREER_FINISH_MEAN" and self.overall_count[player]:
            return BASE_RATING + 100.0 * self.overall_sum[player] / self.overall_count[player]
        return BASE_RATING

    def _score(self, player, year):
        history = self.history[player]
        numeric = [value for value in history if value is not None]
        if len(history) == 50:
            if numeric:
                self.counts[f"{year}_available"] += 1
                return fmean(numeric)
        if self.config["fallback"] == "AVAILABLE_HISTORY" and numeric:
            self.counts[f"{year}_fallback_available_history_lt50"] += 1
            return fmean(numeric)
        if not numeric and player in self.short_initials:
            self.counts[f"{year}_confirmed_newcomer_initializer"] += 1
            return (self.short_initials[player] - BASE_RATING) / 100.0
        if self.config["fallback"] == "OVERALL_RATING":
            self.counts[f"{year}_fallback_overall_rating"] += 1
            return (self.overall_ratings[player] - BASE_RATING) / 100.0
        if self.config["fallback"] == "CAREER_FINISH_MEAN" and self.overall_count[player]:
            self.counts[f"{year}_fallback_career_finish_mean"] += 1
            return self.overall_sum[player] / self.overall_count[player]
        self.counts[f"{year}_fallback_initializer"] += 1
        return 0.0

    def predict(self, race):
        values = [BASE_RATING + 100.0 * self._score(e.player_id, race.day.year)
                  for e in race.entries]
        return softmax(values), pl_second(values)

    def update_eligible(self, race):
        return False

    def deltas(self, race):
        return None

    def apply(self, deltas):
        pass

    def combine_day(self, pending):
        return None

    def after_day(self, races):
        # Fixed predeclared B baseline: STRICT, K=8, race-normalized.  Every
        # race delta is computed from one D-1 state and applied once per D.
        rating_delta = defaultdict(float)
        for race in races:
            if not race.common_strict:
                continue
            entries = list(race.entries)
            pairs = len(entries) * (len(entries) - 1) // 2
            for i, left in enumerate(entries):
                for right in entries[i + 1:]:
                    expected = 1 / (1 + math.exp((self.overall_ratings[right.player_id]
                                                  - self.overall_ratings[left.player_id])
                                                 / RATING_SCALE))
                    observed = 1.0 if left.finish < right.finish else 0.0
                    change = 8.0 / pairs * (observed - expected)
                    rating_delta[left.player_id] += change
                    rating_delta[right.player_id] -= change
        for player, change in rating_delta.items():
            self.overall_ratings[player] += change
        for race in races:
            for entry in race.entries:
                value = (self._performance(entry.finish) if race.common_strict
                         and entry.finish_state == "NUMERIC_VALID" else None)
                if self.config["basis"] == "ENTRY":
                    self.history[entry.player_id].append(value)
                elif value is not None:
                    self.history[entry.player_id].append(value)
                if value is not None:
                    self.overall_sum[entry.player_id] += value
                    self.overall_count[entry.player_id] += 1


class Short50Coverage:
    """Compare prior-day availability for last-50 entry and valid-result bases."""
    def __init__(self):
        self.entry = defaultdict(lambda: deque(maxlen=50))
        self.valid = defaultdict(lambda: deque(maxlen=50))
        self.counts = defaultdict(Counter)

    def observe_before_update(self, race):
        if not race.common_strict or race.day.year not in (2023, 2024):
            return
        year = race.day.year
        for e in race.entries:
            for name, histories in (("ENTRY", self.entry), ("VALID_RESULT", self.valid)):
                if len(histories[e.player_id]) == 50:
                    self.counts[year][f"{name}_AVAILABLE"] += 1
                elif histories[e.player_id]:
                    self.counts[year][f"{name}_FALLBACK_OVERALL_LT50"] += 1
                else:
                    self.counts[year][f"{name}_FALLBACK_INITIALIZER_0"] += 1

    def update_after_day(self, races):
        for race in races:
            for e in race.entries:
                value = (e.finish if race.common_strict
                         and e.finish_state == "NUMERIC_VALID" else None)
                self.entry[e.player_id].append((race.day, value))
                if value is not None:
                    self.valid[e.player_id].append((race.day, e.finish))


def candidate_specs():
    specs = []
    for method in ("A", "C"):
        for rate in (8.0, 16.0):
            for init in ("WARMUP_2017_2022", "RESET_2023"):
                for eligibility in ("STRICT", "ROW_SAFE"):
                    config = {"initialization": init, "eligibility": eligibility,
                              "learning_rate": rate}
                    cid = f"{method}-lr{int(rate)}-{init}-{eligibility}"
                    specs.append((method, cid, config))
    for k, weights in ((8.0, ("RACE_NORMALIZED", "PER_PAIR")),
                       (16.0, ("RACE_NORMALIZED", "PER_PAIR")),
                       (120.0, ("RACE_NORMALIZED",))):
        for weight in weights:
            for init in ("WARMUP_2017_2022", "RESET_2023"):
                for eligibility in ("STRICT", "ROW_SAFE"):
                    config = {"initialization": init, "eligibility": eligibility,
                              "k_factor": k, "pair_weight": weight,
                              "link": "EXP_SOFTMAX_SCALE_400"}
                    cid = f"B-k{int(k)}-{weight}-{init}-{eligibility}"
                    specs.append(("B", cid, config))
    return specs


def build_candidates():
    supported, unsupported = [], []
    classes = {"A": CourseSoftmax, "B": PairwiseElo, "C": PlackettLuce}
    names = {"A": CourseSoftmax.method, "B": PairwiseElo.method, "C": PlackettLuce.method}
    for method, cid, config in candidate_specs():
        if method in ("A", "C") and config["eligibility"] == "ROW_SAFE":
            unsupported.append({"candidate_id": cid, "status": "UNSUPPORTED",
                                "method": names[method], "config": config,
                                "compute_seconds": None,
                                "stability_2024": "NOT_APPLICABLE",
                                "reason": "partial race has no provably safe full softmax/rank denominator"})
        else:
            supported.append(classes[method](cid, config))
    return supported, unsupported


def build_short50_candidates():
    return [Short50Model(f"SHORT50-{basis}-{fallback}",
                         {"initialization": "WARMUP_2017_2022",
                          "eligibility": "STRICT", "basis": basis,
                          "fallback": fallback})
            for basis in ("ENTRY", "VALID_RESULT")
            for fallback in ("AVAILABLE_HISTORY", "OVERALL_RATING",
                             "CAREER_FINISH_MEAN", "INITIALIZER")]


def _row_for_hash(row):
    return [row[0], row[1].isoformat(), *row[2:]]


def _make_race(rows):
    first = rows[0]
    entries = tuple(Entry(boat_no=r[4], player_id=r[5], finish_state=r[6],
                          finish=r[7], actual_course=r[8], canonical_result=r[10])
                    for r in rows)
    return Race(race_id=first[0], day=first[1], venue=first[2], race_no=first[3],
                result_state=first[9], common_strict=first[11], entries=entries)


def select_candidates(models):
    selected = {}
    for method in sorted({m.method for m in models}):
        choices = [m for m in models if m.method == method]
        selected[method] = min(
            choices,
            key=lambda m: (m.selection_2023.json().get("combined_log_loss", math.inf),
                           m.candidate_id)).candidate_id
    return selected


def run():
    started = perf_counter()
    models, unsupported = build_candidates()
    short_models = build_short50_candidates()
    conn = target_connection()
    digest = hashlib.sha256()
    digest.update((QUERY_VERSION + "\n").encode())
    rows_hashed = 0
    strict_counts = Counter()
    short50 = Short50Coverage()
    seen_players = set()
    newcomer_counts = Counter()
    selected = None
    try:
        conn.commit()
        conn.set_session(readonly=True, isolation_level="REPEATABLE READ")
        with conn.cursor() as cur:
            cur.execute("SELECT current_database(),current_setting('transaction_read_only'),pg_current_snapshot()::text")
            database, readonly, snapshot = cur.fetchone()
            if database != "boatrace_predictor" or readonly != "on":
                raise RuntimeError("expected boatrace_predictor read-only snapshot")
            cur.execute("SET LOCAL statement_timeout='0'")
        current_race_rows = []
        current_day = None
        day_races = []

        def process_day(day, races):
            nonlocal selected
            if day is None:
                return
            if day.year == 2024 and selected is None:
                selected = select_candidates(models)
            roster = {e.player_id for race in races for e in race.entries}
            statuses = {p: (ESTABLISHED if p in seen_players else NEWCOMER_UNCERTAIN)
                        for p in roster}
            newcomer_counts.update(statuses.values())
            for model in models + short_models:
                model_started = perf_counter()
                model.process_day(day, races, statuses,
                                  collect_validation=True)
                model.compute_seconds += perf_counter() - model_started
            for race in races:
                short50.observe_before_update(race)
            short50.update_after_day(races)
            seen_players.update(roster)

        with conn.cursor(name="rating_method_extract") as cur:
            cur.itersize = 20000
            cur.execute(EXTRACT_SQL)
            for row in cur:
                if row[1] >= date(2025, 1, 1):
                    raise RuntimeError("BLOCKING: extraction crossed 2024-12-31")
                digest.update(json.dumps(_row_for_hash(row), ensure_ascii=False,
                                         separators=(",", ":"), default=str).encode("utf-8") + b"\n")
                rows_hashed += 1
                if current_race_rows and row[0] != current_race_rows[0][0]:
                    race = _make_race(current_race_rows)
                    strict_counts[f"{race.day.year}_all_races"] += 1
                    strict_counts[f"{race.day.year}_common_strict_races"] += race.common_strict
                    if current_day is not None and race.day != current_day:
                        process_day(current_day, day_races)
                        day_races = []
                    current_day = race.day
                    day_races.append(race)
                    current_race_rows = []
                current_race_rows.append(row)
            if current_race_rows:
                race = _make_race(current_race_rows)
                strict_counts[f"{race.day.year}_all_races"] += 1
                strict_counts[f"{race.day.year}_common_strict_races"] += race.common_strict
                if current_day is not None and race.day != current_day:
                    process_day(current_day, day_races)
                    day_races = []
                current_day = race.day
                day_races.append(race)
            process_day(current_day, day_races)
        if selected is None:
            raise RuntimeError("no 2024 boundary found")
        candidates = [m.output(m.candidate_id in set(selected.values())) for m in models]
        candidates.extend(unsupported)
        candidates.sort(key=lambda x: x["candidate_id"])
        selected_overall = min(
            (m for m in models if m.candidate_id in set(selected.values())),
            key=lambda m: (m.selection_2023.json()["combined_log_loss"], m.candidate_id)).candidate_id
        best_2024_by_method = {}
        for method in sorted({m.method for m in models}):
            best_2024_by_method[method] = min(
                (m for m in models if m.method == method),
                key=lambda m: (m.metrics[2024].json().get("combined_log_loss", math.inf),
                               m.candidate_id)).candidate_id
        best_2024 = min(
            models,
            key=lambda m: (m.metrics[2024].json().get("combined_log_loss", math.inf),
                           m.candidate_id)).candidate_id
        return {
            "comparison_version": QUERY_VERSION,
            "database": database,
            "transaction": {"read_only": readonly, "isolation": "REPEATABLE READ",
                            "snapshot": snapshot},
            "extraction": {"query_version": QUERY_VERSION,
                           "date_bounds": ["2017-01-01", "2024-12-31"],
                           "ordered_rows": rows_hashed,
                           "sha256": digest.hexdigest(),
                           "hash_preamble": QUERY_VERSION,
                           "row_fields": ["race_id", "race_date", "venue_code", "race_no",
                                          "boat_no", "player_id", "finish_state", "finish_position",
                                          "actual_course", "result_state", "canonical_result",
                                          "common_strict"]},
            "scoring": {"common_rule": "COMMON_STRICT only for every method and both periods",
                        "common_strict_counts": dict(sorted(strict_counts.items())),
                        "selection": "lowest Q2-Q4 2023 prequential combined first/exact-second log loss after Q1 development; candidate-id tie break",
                        "validation": "2024 OOT metrics for every supported candidate; quarter consistency only, no paired uncertainty"},
            "selected_by_method": selected,
            "selected_overall_from_2023": selected_overall,
            "best_2024_by_method": best_2024_by_method,
            "best_supported_candidate_2024": best_2024,
            "candidates": candidates,
            "short50": {"rule": "race_date < D; ENTRY counts every prior appearance; VALID_RESULT counts NUMERIC_VALID only; fewer than 50 uses AVAILABLE_HISTORY, fixed B OVERALL_RATING, CAREER_FINISH_MEAN, or INITIALIZER by candidate",
                        "coverage": {str(y): dict(sorted(short50.counts[y].items()))
                                     for y in (2023, 2024)},
                        "performance_candidates": [m.output(False) for m in short_models],
                        "estimator": "mean centered finish performance in the preceding 50 eligible observations, mapped to rating as 1000 + 100*mean; PL first/second probabilities; untuned comparator",
                        "overall_rating_fallback": "fixed predeclared B baseline: WARMUP_2017_2022, STRICT, K=8, RACE_NORMALIZED; D-1 state",
                        "freeze_status": "INCOMPLETE_COMPARATOR_ONLY",
                        "limitation": "OVERALL_RATING uses a fixed predeclared B baseline rather than a method chosen from 2024; SHORT_50 remains exploratory and is not frozen by this script"},
            "newcomer_initialization": {
                "confirmed_rule": "per-series pre-insertion existing valid-player mean multiplied by 0.8; one frozen mean for all same-day confirmed newcomers",
                "uncertain_rule": f"no discount; conservative base {BASE_RATING}",
                "runtime_confirmed_newcomers": 0,
                "limitation": "historical as-of-D cohort publication and complete prior career coverage are not confirmed; all first-seen players remain NEWCOMER_UNCERTAIN",
                "day_roster_status_counts": dict(sorted(newcomer_counts.items()))},
            "compute_seconds": perf_counter() - started,
            "limitations": [
                "A uses softmax of Dirichlet(1)-smoothed venue-by-boat course-frequency-weighted rating scores; this is not exact marginalization over uncertain courses.",
                "All comparison metrics are conditional on complete six-boat numeric-finish COMMON_STRICT races.",
                "Quarter consistency is reported without paired uncertainty intervals."
            ],
        }
    finally:
        conn.rollback()
        conn.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    result = run()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2,
                                      default=str) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(args.report),
                      "selected_by_method": result["selected_by_method"],
                      "ordered_rows": result["extraction"]["ordered_rows"],
                      "sha256": result["extraction"]["sha256"],
                      "compute_seconds": result["compute_seconds"]},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
