"""Read-only Rating preparation coverage audit. No ratings or eligibility policy.

Run from the repository root. The database transaction is repeatable-read and
read-only; the only output is the requested local JSON file.
"""
import argparse
from collections import Counter, defaultdict
from datetime import date
import json
from pathlib import Path
from statistics import median

from scripts.db import target_connection


YEARS = (2023, 2024, 2025)
SPECIALS = ('転', '欠', '落', 'エ', '妨', '不', '沈', '失', '＿', 'K', 'S', '00', 'F', 'L0', 'L1')


def add(table, year, key, value=1):
    table[year][key] += value


def finish_race(boats, state, counters, specials, fl, courses, overall):
    year = boats[0][1].year
    race_id = boats[0][0]
    result_state = state[race_id]
    n = len(boats)
    finish_states = [b[4] for b in boats]
    numeric = [b for b in boats if b[4] == 'NUMERIC_VALID']
    course_rows = [b for b in numeric if b[6] is not None]
    full_numeric = n == 6 and len(numeric) == 6
    strict = (result_state == 'RESULT_RECORDS_PRESENT' and full_numeric
              and all(b[9] for b in boats))
    course_permutation = n == 6 and all(b[6] is not None for b in boats) and sorted(b[6] for b in boats) == [1, 2, 3, 4, 5, 6]
    course_strict = strict and course_permutation
    add(counters, year, 'boats', n)
    add(counters, year, 'numeric_valid_boats', len(numeric))
    add(counters, year, 'numeric_valid_with_course_boats', len(course_rows))
    add(counters, year, 'actual_course_present_boats', sum(b[6] is not None for b in boats))
    add(counters, year, 'canonical_result_boats', sum(b[9] for b in boats))
    add(counters, year, 'numeric_raw_boats', sum(b[5] is not None for b in boats))
    add(counters, year, 'strict_races', strict)
    add(counters, year, 'course_strict_races', course_strict)
    add(counters, year, 'full_numeric_races', full_numeric)
    add(counters, year, 'six_course_present_races', n == 6 and all(b[6] is not None for b in boats))
    add(counters, year, 'unique_six_course_races', course_permutation)
    add(counters, year, 'numeric_duplicate_races', any(s == 'NUMERIC_DUPLICATE_UNRESOLVED' for s in finish_states))
    add(counters, year, 'numeric_duplicate_boats', finish_states.count('NUMERIC_DUPLICATE_UNRESOLVED'))
    add(counters, year, 'unresolved_boat_state_races', any(s.startswith('UNRESOLVED') or 'DUPLICATE' in s for s in finish_states))
    add(counters, year, 'row_candidates_in_unresolved_races', len(course_rows) if result_state == 'UNRESOLVED' else 0)
    add(counters, year, 'row_candidates_other_races', len(course_rows) if result_state != 'UNRESOLVED' else 0)
    add(counters, year, 'numeric_valid_pairs', len(numeric) * (len(numeric) - 1) // 2)
    add(counters, year, 'numeric_valid_pair_races', len(numeric) >= 2)
    add(counters, year, 'unique_winner_races', sum(b[5] == 1 for b in numeric) == 1)
    add(counters, year, 'unique_exact_second_races', sum(b[5] == 2 for b in numeric) == 1)
    for s in set(finish_states):
        add(overall, year, 'finish_state_races:' + s)
    for s in finish_states:
        add(overall, year, 'finish_state_boats:' + s)
    for b in course_rows:
        key = str(b[6])
        courses[year][key]['boats'] += 1
        courses[year][key]['first'] += b[5] == 1
        courses[year][key]['exact_second'] += b[5] == 2
        if course_strict:
            courses[year][key]['course_strict_boats'] += 1
            courses[year][key]['course_strict_first'] += b[5] == 1
            courses[year][key]['course_strict_exact_second'] += b[5] == 2
    for course in {b[6] for b in course_rows}:
        courses[year][str(course)]['races'] += 1
    symbol_rows = [b for b in boats if b[4] == 'UNRESOLVED_SPECIAL']
    for symbol in {b[8] for b in symbol_rows}:
        entry = specials[year][symbol]
        entry['races'] += 1
        entry['boats'] += sum(b[8] == symbol for b in symbol_rows)
        entry['races_without_valid_first'] += not any(b[5] == 1 for b in numeric)
        entry['races_without_valid_second'] += not any(b[5] == 2 for b in numeric)
        entry['strict_excluded_races_containing_symbol'] += not strict
        entry['sole_special_blocker_races'] += (
            result_state == 'RESULT_RECORDS_PRESENT' and n == 6
            and len(symbol_rows) == 1 and len(numeric) == 5
            and symbol_rows[0][8] == symbol
        )
    fl_rows = [b for b in boats if b[7] in ('F', 'L')]
    if fl_rows:
        fl[year]['races_with_f_or_l'] += 1
        for b in fl_rows:
            fl[year][b[7] + ':boats'] += 1
            fl[year][b[7] + ':numeric_finish'] += b[4] == 'NUMERIC_VALID'
            fl[year][b[7] + ':special_finish'] += b[4] == 'UNRESOLVED_SPECIAL'
            fl[year][b[7] + ':other_finish'] += b[4] not in ('NUMERIC_VALID', 'UNRESOLVED_SPECIAL')
        fl[year]['other_boats'] += n - len(fl_rows)
        fl[year]['other_numeric_valid'] += sum(b[4] == 'NUMERIC_VALID' and b[7] not in ('F', 'L') for b in boats)
        fl[year]['other_special'] += sum(b[4] == 'UNRESOLVED_SPECIAL' and b[7] not in ('F', 'L') for b in boats)
        fl[year]['other_missing_or_duplicate'] += sum(b[4] not in ('NUMERIC_VALID', 'UNRESOLVED_SPECIAL') and b[7] not in ('F', 'L') for b in boats)


def cohort_month(training_class):
    if training_class is None or training_class <= 0 or training_class > 139:
        return None
    index = 2026 * 12 + 10 - (139 - training_class) * 6  # 2026-11 anchor
    return date(index // 12, index % 12 + 1, 1)


def summarize_depth(players, active, boundary, year):
    ids = active[year]
    prior = boundary[year]
    entry_depth = [prior.get(p, (0, 0))[0] for p in ids]
    numeric_depth = [prior.get(p, (0, 0))[1] for p in ids]
    return {
        'active_players': len(ids),
        'prior_entry_0': sum(n == 0 for n in entry_depth),
        'prior_entry_1_49': sum(0 < n < 50 for n in entry_depth),
        'prior_entry_50_plus': sum(n >= 50 for n in entry_depth),
        'prior_numeric_0': sum(n == 0 for n in numeric_depth),
        'prior_numeric_1_49': sum(0 < n < 50 for n in numeric_depth),
        'prior_numeric_50_plus': sum(n >= 50 for n in numeric_depth),
        'prior_entry_min': min(entry_depth, default=None),
        'prior_entry_median': median(entry_depth) if entry_depth else None,
        'prior_numeric_median': median(numeric_depth) if numeric_depth else None,
    }


def run():
    conn = target_connection()
    try:
        conn.commit()
        conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
        with conn.cursor() as cur:
            cur.execute("SELECT current_database(),current_setting('transaction_read_only'),pg_current_snapshot()::text")
            db, ro, snapshot = cur.fetchone()
            if db != 'boatrace_predictor' or ro != 'on':
                raise RuntimeError('expected target read-only snapshot')
            cur.execute("SET LOCAL statement_timeout='0'")
            cur.execute("SELECT source_table,count(*),min(extraction_condition->>'partition'),max(extraction_condition->>'partition') FROM raw.source_batch WHERE source_table IN ('brd_l2','brd_l3','brd_k3') AND extraction_condition->>'partition' BETWEEN '2017-01' AND '2025-12' GROUP BY 1 ORDER BY 1")
            source_months = [dict(source_table=t, months=n, first=lo, last=hi) for t,n,lo,hi in cur.fetchall()]
            cur.execute("SELECT player_id,training_class,training_class_raw FROM core.player")
            classes = {p:(c,raw) for p,c,raw in cur.fetchall()}
            cur.execute("""SELECT s.raw_payload->>'toroku_bango',s.raw_payload->>'yosei_ki',
                s.raw_payload->>'kaisai_nen' FROM raw.source_record s
                JOIN raw.source_batch b USING(source_batch_id)
                WHERE b.source_table='brd_ki'""")
            raw_ki = defaultdict(list)
            for player_raw,class_raw,year_raw in cur:
                if player_raw and player_raw.strip().isdigit():
                    player_id = int(player_raw.strip())
                    if player_id in classes:
                        raw_ki[player_id].append((int(class_raw.strip()) if class_raw and class_raw.strip().isdigit() else None,
                                                  int(year_raw.strip()) if year_raw and year_raw.strip().isdigit() else None))
            cur.execute("SELECT race_id,extract(year FROM race_date)::int,result_state FROM core.race_result_state WHERE race_date BETWEEN DATE '2023-01-01' AND DATE '2025-12-31'")
            race_state = {}
            race_states = defaultdict(Counter)
            for race_id,year,status in cur:
                race_state[race_id] = status
                add(race_states, year, status)
                add(race_states, year, 'total_races')
        print('Race states loaded; streaming boat evidence and player history', flush=True)
        counters, overall = defaultdict(Counter), defaultdict(Counter)
        specials = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
        fl = defaultdict(Counter)
        courses = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
        players = defaultdict(lambda: {'first':None, 'last':None, 'entries':0, 'numeric':0, 'entry_50_date':None, 'numeric_50_date':None})
        active = defaultdict(set)
        history_years = defaultdict(Counter)
        boundary = {}
        current_year = 2017
        boats = []
        with conn.cursor(name='rating_prep_boats') as cur:
            cur.itersize = 20000
            cur.execute("""SELECT b.race_id,b.race_date,b.boat_no,e.player_id,b.finish_state,
                b.finish_position,b.actual_course,b.start_timing_status,b.finish_raw,
                z.race_id IS NOT NULL AS canonical_result
                FROM core.boat_finish_state b JOIN core.race_entry e USING(race_id,boat_no)
                LEFT JOIN core.race_result z USING(race_id,boat_no)
                WHERE b.race_date <= DATE '2025-12-31'
                ORDER BY b.race_date,b.race_id,b.boat_no""")
            for b in cur:
                race_id,day,boat_no,player,finish_state,finish,course,st,raw,has_result = b
                year = day.year
                if year != current_year:
                    for y in range(current_year + 1, min(year, 2025) + 1):
                        if y in YEARS:
                            boundary[y] = {p:(v['entries'],v['numeric']) for p,v in players.items()}
                    current_year = year
                info = players[player]
                if info['first'] is None:
                    info['first'] = day
                    history_years[year]['first_observed_players'] += 1
                info['last'] = day
                info['entries'] += 1
                history_years[year]['entry_appearances'] += 1
                if info['entries'] == 50:
                    info['entry_50_date'] = day
                    history_years[year]['entry_50_reached_players'] += 1
                if finish_state == 'NUMERIC_VALID':
                    info['numeric'] += 1
                    history_years[year]['numeric_valid_finishes'] += 1
                    if info['numeric'] == 50:
                        info['numeric_50_date'] = day
                        history_years[year]['numeric_50_reached_players'] += 1
                active[year].add(player)
                if year in YEARS:
                    if not boats or boats[0][0] == race_id:
                        boats.append(b)
                    else:
                        finish_race(boats, race_state, counters, specials, fl, courses, overall)
                        boats = [b]
            if boats:
                finish_race(boats, race_state, counters, specials, fl, courses, overall)
        for y in YEARS:
            boundary.setdefault(y, {p:(v['entries'],v['numeric']) for p,v in players.items()})
        if set(race_state) != set() and sum(race_states[y]['total_races'] for y in YEARS) < sum(counters[y]['strict_races'] for y in YEARS):
            raise RuntimeError('race coverage reconciliation failed')
        for year in YEARS:
            if counters[year]['boats'] != race_states[year]['total_races'] * 6:
                raise RuntimeError(f'{year}: entries must be six per race')
            if sum(courses[year][str(c)]['boats'] for c in range(1,7)) != counters[year]['numeric_valid_with_course_boats']:
                raise RuntimeError(f'{year}: course candidate reconciliation failed')
        warmup = boundary[2023]
        observed_50 = [((p['entry_50_date']-p['first']).days, (p['entry_50_date']-p['first']).days / 30.4375)
                       for p in players.values() if p['entry_50_date']]
        numeric_50 = [(p['numeric_50_date']-p['first']).days for p in players.values() if p['numeric_50_date']]
        post_2017_entry_50 = [(p['entry_50_date']-p['first']).days for p in players.values()
                              if p['first'] >= date(2018,1,1) and p['entry_50_date']]
        post_2017_numeric_50 = [(p['numeric_50_date']-p['first']).days for p in players.values()
                                if p['first'] >= date(2018,1,1) and p['numeric_50_date']]
        newcomers = defaultdict(Counter)
        raw_newcomers = defaultdict(Counter)
        for player_id,info in players.items():
            cls, raw = classes.get(player_id,(None,None))
            debut_month = cohort_month(cls)
            first = info['first']
            relevant_year = first.year if first and first.year in YEARS else 'all'
            for group in ('all', relevant_year) if relevant_year != 'all' else ('all',):
                newcomers[group]['players'] += 1
                newcomers[group]['training_class_present'] += cls is not None
                newcomers[group]['debut_month_calculable'] += debut_month is not None
                if debut_month is None or debut_month < date(2017,1,1):
                    newcomers[group]['pre_2017_or_unavailable_cohort_coverage'] += 1
                else:
                    newcomers[group]['cohort_window_covered_from_start'] += 1
                    if first >= debut_month and first < date(debut_month.year+1,debut_month.month,1):
                        newcomers[group]['observed_first_within_12_month_window'] += 1
                    else:
                        newcomers[group]['observed_first_outside_12_month_window'] += 1
                observations = raw_ki.get(player_id, ())
                values = {c for c,y in observations if c is not None and 0 < c <= 139}
                raw_newcomers[group]['players'] += 1
                raw_newcomers[group]['any_raw_ki'] += bool(observations)
                raw_newcomers[group]['any_raw_ki_class'] += bool(values)
                raw_newcomers[group]['conflicting_raw_classes'] += len(values) > 1
                if len(values) == 1:
                    raw_newcomers[group]['unique_raw_class'] += 1
                    raw_newcomers[group]['class_observed_before_first_year'] += any(
                        c in values and y is not None and y < first.year for c,y in observations)
                    raw_newcomers[group]['class_observed_same_first_year'] += any(
                        c in values and y == first.year for c,y in observations)
                    raw_newcomers[group]['class_observed_after_first_year'] += any(
                        c in values and y is not None and y > first.year for c,y in observations)
                    raw_newcomers[group]['class_only_same_or_later_year'] += not any(
                        c in values and y is not None and y < first.year for c,y in observations)
                    raw_debut_month = cohort_month(next(iter(values)))
                    if raw_debut_month and raw_debut_month >= date(2017,1,1):
                        raw_newcomers[group]['cohort_window_covered_from_start'] += 1
                        if first >= raw_debut_month and first < date(raw_debut_month.year+1,raw_debut_month.month,1):
                            raw_newcomers[group]['observed_first_within_12_month_window'] += 1
                        else:
                            raw_newcomers[group]['observed_first_outside_12_month_window'] += 1
        return {
            'audit_version':'RATING_PREP_COVERAGE_V1', 'database':db,
            'transaction_read_only':ro, 'snapshot':snapshot,
            'definitions':{
                'strict':'RESULT_RECORDS_PRESENT, six canonical result rows, and six NUMERIC_VALID finishes',
                'course_strict':'strict plus actual_course is exactly permutation 1..6',
                'row_candidate':'NUMERIC_VALID finish with canonical actual_course 1..6; race may be incomplete',
                'history_entry':'observed race_entry appearance; pre-day counts for boundary years',
                'history_numeric':'observed NUMERIC_VALID finish; pre-day counts for boundary years',
                'newcomer':'observed first entry in [cohort debut month, same month next year); true career first remains unverified',
                'symbol_sole_blocker':'one special boat, other five NUMERIC_VALID, RESULT_RECORDS_PRESENT; counterfactual only, not an adopted result',
            },
            'source_months':source_months,
            'years':{str(y):{
                'race_states':dict(race_states[y]), 'coverage':dict(counters[y]),
                'finish_states':dict(overall[y]),
                'specials':{s:dict(specials[y][s]) for s in SPECIALS},
                'fl':dict(fl[y]), 'courses':{str(c):dict(courses[y][str(c)]) for c in range(1,7)},
                'player_depth_at_year_start':summarize_depth(players,active,boundary,y),
                'newcomer_first_observed_year':dict(newcomers[y]),
                'newcomer_raw_ki_first_observed_year':dict(raw_newcomers[y]),
            } for y in YEARS},
            'history':{
                'players_observed_through_2025':len(players),
                'players_with_pre_2023_entry':sum(n[0]>0 for n in warmup.values()),
                'players_with_pre_2023_numeric_valid':sum(n[1]>0 for n in warmup.values()),
                'players_with_pre_2023_entry_50_plus':sum(n[0]>=50 for n in warmup.values()),
                'players_with_pre_2023_numeric_valid_50_plus':sum(n[1]>=50 for n in warmup.values()),
                'players_first_observed_2017':sum(v['first'].year==2017 for v in players.values()),
                'players_first_observed_2023_or_later':sum(v['first'].year>=2023 for v in players.values()),
                'entry_50_reached_players':len(observed_50),
                'entry_50_elapsed_days_median':median(x[0] for x in observed_50) if observed_50 else None,
                'entry_50_elapsed_days_max':max((x[0] for x in observed_50),default=None),
                'numeric_50_reached_players':len(numeric_50),
                'numeric_50_elapsed_days_median':median(numeric_50) if numeric_50 else None,
                'numeric_50_elapsed_days_max':max(numeric_50,default=None),
                'first_observed_2018_plus_entry_50_reached_players':len(post_2017_entry_50),
                'first_observed_2018_plus_entry_50_elapsed_days_median':median(post_2017_entry_50) if post_2017_entry_50 else None,
                'first_observed_2018_plus_numeric_50_reached_players':len(post_2017_numeric_50),
                'first_observed_2018_plus_numeric_50_elapsed_days_median':median(post_2017_numeric_50) if post_2017_numeric_50 else None,
            },
            'history_by_year':{str(y):dict(history_years[y],active_players=len(active[y])) for y in range(2017,2026)},
            'newcomers':dict(newcomers['all']),
            'newcomers_raw_ki':dict(raw_newcomers['all']),
        }
    finally:
        conn.rollback()
        conn.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',type=Path,required=True)
    args = parser.parse_args()
    result = run()
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
    print(json.dumps({'report':str(args.report),'years':list(result['years']),
                      'transaction_read_only':result['transaction_read_only']},ensure_ascii=False))
