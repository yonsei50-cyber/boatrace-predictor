"""Adversarial tests for the chronological rating comparison."""
import unittest
from datetime import date

from scripts.compare_rating_methods import (
    BASE_RATING, CONFIRMED_NEWCOMER, NEWCOMER_UNCERTAIN,
    CourseSoftmax, Entry, EXTRACT_SQL, MetricSet, PairwiseElo, PlackettLuce, Race,
    Short50Coverage, Short50Model, build_candidates, build_short50_candidates,
    initialize_rating_map, pl_second,
)


def race(day, race_id=1, finishes=(1, 2, 3, 4, 5, 6), courses=(1, 2, 3, 4, 5, 6),
         strict=True, players=None):
    players = players or tuple(range(101, 107))
    entries = tuple(Entry(i + 1, players[i], "NUMERIC_VALID" if finishes[i] else "UNRESOLVED_SPECIAL",
                          finishes[i], courses[i], True) for i in range(6))
    return Race(race_id, day, 1, race_id, "RESULT_RECORDS_PRESENT", strict, entries)


class RatingMethodsTest(unittest.TestCase):
    def test_query_has_non_configurable_pre_2025_cutoff(self):
        self.assertIn("r.race_date < DATE '2025-01-01'", EXTRACT_SQL)
        self.assertNotIn("2025-12-31", EXTRACT_SQL)

    def test_same_day_confirmed_newcomers_share_frozen_mean_and_uncertain_is_not_discounted(self):
        ratings = {1: 900.0, 2: 1100.0}
        assigned = initialize_rating_map(
            ratings, [3, 4, 5], {3: CONFIRMED_NEWCOMER, 4: CONFIRMED_NEWCOMER,
                                 5: NEWCOMER_UNCERTAIN})
        self.assertEqual(assigned[3], 800.0)
        self.assertEqual(assigned[4], 800.0)
        self.assertEqual(assigned[5], BASE_RATING)

    def test_pl_first_and_exact_second_are_coherent(self):
        second = pl_second([900, 950, 1000, 1050, 1100, 1150])
        self.assertAlmostEqual(sum(second), 1.0, places=12)
        self.assertTrue(all(0 <= p <= 1 for p in second))

    def test_ranking_diagnostics_reward_correct_order(self):
        entries = race(date(2023, 1, 2)).entries
        good, bad = MetricSet(), MetricSet()
        good_first = [0.40, 0.25, 0.15, 0.10, 0.06, 0.04]
        bad_first = list(reversed(good_first))
        second = [1 / 6] * 6
        good.add(good_first, second, entries)
        bad.add(bad_first, second, entries)
        good_ranking = good.json()["ranking"]
        bad_ranking = bad.json()["ranking"]
        self.assertLess(good_ranking["pl_full_ranking_log_loss_per_race"],
                        bad_ranking["pl_full_ranking_log_loss_per_race"])
        self.assertLess(good_ranking["pairwise_log_loss"],
                        bad_ranking["pairwise_log_loss"])
        self.assertGreater(good_ranking["spearman_mean"], bad_ranking["spearman_mean"])

    def test_all_same_day_predictions_use_one_pre_day_state(self):
        config = {"initialization": "WARMUP_2017_2022", "eligibility": "STRICT",
                  "k_factor": 16.0, "pair_weight": "PER_PAIR"}
        model = PairwiseElo("test", config)
        day = date(2023, 1, 2)
        r1 = race(day, 1)
        r2 = race(day, 2)
        model.prepare_day({e.player_id for e in r1.entries}, {})
        before1 = model.predict(r1)[0]
        before2 = model.predict(r2)[0]
        self.assertEqual(before1, before2)
        pending = [model.deltas(r1), model.deltas(r2)]
        self.assertEqual(model.predict(r2)[0], before2)
        for delta in pending:
            model.apply(delta)
        self.assertNotEqual(model.predict(race(date(2023, 1, 3), 3))[0], before2)

    def test_process_day_accumulates_two_races_and_applies_once(self):
        class RecordingElo(PairwiseElo):
            def __init__(self, candidate_id, config):
                super().__init__(candidate_id, config)
                self.states_at_delta = []
                self.apply_calls = 0
            def deltas(self, item):
                self.states_at_delta.append(dict(self.ratings))
                return super().deltas(item)
            def apply(self, deltas):
                self.apply_calls += 1
                return super().apply(deltas)
        config = {"initialization": "WARMUP_2017_2022", "eligibility": "STRICT",
                  "k_factor": 16.0, "pair_weight": "PER_PAIR"}
        model = RecordingElo("test", config)
        day = date(2024, 1, 2)
        model.process_day(day, [race(day, 1), race(day, 2)], {}, True)
        self.assertEqual(model.states_at_delta[0], model.states_at_delta[1])
        self.assertEqual(model.apply_calls, 1)

    def test_course_prediction_does_not_read_current_actual_course(self):
        config = {"initialization": "WARMUP_2017_2022", "eligibility": "STRICT",
                  "learning_rate": 8.0}
        model = CourseSoftmax("test", config)
        players = tuple(range(101, 107))
        model.prepare_day(players, {})
        day = date(2023, 2, 1)
        normal = race(day, 1, players=players)
        reversed_courses = race(day, 2, courses=(6, 5, 4, 3, 2, 1), players=players)
        self.assertEqual(model.predict(normal), model.predict(reversed_courses))
        self.assertEqual(model.course_probabilities(1, 1), [1 / 6] * 6)
        model.after_day([normal, reversed_courses])
        self.assertNotEqual(model.course_probabilities(1, 1), [1 / 6] * 6)

    def test_process_day_course_results_cannot_change_same_day_predictions(self):
        class RecordingCourse(CourseSoftmax):
            def __init__(self, candidate_id, config):
                super().__init__(candidate_id, config)
                self.predictions = []
            def predict(self, item):
                value = super().predict(item)
                self.predictions.append(value)
                return value
        config = {"initialization": "WARMUP_2017_2022", "eligibility": "STRICT",
                  "learning_rate": 8.0}
        day = date(2024, 2, 1)
        players = tuple(range(101, 107))
        first = race(day, 1, players=players)
        normal_second = race(day, 2, players=players)
        changed_second = race(day, 2, courses=(6, 5, 4, 3, 2, 1), players=players)
        left, right = RecordingCourse("left", config), RecordingCourse("right", config)
        for model in (left, right):
            for course in range(6):
                for i, player in enumerate(players):
                    model.first[course][player] = BASE_RATING + 10 * course + i
                    model.second[course][player] = BASE_RATING - 10 * course + i
            model.course_counts[(1, 1)] = [8, 1, 1, 1, 1, 1]
        left.process_day(day, [first, normal_second], {}, True)
        right.process_day(day, [first, changed_second], {}, True)
        self.assertEqual(left.predictions, right.predictions)
        future = race(date(2024, 2, 2), 3, players=players)
        self.assertNotEqual(left.predict(future), right.predict(future))

    def test_row_safe_pair_update_uses_only_proven_numeric_pairs(self):
        config = {"initialization": "WARMUP_2017_2022", "eligibility": "ROW_SAFE",
                  "k_factor": 8.0, "pair_weight": "RACE_NORMALIZED"}
        model = PairwiseElo("test", config)
        partial = race(date(2023, 1, 2), strict=False,
                       finishes=(1, 2, 3, None, None, None))
        model.prepare_day({e.player_id for e in partial.entries}, {})
        self.assertTrue(model.update_eligible(partial))
        delta = model.deltas(partial)
        self.assertEqual(set(delta), {101, 102, 103})
        self.assertAlmostEqual(sum(delta.values()), 0.0, places=12)
        unsafe = Race(partial.race_id, partial.day, partial.venue, partial.race_no,
                      "SOURCE_INCOMPLETE", False, partial.entries)
        self.assertFalse(model.update_eligible(unsafe))
        only_two = Race(9, partial.day, partial.venue, partial.race_no,
                        "RESULT_RECORDS_PRESENT", False, partial.entries[:2])
        self.assertFalse(model.update_eligible(only_two))

    def test_partial_softmax_and_pl_candidates_are_explicitly_unsupported(self):
        _, unsupported = build_candidates()
        self.assertTrue(unsupported)
        self.assertEqual({row["method"] for row in unsupported},
                         {CourseSoftmax.method, PlackettLuce.method})
        self.assertTrue(all(row["config"]["eligibility"] == "ROW_SAFE"
                            for row in unsupported))

    def test_short50_is_prior_day_and_basis_specific(self):
        tracker = Short50Coverage()
        player = 101
        for i in range(50):
            tracker.entry[player].append((date(2022, 1, 1), None))
        for i in range(49):
            tracker.valid[player].append((date(2022, 1, 1), 1))
        r = race(date(2023, 1, 2))
        tracker.observe_before_update(r)
        self.assertEqual(tracker.counts[2023]["ENTRY_AVAILABLE"], 1)
        self.assertEqual(tracker.counts[2023]["VALID_RESULT_FALLBACK_OVERALL_LT50"], 1)
        self.assertEqual(len(tracker.valid[player]), 49)
        tracker.update_after_day([r])
        self.assertEqual(len(tracker.valid[player]), 50)

    def test_short50_entry_counts_incomplete_appearance_but_valid_does_not(self):
        tracker = Short50Coverage()
        item = race(date(2023, 1, 2))
        incomplete = Race(item.race_id, item.day, item.venue, item.race_no,
                          "SOURCE_INCOMPLETE", False, item.entries)
        tracker.update_after_day([incomplete])
        self.assertEqual(len(tracker.entry[101]), 1)
        self.assertEqual(len(tracker.valid[101]), 0)
        self.assertIsNone(tracker.entry[101][0][1])

    def test_short50_special_race_adds_no_numeric_short_score(self):
        item = race(date(2023, 1, 2), strict=False,
                    finishes=(1, 2, 3, 4, 5, None))
        for basis in ("ENTRY", "VALID_RESULT"):
            model = Short50Model("test", {"initialization": "WARMUP_2017_2022",
                                          "eligibility": "STRICT", "basis": basis,
                                          "fallback": "INITIALIZER"})
            model.after_day([item])
            if basis == "ENTRY":
                self.assertTrue(all(list(model.history[e.player_id]) == [None]
                                    for e in item.entries))
            else:
                self.assertTrue(all(not model.history[e.player_id]
                                    for e in item.entries))
            self.assertFalse(model.overall_count)

    def test_short50_confirmed_newcomers_share_preinsertion_mean(self):
        model = Short50Model("test", {"initialization": "WARMUP_2017_2022",
                                      "eligibility": "STRICT", "basis": "VALID_RESULT",
                                      "fallback": "AVAILABLE_HISTORY"})
        model.prepare_day({101, 102}, {})
        model.history[101].append(1.0)
        model.history[102].append(-1.0)
        model.prepare_day({103, 104, 105},
                          {103: CONFIRMED_NEWCOMER,
                           104: CONFIRMED_NEWCOMER,
                           105: NEWCOMER_UNCERTAIN})
        self.assertEqual(model.short_initials[103], 800.0)
        self.assertEqual(model.short_initials[104], 800.0)
        self.assertNotIn(105, model.short_initials)
        self.assertEqual(BASE_RATING + 100 * model._score(103, 2023), 800.0)
        self.assertEqual(BASE_RATING + 100 * model._score(105, 2023), BASE_RATING)
        model.history[103].append(0.2)
        self.assertEqual(BASE_RATING + 100 * model._score(103, 2023), 1020.0)

    def test_short50_performance_grid_is_explicitly_comparator_only(self):
        models = build_short50_candidates()
        self.assertEqual({(m.config["basis"], m.config["fallback"]) for m in models},
                         {("ENTRY", "AVAILABLE_HISTORY"),
                          ("ENTRY", "OVERALL_RATING"),
                          ("ENTRY", "CAREER_FINISH_MEAN"), ("ENTRY", "INITIALIZER"),
                          ("VALID_RESULT", "AVAILABLE_HISTORY"),
                          ("VALID_RESULT", "OVERALL_RATING"),
                          ("VALID_RESULT", "CAREER_FINISH_MEAN"),
                          ("VALID_RESULT", "INITIALIZER")})

    def test_matched_scale_race_normalized_elo_sensitivity_exists(self):
        models, _ = build_candidates()
        matched = [m for m in models if m.method == PairwiseElo.method
                   and m.config["k_factor"] == 120.0]
        self.assertEqual(len(matched), 4)
        self.assertTrue(all(m.config["pair_weight"] == "RACE_NORMALIZED"
                            for m in matched))

    def test_reset_discards_warmup_state(self):
        config = {"initialization": "RESET_2023", "eligibility": "STRICT",
                  "learning_rate": 8.0}
        model = PlackettLuce("test", config)
        model.ratings = {101: 1234.0}
        model.maybe_start(date(2022, 12, 31))
        self.assertFalse(model.started)
        model.maybe_start(date(2023, 1, 1))
        self.assertTrue(model.started)
        self.assertEqual(model.ratings, {})


if __name__ == "__main__":
    unittest.main()
