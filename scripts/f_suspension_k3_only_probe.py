"""Read-only K3-only F-event replay; no feature or Canonical writes."""
from collections import Counter, defaultdict
from datetime import date, timedelta, datetime, timezone
import json
from pathlib import Path
import re

from scripts.db import source_connection, target_connection


START = date(2017, 1, 1)
ANCHOR = date(2016, 12, 31)
OUT = Path('.local/f_suspension_k3_only_probe.json')


class State:
    def __init__(self, seed=None):
        self.value = 'ACTIVE_UNSERVED' if seed else 'UNRESOLVED'
        self.last_possible_race = ANCHOR
        self.last_confirmed_race = seed
        self.pending_f = 1 if seed else 0
        self.seed = seed
        self.first_resolution = None

    def day(self, day, confirmed=0, possible=0, f_events=0):
        old = self.value
        gap = (day - self.last_possible_race).days
        if self.value != 'CLEAR' and gap >= 30:
            self.value = 'CLEAR'
            self.pending_f = 0
        before = self.value
        if self.seed is None and self.first_resolution is None and before == 'CLEAR':
            self.first_resolution = 'CLEAR_BY_GAP'
        if possible and before == 'CLEAR':
            self.value = 'UNRESOLVED'
        if confirmed or possible:
            self.last_possible_race = day
        if confirmed:
            self.last_confirmed_race = day
        f2 = 0
        if f_events:
            f2 = f_events if before == 'ACTIVE_UNSERVED' and self.pending_f else max(0, f_events - 1)
            self.pending_f = self.pending_f + f_events if before == 'ACTIVE_UNSERVED' else f_events
            self.value = 'ACTIVE_UNSERVED'
            if self.seed is None and self.first_resolution is None:
                self.first_resolution = 'ACTIVE_BY_F'
        return dict(before=before, after=self.value, cleared=old != 'CLEAR' and before == 'CLEAR',
                    f2=f2, gap=gap, clear_on_entry=bool(confirmed or possible))


def self_test():
    x = State()
    assert x.day(START, confirmed=1, f_events=1)['before'] == 'UNRESOLVED'
    assert x.day(date(2017, 1, 30))['before'] == 'ACTIVE_UNSERVED'
    assert x.day(date(2017, 1, 31))['before'] == 'CLEAR'
    x = State()
    x.day(START, confirmed=1, f_events=1)
    x.day(date(2017, 1, 11), confirmed=1, f_events=1)
    assert x.last_confirmed_race == date(2017, 1, 11)
    assert x.day(date(2017, 2, 10))['before'] == 'CLEAR'
    x = State()
    assert x.day(START, confirmed=1, f_events=1)['before'] == 'UNRESOLVED'
    assert x.day(date(2017, 1, 2), confirmed=1)['before'] == 'ACTIVE_UNSERVED'
    x = State(date(2016, 12, 31))
    assert x.day(START)['before'] == 'ACTIVE_UNSERVED'


