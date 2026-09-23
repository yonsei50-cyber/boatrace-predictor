"""Read-only K3 source correction of frozen Rating v1, replayed from 2017."""

from collections import Counter, defaultdict
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path

from scripts.compare_rating_methods import (
    CourseSoftmax, ESTABLISHED, MetricSet, NEWCOMER_UNCERTAIN, PairwiseElo,
    RATING_SCALE, Short50Model, EXTRACT_SQL as FROZEN_EXTRACT_SQL,
    _make_race, _row_for_hash,
)
from scripts.db import target_connection
from scripts.evaluate_rating_v1_holdout_2025 import (
    BinaryMetric, EXTRACT_SQL as HOLDOUT_EXTRACT_SQL,
    model_state, with_calibration_error,
)


ROOT = Path(__file__).resolve().parents[1]
FREEZE = ROOT / 'artifacts/rating_method_freeze_v1.json'
MODEL_CODE = ROOT / 'scripts/compare_rating_methods.py'
LEGACY_DEV = ROOT / 'artifacts/rating_method_comparison_2023_2024_v2.json'
LEGACY_2025 = ROOT / 'artifacts/rating_v1_holdout_2025.json'
DEV_OUT = ROOT / 'artifacts/rating_v1_k3_source_corrected_2023_2024.json'
YEAR_2025_OUT = ROOT / 'artifacts/rating_v1_k3_source_corrected_2025.json'
DIFF_OUT = ROOT / 'artifacts/rating_v1_k3_source_corrected_comparison.json'
REPORT_OUT = ROOT / 'docs/rating_v1_k3_source_corrected_report.md'
EXPECTED_FREEZE_SHA256 = 'c7fbd2af725f2c9d62491923a5a411350a33076b8b1b305798c5ed07d23136fb'
SOURCE_POLICY_CHECKPOINT = 'fd49bffe83b2f23443ec5f525786c0dd309abe95'
EXTRACT_SQL = FROZEN_EXTRACT_SQL.replace("DATE '2025-01-01'", "DATE '2026-01-01'")
EXTRACT_VERSION = 'rating-v1-k3-source-corrected-2017-2025-v1'
YEARS = (2023, 2024, 2025)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked_freeze():
    if sha(FREEZE) != EXPECTED_FREEZE_SHA256:
        raise RuntimeError('Rating v1 freeze hash changed')
    freeze = json.loads(FREEZE.read_text(encoding='utf-8'))
    ids = freeze['rating_series']
    parameters = freeze['parameters']
    if (sha(MODEL_CODE) != freeze['versions_and_hashes']['current_comparison_code_sha256']
            or freeze['status'] != 'RATING_METHOD_FROZEN'
            or freeze['series_count'] != 14
            or freeze['eligibility']['selected'] != 'STRICT for A, B, and SHORT_50 numeric updates'
            or freeze['initialization']['historical_warmup'] !=
               'Use eligible 2017-01-01 through 2022-12-31 results only to build the 2023-01-01 D-1 state'
            or parameters['rating_scale'] != RATING_SCALE
            or parameters['A_learning_rate'] != 16.0
            or parameters['B_k_factor'] != 120.0
            or parameters['B_pair_weight'] != 'RACE_NORMALIZED'
            or parameters['short_window_size'] != 50
            or parameters['decay'] != 'none beyond the SHORT_50 window'
            or ids['FIRST_COURSE_1_TO_6']['candidate_id'] !=
               ids['EXACT_SECOND_COURSE_1_TO_6']['candidate_id']
            or ids['FIRST_COURSE_1_TO_6']['candidate_id'] !=
               'A-lr16-WARMUP_2017_2022-STRICT'
            or ids['OVERALL']['candidate_id'] !=
               'B-k120-RACE_NORMALIZED-WARMUP_2017_2022-STRICT'
            or ids['SHORT_50']['candidate_id'] != 'SHORT50-VALID_RESULT-AVAILABLE_HISTORY'
            or EXTRACT_SQL != HOLDOUT_EXTRACT_SQL):
        raise RuntimeError('Rating v1 frozen method or extract identity mismatch')
    return freeze


