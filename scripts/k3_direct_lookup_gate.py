"""Read-only, per-race K3 lookup for 2025 Canonical-only result candidates.

This gate deliberately uses no other individual-result source. It reports every
candidate and checks both the exact K3 key and parseable alternate encodings.
"""

import argparse
from collections import defaultdict
from datetime import date, datetime, timezone
import json
from pathlib import Path
import re

from scripts.db import source_connection, target_connection


def normalized_key(year, month_day, venue, race):
    parts = (year, month_day, venue, race)
    if any(value is None for value in parts):
        return None
    year, month_day, venue, race = (value.strip() for value in parts)
    if not (re.fullmatch(r'\d{4}', year) and re.fullmatch(r'\d{3,4}', month_day)
            and re.fullmatch(r'\d{1,2}', venue) and re.fullmatch(r'\d{1,2}', race)):
        return None
    try:
        day = date(int(year), int(month_day.zfill(4)[:2]), int(month_day.zfill(4)[2:]))
    except ValueError:
        return None
    return day, int(venue), int(race)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    source = source_connection()
    target = target_connection()
    target.commit()
    target.set_session(readonly=True, isolation_level='REPEATABLE READ')
    try:
        with source.cursor() as q:
            q.execute('SHOW transaction_read_only')
            assert q.fetchone()[0] == 'on'
            q.execute("SET LOCAL statement_timeout='0'")
            q.execute("SELECT DISTINCT kaisai_nen FROM public.brd_k3 WHERE kaisai_nen LIKE '%25%' ORDER BY 1")
            year_encodings = [row[0] for row in q]
        with target.cursor() as q:
            q.execute('SHOW transaction_read_only')
            assert q.fetchone()[0] == 'on'
            q.execute("SET LOCAL statement_timeout='0'")

        exact_races = set()
        normalized_races = defaultdict(list)
        malformed = 0
        with source.cursor(name='k3_gate_2025') as q:
            q.itersize = 10000
            q.execute("""SELECT kaisai_nen,kaisai_tsukihi,kyoteijo_code,race_no,
                               teiban,toroku_bango,record_id
                        FROM public.brd_k3 WHERE kaisai_nen LIKE '%25%'
                        ORDER BY kaisai_nen,kaisai_tsukihi,kyoteijo_code,race_no,teiban""")
            for row in q:
                raw_key = tuple(row[:4])
                exact_races.add(raw_key)
                key = normalized_key(*raw_key)
                if key is None:
                    malformed += 1
                elif key[0].year == 2025:
                    normalized_races[key].append(dict(raw_key=raw_key, boat_no=row[4],
                                                      player_registration=row[5], record_id=row[6]))

        canonical_races = defaultdict(list)
        with target.cursor(name='canonical_gate_2025') as q:
            q.itersize = 10000
            q.execute("""SELECT r.race_date,r.venue_code,r.race_no,z.boat_no,e.player_id
                         FROM core.race_result z JOIN core.race r USING(race_id)
                         JOIN core.race_entry e USING(race_id,boat_no)
                         WHERE r.race_date >= DATE '2025-01-01'
                           AND r.race_date < DATE '2026-01-01'
                         ORDER BY r.race_date,r.venue_code,r.race_no,z.boat_no""")
            for day, venue, race, boat, player in q:
                canonical_races[(day, venue, race)].append(dict(boat_no=boat,
                                                                player_registration=player))

        candidates = []
        for (day, venue, race), boats in sorted(canonical_races.items()):
            exact_key = (str(day.year), day.strftime('%m%d'), f'{venue:02d}', f'{race:02d}')
            if exact_key in exact_races:
                continue
            with source.cursor() as q:
                q.execute("""SELECT kaisai_nen,kaisai_tsukihi,kyoteijo_code,race_no,
                                    teiban,toroku_bango,record_id
                             FROM public.brd_k3
                             WHERE kaisai_nen=%s AND kaisai_tsukihi=%s
                               AND kyoteijo_code=%s AND race_no=%s ORDER BY teiban""", exact_key)
                direct = [dict(raw_key=row[:4], boat_no=row[4],
                               player_registration=row[5], record_id=row[6]) for row in q]
            alternate = normalized_races.get((day, venue, race), [])
            candidates.append(dict(date=day.isoformat(), venue=venue, race_no=race,
                                   canonical_boat_count=len(boats), canonical_boats=boats,
                                   k3_direct_lookup_count=len(direct), k3_direct_rows=direct,
                                   k3_normalized_lookup_count=len(alternate),
                                   k3_normalized_rows=alternate,
                                   classification='K3_PRESENT_PROBE_BUG' if direct or alternate
                                   else 'K3_ABSENT'))

        report = dict(generated_at=datetime.now(timezone.utc).isoformat(),
                      source='pckyotei.public.brd_k3', year_encodings=year_encodings,
                      malformed_k3_key_rows=malformed,
                      candidate_races=len(candidates),
                      candidate_boats=sum(r['canonical_boat_count'] for r in candidates),
                      k3_present_probe_bug=sum(r['classification'] == 'K3_PRESENT_PROBE_BUG' for r in candidates),
                      k3_absent=sum(r['classification'] == 'K3_ABSENT' for r in candidates),
                      races=candidates)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({k: v for k, v in report.items() if k != 'races'}, ensure_ascii=False))
        if (len(candidates), report['candidate_boats']) != (60, 360):
            raise RuntimeError('candidate population differs from prior probe; investigate before migration')
        if report['k3_present_probe_bug']:
            raise RuntimeError('K3 rows found for a prior probe omission; repair and rerun full probe')
    finally:
        source.rollback()
        target.rollback()
        source.close()
        target.close()


if __name__ == '__main__':
    main()