def main(canonical=False):
    self_test()
    conn = source_connection()
    target = target_connection() if canonical else None
    if target is not None:
        target.commit()
        target.set_session(readonly=True, isolation_level='REPEATABLE READ')
        with target.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout='0'")
    counts = Counter()
    before_counts = Counter()
    final = Counter()
    initial = Counter()
    yearly_f = Counter()
    examples = defaultdict(list)
    try:
        with conn.cursor() as q:
            q.execute('SHOW transaction_read_only')
            assert q.fetchone()[0] == 'on'
            q.execute("SET LOCAL statement_timeout='0'")
            q.execute("SET LOCAL work_mem='64MB'")
            q.execute("SELECT max(kaisai_nen||kaisai_tsukihi) FROM public.brd_k3 WHERE kaisai_nen>='2017'")
            end = date.fromisoformat(q.fetchone()[0])
            q.execute("SELECT DISTINCT toroku_bango FROM public.brd_l3 WHERE kaisai_nen='2017' AND kaisai_tsukihi='0101'")
            jan1 = {int(row[0]) for row in q}
            q.execute("""SELECT toroku_bango,max(kaisai_tsukihi) FROM public.brd_k3
                       WHERE kaisai_nen='2016' AND kaisai_tsukihi>='1203'
                         AND btrim(chakujun)='F' GROUP BY toroku_bango""")
            seed = {int(player): date(2016, int(md[:2]), int(md[2:]))
                    for player, md in q if int(player) in jan1}
        current_player = current_day = None
        state = None
        day_cursor = START
        evidence = Counter()
        race_numbers = []
        f_players = set()

        def process(day, ev, races):
            result = state.day(day, ev['confirmed'], ev['possible'], ev['f'])
            counts['calendar_player_days'] += 1
            if ev['entries']:
                counts['entry_player_days'] += 1
                counts['entries'] += ev['entries']
                before_counts[result['before']] += ev['entries']
                if ev['f']:
                    counts['f_player_days'] += 1
                if ev['entries'] > 1 and ev['f']:
                    counts['multi_race_f_player_days'] += 1
            if result['cleared']:
                counts['clear_transitions'] += 1
                counts['clear_on_entry_day' if result['clear_on_entry'] else 'clear_on_no_entry_day'] += 1
            if result['before'] != 'ACTIVE_UNSERVED' and ev['f']:
                counts['transitions_to_active'] += 1
            counts['f2_additional_events'] += result['f2']
            if ev['possible']:
                counts['possible_races'] += ev['possible']
                if result['before'] == 'CLEAR':
                    counts['clear_to_unresolved_possible_f'] += 1
            if ev['f'] and len(examples['f']) < 5:
                examples['f'].append(dict(player=current_player, day=str(day), before=result['before'],
                                          after=result['after'], f=ev['f'], races=races))

        def flush_player():
            nonlocal day_cursor
            if state is None:
                return
            while day_cursor <= end:
                process(day_cursor, Counter(), [])
                day_cursor += timedelta(days=1)
            final[state.value] += 1
            if state.seed is None:
                initial[state.first_resolution or 'STILL_UNRESOLVED_INITIAL'] += 1
            counts['players'] += 1

        feed = target if canonical else conn
        with feed.cursor(name='k3_f_replay') as q:
            q.itersize = 10000
            if canonical:
                q.execute("""SELECT e.player_id::text,to_char(r.race_date,'YYYY'),
                       to_char(r.race_date,'MMDD'),lpad(r.venue_code::text,2,'0'),
                       lpad(r.race_no::text,2,'0'),e.boat_no::text,
                       CASE WHEN z.race_id IS NOT NULL THEN e.player_id::text END,
                       z.finish_raw,z.start_timing_raw,z.actual_course_raw,
                       CASE WHEN rs.has_verified_r2_event_code THEN '9' END
                       FROM core.race_entry e JOIN core.race r USING(race_id)
                       LEFT JOIN core.race_result z USING(race_id,boat_no)
                       LEFT JOIN core.race_result_state rs USING(race_id)
                       WHERE r.race_date BETWEEN DATE '2017-01-01' AND %s
                       ORDER BY e.player_id,r.race_date,r.venue_code,r.race_no,e.boat_no""",
                          (end,))
            else:
                q.execute("""SELECT l.toroku_bango,l.kaisai_nen,l.kaisai_tsukihi,
                       l.kyoteijo_code,l.race_no,l.teiban,k.toroku_bango,
                       k.chakujun,k.st,k.shinnyu_course,r.data_kubun
                       FROM public.brd_l3 l
                       LEFT JOIN public.brd_k3 k USING
                         (kaisai_nen,kaisai_tsukihi,kyoteijo_code,race_no,teiban)
                       LEFT JOIN public.brd_r2 r USING
                         (kaisai_nen,kaisai_tsukihi,kyoteijo_code,race_no)
                       WHERE l.kaisai_nen>='2017'
                         AND l.kaisai_nen||l.kaisai_tsukihi<=%s
                       ORDER BY l.toroku_bango,l.kaisai_nen,l.kaisai_tsukihi,
                                l.kyoteijo_code,l.race_no,l.teiban""", (end.strftime('%Y%m%d'),))
            for player_raw, year, md, venue, race, boat, k_player, finish, st, course, event_code in q:
                player = int(player_raw)
                day = date(int(year), int(md[:2]), int(md[2:]))
                if player != current_player:
                    if state is not None:
                        if current_day is not None:
                            while day_cursor < current_day:
                                process(day_cursor, Counter(), [])
                                day_cursor += timedelta(days=1)
                            process(current_day, evidence, race_numbers)
                            day_cursor = current_day + timedelta(days=1)
                        flush_player()
                    current_player, current_day = player, None
                    state = State(seed.get(player))
                    day_cursor = START
                    evidence = Counter()
                    race_numbers = []
                if day != current_day:
                    if current_day is not None:
                        while day_cursor < current_day:
                            process(day_cursor, Counter(), [])
                            day_cursor += timedelta(days=1)
                        process(current_day, evidence, race_numbers)
                        day_cursor = current_day + timedelta(days=1)
                    current_day, evidence, race_numbers = day, Counter(), []
                evidence['entries'] += 1
                race_numbers.append([venue, race])
                if k_player is not None and k_player != player_raw:
                    counts['identity_mismatch'] += 1
                    evidence['possible'] += 1
                    continue
                if k_player is None:
                    counts['k3_missing_entries'] += 1
                    if event_code == '9':
                        counts['r2_cancelled_entries'] += 1
                    else:
                        evidence['possible'] += 1
                    continue
                token = finish.strip() if finish is not None else ''
                if token == 'F':
                    evidence['f'] += 1
                    evidence['confirmed'] += 1
                    counts['f_events'] += 1
                    yearly_f[year] += 1
                    f_players.add(player)
                elif token in ('01','02','03','04','05','06','L0','L1'):
                    evidence['confirmed'] += 1
                elif token.startswith('K'):
                    counts['k_code_nonstarter_entries'] += 1
                elif st is not None and re.fullmatch(r'[0-9]{3}', st):
                    # Measured start is appearance evidence, not a numeric finish.
                    evidence['confirmed'] += 1
                    counts['special_finish_started_entries'] += 1
                else:
                    evidence['possible'] += 1
                    counts['unresolved_finish_entries'] += 1
        if current_day is not None:
            while day_cursor < current_day:
                process(day_cursor, Counter(), [])
                day_cursor += timedelta(days=1)
            process(current_day, evidence, race_numbers)
            day_cursor = current_day + timedelta(days=1)
        flush_player()
        counts['f_event_players'] = len(f_players)
        report = dict(probe='f-suspension-k3-only-v1',
                      source='core.race_result K3-only Canonical' if canonical else 'pckyotei.public.brd_k3',
                      scope=[START.isoformat(), end.isoformat()],
                      generated_at=datetime.now(timezone.utc).isoformat(),
                      self_test='PASS', initial_jan1_players=len(jan1),
                      initial_jan1_active_seed=len(seed),
                      initial_jan1_unresolved=len(jan1)-len(seed),
                      counts=counts, prediction_entry_state=before_counts,
                      final_state=final, initial_unknown_first_resolution=initial,
                      yearly_f=yearly_f, examples=examples,
                      treatment='K3 F is sole F event; numeric/L or measured start confirm racing, K with blank start is nonstarter, other specials unresolved; R2 only classifies cancelled entries')
        output = (Path('.local/f_suspension_k3_canonical.json') if canonical else OUT)
        output.parent.mkdir(exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=dict), encoding='utf-8')
        print(json.dumps({'output':str(output), 'counts':counts, 'prediction_entry_state':before_counts,
                          'final_state':final, 'initial_jan1_active_seed':len(seed)},
                         ensure_ascii=False, default=dict))
    finally:
        conn.rollback()
        conn.close()
        if target is not None:
            target.rollback()
            target.close()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--canonical',action='store_true')
    main(parser.parse_args().canonical)