def frozen_models(freeze):
    ids = freeze['rating_series']
    warmup = 'WARMUP_2017_2022'
    return (
        CourseSoftmax(ids['FIRST_COURSE_1_TO_6']['candidate_id'],
                      {'initialization': warmup, 'eligibility': 'STRICT',
                       'learning_rate': freeze['parameters']['A_learning_rate']}),
        PairwiseElo(ids['OVERALL']['candidate_id'],
                    {'initialization': warmup, 'eligibility': 'STRICT',
                     'k_factor': freeze['parameters']['B_k_factor'],
                     'pair_weight': 'RACE_NORMALIZED',
                     'link': 'EXP_SOFTMAX_SCALE_400'}),
        Short50Model(ids['SHORT_50']['candidate_id'],
                     {'initialization': warmup, 'eligibility': 'STRICT',
                      'basis': 'VALID_RESULT', 'fallback': 'AVAILABLE_HISTORY'}),
    )


def state_fingerprint(models, seen_players):
    course, overall, short = models
    ordered = lambda ratings: [(p, value.hex()) for p, value in sorted(ratings.items())]
    state = {
        'course_first': [ordered(series) for series in course.first],
        'course_second': [ordered(series) for series in course.second],
        'course_counts': [(venue, boat, value) for (venue, boat), value
                          in sorted(course.course_counts.items())],
        'overall': ordered(overall.ratings),
        'short_history': [(p, [value.hex() if value is not None else None
                               for value in values])
                          for p, values in sorted(short.history.items())],
        'short_overall_ratings': ordered(short.overall_ratings),
        'short_overall_sum': ordered(short.overall_sum),
        'short_overall_count': sorted(short.overall_count.items()),
        'short_initials': ordered(short.short_initials),
        'short_known_players': sorted(short.known_players),
        'seen_players': sorted(seen_players),
    }
    payload = json.dumps(state, ensure_ascii=False, separators=(',', ':')).encode()
    return {'sha256': hashlib.sha256(payload).hexdigest(),
            'course_players': len(course.first[0]),
            'overall_players': len(overall.ratings),
            'short_known_players': len(short.known_players),
            'seen_players': len(seen_players)}


def source_identity(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT current_database(),current_setting('transaction_read_only')")
        if cur.fetchone() != ('boatrace_predictor', 'on'):
            raise RuntimeError('expected read-only Canonical target')
        cur.execute('''SELECT version_id,authoritative_source,date_start,date_end,
                      source_manifest_hash,normalization_version,result_races,result_boats
                      FROM core.result_dataset_version ORDER BY created_at DESC LIMIT 1''')
        row = cur.fetchone()
        if not row or row[1] != 'brd_k3' or row[2] != date(2017, 1, 1) \
                or row[3] < date(2025, 12, 31) or row[5] != 'k3-only-result-v1':
            raise RuntimeError('K3-only Canonical result version is absent or incomplete')
        names = [description[0] for description in cur.description]
        version = dict(zip(names, row))
        cur.execute('''SELECT count(*),count(*) FILTER
                (WHERE b.source_table IS DISTINCT FROM 'brd_k3')
                FROM core.race_result z JOIN core.race r USING(race_id)
                JOIN raw.source_record s ON s.source_record_id=z.source_record_id
                JOIN raw.source_batch b USING(source_batch_id)
                WHERE r.race_date < DATE '2026-01-01' ''')
        result_boats, foreign_source_boats = cur.fetchone()
        if foreign_source_boats:
            raise RuntimeError('non-K3 Canonical result lineage in replay range')
        cur.execute('''SELECT count(DISTINCT r.race_id),count(e.boat_no),count(z.boat_no)
                FROM core.race r JOIN core.race_entry e USING(race_id)
                LEFT JOIN core.race_result z USING(race_id,boat_no)
                WHERE r.race_date=DATE '2025-08-12'
                  AND r.venue_code IN (1,7,15,19,20)''')
        absent_races, absent_entries, absent_results = cur.fetchone()
        if (absent_races, absent_entries, absent_results) != (60, 360, 0):
            raise RuntimeError('known K3-absent 2025 races changed')
    return {'result_dataset_version': version, 'result_boats_before_2026': result_boats,
            'foreign_source_boats': foreign_source_boats,
            'known_2025_k3_absent': {'races': absent_races, 'entries': absent_entries,
                                     'individual_results': absent_results}}


def evaluate():
    freeze = checked_freeze()
    models = frozen_models(freeze)
    conn = target_connection()
    conn.commit()
    conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
    try:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout='0'")
        source = source_identity(conn)
        metrics = {year: {name: MetricSet() for name in ('course', 'overall', 'short50')}
                   for year in YEARS}
        strata = {year: {target: {str(c): BinaryMetric() for c in range(1, 7)}
                         for target in ('first', 'exact_second')} for year in YEARS}
        annual_counts = defaultdict(Counter)
        newcomer_counts = defaultdict(Counter)
        seen_players = set()
        checkpoints = {}
        digest = hashlib.sha256((EXTRACT_VERSION + '\n').encode())
        extract_rows = 0
        extract_rows_by_year = Counter()
        current_race_rows, day_races, current_day = [], [], None
        prior_update_day = None

        def process_day(day, races):
            nonlocal prior_update_day
            if day is None:
                return
            if prior_update_day is not None and day <= prior_update_day:
                raise RuntimeError('D-1 ordering violated')
            if day.year in YEARS and str(day.year) not in checkpoints:
                checkpoints[str(day.year)] = {'before_first_race_date': day.isoformat(),
                                               **state_fingerprint(models, seen_players)}
                print(json.dumps({'stage': 'year_start', 'year': day.year,
                                  'prior_strict_races': annual_counts[day.year - 1]['strict_races']}),
                      flush=True)
            roster = {entry.player_id for race in races for entry in race.entries}
            statuses = {player: ESTABLISHED if player in seen_players else NEWCOMER_UNCERTAIN
                        for player in roster}
            for race in races:
                count = annual_counts[day.year]
                count['total_races'] += 1
                count['total_boats'] += len(race.entries)
                if race.common_strict:
                    if (len(race.entries) != 6
                            or sorted(entry.finish for entry in race.entries) !=
                               [1, 2, 3, 4, 5, 6]
                            or sorted(entry.actual_course for entry in race.entries) !=
                               [1, 2, 3, 4, 5, 6]):
                        raise RuntimeError('STRICT race violates frozen six-boat/course rule')
                    count['strict_races'] += 1
                    count['strict_boats'] += 6
                else:
                    count['excluded_races'] += 1
                    count['excluded_boats'] += len(race.entries)
                    reason = ('result_records_absent' if race.result_state !=
                              'RESULT_RECORDS_PRESENT' else 'non_numeric_or_incomplete')
                    count[f'excluded_{reason}'] += 1
            if day.year < 2023:
                for model in models:
                    model.process_day(day, races, statuses, collect_validation=False)
            else:
                for model in models:
                    model.prepare_day(roster, statuses)
                before = model_state(models)
                newcomer_counts[day.year].update(statuses.values())
                for race in races:
                    if not race.common_strict:
                        continue
                    predictions = [model.predict(race) for model in models]
                    for name, (first, second) in zip(('course', 'overall', 'short50'),
                                                     predictions):
                        if (abs(sum(first) - 1) > 1e-10 or abs(sum(second) - 1) > 1e-10
                                or any(not 0 <= p <= 1 for p in first + second)):
                            raise RuntimeError('invalid probability distribution')
                        metrics[day.year][name].add(first, second, race.entries)
                    for i, entry in enumerate(race.entries):
                        c = str(entry.actual_course)
                        strata[day.year]['first'][c].add(predictions[0][0][i],
                                                         entry.finish == 1)
                        strata[day.year]['exact_second'][c].add(predictions[0][1][i],
                                                                entry.finish == 2)
                pending_a = [models[0].deltas(race) for race in races
                             if models[0].update_eligible(race)]
                pending_b = [models[1].deltas(race) for race in races
                             if models[1].update_eligible(race)]
                if model_state(models) != before:
                    raise RuntimeError('same-day result altered prediction state')
                if pending_a:
                    models[0].apply(models[0].combine_day(pending_a))
                if pending_b:
                    models[1].apply(models[1].combine_day(pending_b))
                for model in models:
                    model.after_day(races)
                annual_counts[day.year]['course_update_races'] += len(pending_a)
                annual_counts[day.year]['overall_update_races'] += len(pending_b)
            seen_players.update(roster)
            prior_update_day = day

        with conn.cursor(name='rating_v1_k3_replay') as cur:
            cur.itersize = 20000
            cur.execute(EXTRACT_SQL)
            for row in cur:
                digest.update(json.dumps(_row_for_hash(row), ensure_ascii=False,
                                         separators=(',', ':'), default=str).encode() + b'\n')
                extract_rows += 1
                extract_rows_by_year[row[1].year] += 1
                if current_race_rows and row[0] != current_race_rows[0][0]:
                    race = _make_race(current_race_rows)
                    if current_day is not None and race.day != current_day:
                        process_day(current_day, day_races)
                        day_races = []
                    current_day = race.day
                    day_races.append(race)
                    current_race_rows = []
                current_race_rows.append(row)
            if current_race_rows:
                race = _make_race(current_race_rows)
                if current_day is not None and race.day != current_day:
                    process_day(current_day, day_races)
                    day_races = []
                current_day = race.day
                day_races.append(race)
            process_day(current_day, day_races)
        checkpoints['after_2025'] = state_fingerprint(models, seen_players)
        if set(YEARS) - set(annual_counts):
            raise RuntimeError('missing evaluation year')
        for year in YEARS:
            c = annual_counts[year]
            if (c['strict_races'] != metrics[year]['course'].races
                    or c['strict_races'] != c['course_update_races']
                    or c['strict_races'] != c['overall_update_races']
                    or c['strict_boats'] != 6 * c['strict_races']
                    or c['total_races'] != c['strict_races'] + c['excluded_races']):
                raise RuntimeError(f'{year} STRICT count reconciliation failed')
        annual_metrics = {str(year): {name: with_calibration_error(metric)
                                      for name, metric in metrics[year].items()}
                          for year in YEARS}
        payload = {
            'source_policy_checkpoint': SOURCE_POLICY_CHECKPOINT,
            'freeze_sha256': sha(FREEZE), 'frozen_code_sha256': sha(MODEL_CODE),
            'source': source, 'extract_version': EXTRACT_VERSION,
            'extract_rows': extract_rows,
            'extract_rows_by_year': dict(sorted(extract_rows_by_year.items())),
            'extract_sha256': digest.hexdigest(),
            'replay_start': '2017-01-01', 'warmup_end': '2022-12-31',
            'state_checkpoints': checkpoints,
            'counts': {str(y): dict(sorted(c.items())) for y, c in sorted(annual_counts.items())},
            'metrics': annual_metrics,
            'course_strata': {str(y): {target: {c: metric.json() for c, metric in values.items()}
                                       for target, values in strata[y].items()} for y in YEARS},
            'newcomer_roster_status': {str(y): dict(c) for y, c in newcomer_counts.items()},
        }
        stable = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                            separators=(',', ':'), default=str).encode()
        payload['deterministic_sha256'] = hashlib.sha256(stable).hexdigest()
        payload['executed_at_utc'] = datetime.now(timezone.utc).isoformat()
        return payload
    finally:
        conn.rollback()
        conn.close()


def old_new_comparison(result):
    """Historical aggregate values are read only after the K3 replay is finished."""
    old_dev = json.loads(LEGACY_DEV.read_text(encoding='utf-8'))
    old_2025 = json.loads(LEGACY_2025.read_text(encoding='utf-8'))
    freeze = json.loads(FREEZE.read_text(encoding='utf-8'))
    candidate = {c['candidate_id']: c for c in old_dev['candidates']}
    short = {c['candidate_id']: c for c in old_dev['short50']['performance_candidates']}
    ids = freeze['rating_series']
    old_models = {
        'course': candidate[ids['FIRST_COURSE_1_TO_6']['candidate_id']],
        'overall': candidate[ids['OVERALL']['candidate_id']],
        'short50': short[ids['SHORT_50']['candidate_id']],
    }

    def flat(count, values):
        course = values['course']
        def ece(target):
            if 'calibration_ece_10bin' in course[target]:
                return course[target]['calibration_ece_10bin']
            bins = course[target]['calibration']
            n = sum(item['observations'] for item in bins)
            return sum(item['observations'] *
                       abs(item['mean_probability'] - item['event_rate'])
                       for item in bins if item['observations']) / n
        return {
            'strict_races': count, 'strict_boats': count * 6,
            'course_mean_log_loss': course['combined_log_loss'],
            'p1_log_loss': course['first']['log_loss'],
            'p1_brier': course['first']['brier'],
            'p1_ece': ece('first'),
            'p1_top1': course['first']['top1_hit_rate'],
            'exact_p2_log_loss': course['exact_second']['log_loss'],
            'exact_p2_brier': course['exact_second']['brier'],
            'exact_p2_ece': ece('exact_second'),
            'overall_log_loss': values['overall']['combined_log_loss'],
            'short50_log_loss': values['short50']['combined_log_loss'],
        }

    years = {}
    for year in YEARS:
        if year == 2025:
            old = flat(old_2025['eligibility']['eligible_races'], old_2025['metrics'])
        else:
            key = 'tuning_2023' if year == 2023 else 'validation_2024'
            old = flat(old_dev['scoring']['common_strict_counts'][
                f'{year}_common_strict_races'],
                {name: model[key] for name, model in old_models.items()})
        new = flat(result['counts'][str(year)]['strict_races'],
                   result['metrics'][str(year)])
        years[str(year)] = {name: {'old': old[name], 'new': new[name],
                                  'signed_difference': new[name] - old[name],
                                  'absolute_difference': abs(new[name] - old[name]),
                                  'relative_difference': ((new[name] - old[name]) / old[name]
                                                          if old[name] else None),
                                  'absolute_relative_difference':
                                      (abs(new[name] - old[name]) / abs(old[name])
                                       if old[name] else None)}
                            for name in old}
    warmup = {str(year): {
        'old_strict_races': old_dev['scoring']['common_strict_counts'][
            f'{year}_common_strict_races'],
        'new_strict_races': result['counts'][str(year)]['strict_races'],
        'difference': result['counts'][str(year)]['strict_races'] -
                      old_dev['scoring']['common_strict_counts'][f'{year}_common_strict_races']}
        for year in range(2017, 2023)}
    old_exclusion = old_2025['eligibility']
    new_exclusion = result['counts']['2025']
    eligibility_2025 = {
        'old_result_records_absent': old_exclusion['exclusion_RESULT_RECORDS_NOT_PRESENT'],
        'new_result_records_absent': new_exclusion['excluded_result_records_absent'],
        'old_result_present_but_nonstrict': old_exclusion['exclusion_NONSTRICT_RESULT_OR_INCOMPLETE'],
        'new_result_present_but_nonstrict': new_exclusion['excluded_non_numeric_or_incomplete'],
    }
    return {'position': 'historical aggregate comparison only; no selection or retuning',
            'old_development_artifact_sha256': sha(LEGACY_DEV),
            'old_2025_artifact_sha256': sha(LEGACY_2025),
            'new_replay_deterministic_sha256': result['deterministic_sha256'],
            'old_state_checkpoint_comparison': 'UNAVAILABLE: historical aggregate artifacts do not contain full per-player rating state; retired-source inputs are not replayed',
            'warmup_strict_counts': warmup, 'years': years,
            'eligibility_2025': eligibility_2025,
            'source_change_context': {
                'document': 'docs/k3_only_source_policy_impact_audit.md',
                'known_2022_new_k3_result_boats': 54,
                'known_2023_actual_course_corrected_boats': 2,
                'known_2025_new_k3_result_boats': 1500,
                'known_2025_old_only_boats_removed': 360,
                'known_2025_old_only_races_removed': 60,
                'status': 'Migration evidence gives source-change scope, not per-change metric attribution',
            },
            'attribution_limit': 'Aggregate differences are observed; separate causal effects of warm-up, course correction, and other source changes are not identified by this replay.'}


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + '\n',
                    encoding='utf-8')


def write_report(result, comparison):
    lines = ['# Rating v1 K3-only source-corrected reevaluation', '',
             'Frozen Rating Method v1 was replayed from 2017-01-01 on K3-only Canonical.',
             '2017–2022 is warm-up. No model selection, parameter tuning, or v2 development was performed.',
             '', f"Method freeze SHA-256: `{result['freeze_sha256']}`.",
             f"K3 result version: `{result['source']['result_dataset_version']['version_id']}`.",
             f"Ordered input SHA-256: `{result['extract_sha256']}`.",
             f"Deterministic replay SHA-256: `{result['deterministic_sha256']}`.",
             '', '## Annual old → K3-corrected', '',
             '| Year | STRICT races | Course mean LL | P1 LL | P1 Brier | P1 ECE | P1 top1 | exact P2 LL | exact P2 Brier | exact P2 ECE | Overall LL | SHORT_50 LL |',
             '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    keys = ('strict_races', 'course_mean_log_loss', 'p1_log_loss', 'p1_brier',
            'p1_ece', 'p1_top1', 'exact_p2_log_loss', 'exact_p2_brier',
            'exact_p2_ece', 'overall_log_loss', 'short50_log_loss')
    for year in YEARS:
        fields = comparison['years'][str(year)]
        cells = [str(year)]
        for key in keys:
            item = fields[key]
            fmt = ',.0f' if key == 'strict_races' else '.6f'
            cells.append(f"{item['old']:{fmt}} → {item['new']:{fmt}}")
        lines.append('| ' + ' | '.join(cells) + ' |')
    lines += ['', 'Absolute and relative differences for every metric are in the comparison JSON.',
              '', '## Source correction and limits', '',
              '2022 STRICT warm-up races increased by 7; 2023 and 2024 STRICT scoring populations did not change.',
              'The K3 migration audit records 54 added 2022 result boats and two corrected 2023 actual-course values.',
              'For 2025, STRICT races increased by 174. Result-record-absent races decreased by 190,',
              'while result-present but non-STRICT races increased by 16.',
              'The migration audit records 1,500 added K3 result boats and 360 old-only boats removed;',
              'the known 2025-08-12 60 races / 360 entries have no K3 individual result and receive no STRICT update.',
              'These aggregate movements do not uniquely isolate the effect of each correction on the metrics.',
              'Full historical per-player rating-state snapshots were not saved, so old-versus-new state hashes cannot be compared.',
              'The frozen method and its artifact remain unchanged; future method changes require v2.', '']
    REPORT_OUT.write_text('\n'.join(lines), encoding='utf-8')


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('run', 'verify', 'summarize'))
    args = parser.parse_args()
    if args.action == 'summarize':
        dev = json.loads(DEV_OUT.read_text(encoding='utf-8'))
        holdout = json.loads(YEAR_2025_OUT.read_text(encoding='utf-8'))
        result = {'counts': {**dev['counts'], '2025': holdout['counts']},
                  'metrics': {**dev['metrics'], '2025': holdout['metrics']},
                  'deterministic_sha256': dev['deterministic_sha256'],
                  'source': dev['source'], 'freeze_sha256': dev['freeze_sha256'],
                  'extract_sha256': dev['extract_sha256']}
        comparison = old_new_comparison(result)
        save(DIFF_OUT, comparison)
        write_report(result, comparison)
        print(json.dumps({'status': 'PASS', 'comparison': str(DIFF_OUT),
                          'report': str(REPORT_OUT)}))
        return
    result = evaluate()
    if args.action == 'verify':
        saved = json.loads(DEV_OUT.read_text(encoding='utf-8'))
        if result['deterministic_sha256'] != saved['deterministic_sha256']:
            raise RuntimeError('deterministic Rating v1 K3 replay mismatch')
        print(json.dumps({'status': 'PASS', 'deterministic_sha256':
                          result['deterministic_sha256'],
                          'extract_sha256': result['extract_sha256']}))
        return
    comparison = old_new_comparison(result)
    dev = {key: result[key] for key in ('source_policy_checkpoint', 'freeze_sha256',
        'frozen_code_sha256', 'source', 'extract_version', 'extract_rows',
        'extract_rows_by_year', 'extract_sha256', 'replay_start', 'warmup_end',
        'state_checkpoints', 'deterministic_sha256', 'executed_at_utc')}
    dev['counts'] = {y: result['counts'][y] for y in ('2017', '2018', '2019',
        '2020', '2021', '2022', '2023', '2024')}
    dev['metrics'] = {y: result['metrics'][y] for y in ('2023', '2024')}
    dev['course_strata'] = {y: result['course_strata'][y] for y in ('2023', '2024')}
    holdout = {key: result[key] for key in ('source_policy_checkpoint', 'freeze_sha256',
        'frozen_code_sha256', 'source', 'extract_version', 'extract_rows',
        'extract_rows_by_year', 'extract_sha256', 'replay_start', 'warmup_end',
        'state_checkpoints', 'deterministic_sha256', 'executed_at_utc')}
    holdout['counts'] = result['counts']['2025']
    holdout['metrics'] = result['metrics']['2025']
    holdout['course_strata'] = result['course_strata']['2025']
    holdout['status'] = 'RATING_V1_K3_SOURCE_CORRECTED_REEVALUATION'
    save(DEV_OUT, dev)
    save(YEAR_2025_OUT, holdout)
    save(DIFF_OUT, comparison)
    write_report(result, comparison)
    print(json.dumps({'status': 'PASS', 'deterministic_sha256':
                      result['deterministic_sha256'], 'extract_rows': result['extract_rows'],
                      'strict_races': {y: result['counts'][str(y)]['strict_races'] for y in YEARS},
                      'outputs': [str(DEV_OUT), str(YEAR_2025_OUT), str(DIFF_OUT),
                                  str(REPORT_OUT)]}))


if __name__ == '__main__':
    main()
