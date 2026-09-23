"""Rebuild the 2017-01-01 F-state seed from late-2016 K3 observations."""

import argparse
from collections import defaultdict
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path

from scripts.db import source_connection, target_connection


FIRST_DAY = date(2017, 1, 1)
FIRST_RELEVANT_F = date(2016, 12, 3)
LAST_RELEVANT_F = date(2016, 12, 31)


def construct_seed(cohort, f_rows):
    """Return all cohort states; F rows are direct K3 result observations."""
    evidence = defaultdict(list)
    for player, year, month_day, venue, race, boat, token in f_rows:
        if token.strip() != 'F':
            raise ValueError('non-F row in seed evidence')
        event_day = date(int(year), int(month_day[:2]), int(month_day[2:]))
        if not FIRST_RELEVANT_F <= event_day <= LAST_RELEVANT_F:
            raise ValueError('seed F outside relevant window')
        if int(player) in cohort:
            evidence[int(player)].append(dict(
                date=event_day.isoformat(), venue_code=venue, race_no=race,
                boat_no=boat, finish_raw=token))
    rows = []
    for player in sorted(cohort):
        events = sorted(evidence[player], key=lambda e: (
            e['date'], e['venue_code'], e['race_no'], e['boat_no']))
        rows.append(dict(player_id=player,
                         state='ACTIVE_UNSERVED' if events else 'UNRESOLVED',
                         latest_f_date=events[-1]['date'] if events else None,
                         k3_f_events=events))
    return rows


def audit():
    source = source_connection()
    target = None
    try:
        target = target_connection()
        target.commit()
        target.set_session(readonly=True, isolation_level='REPEATABLE READ')
        with source.cursor() as cur:
            cur.execute('SHOW transaction_read_only')
            if cur.fetchone()[0] != 'on':
                raise RuntimeError('source transaction is not read-only')
            cur.execute("""SELECT DISTINCT toroku_bango FROM public.brd_l3
                WHERE kaisai_nen='2017' AND kaisai_tsukihi='0101'""")
            cohort = {int(row[0]) for row in cur}
            cur.execute("""SELECT toroku_bango,kaisai_nen,kaisai_tsukihi,
                kyoteijo_code,race_no,teiban,chakujun FROM public.brd_k3
                WHERE kaisai_nen='2016' AND kaisai_tsukihi BETWEEN '1203' AND '1231'
                  AND btrim(chakujun)='F'
                ORDER BY toroku_bango,kaisai_tsukihi,kyoteijo_code,race_no,teiban""")
            f_rows = cur.fetchall()
            cur.execute("""SELECT count(*) FILTER (WHERE l.toroku_bango IS NULL),
                count(*) FILTER (WHERE l.toroku_bango IS NOT NULL
                                  AND l.toroku_bango<>k.toroku_bango)
                FROM public.brd_k3 k LEFT JOIN public.brd_l3 l USING
                    (kaisai_nen,kaisai_tsukihi,kyoteijo_code,race_no,teiban)
                WHERE k.kaisai_nen='2016'
                  AND k.kaisai_tsukihi BETWEEN '1203' AND '1231'
                  AND btrim(k.chakujun)='F'
                  AND k.toroku_bango::integer=ANY(%s)""", (sorted(cohort),))
            l3_missing, l3_player_mismatch = cur.fetchone()
        with target.cursor() as cur:
            cur.execute('SHOW transaction_read_only')
            if cur.fetchone()[0] != 'on':
                raise RuntimeError('target transaction is not read-only')
            cur.execute("""SELECT DISTINCT e.player_id FROM core.race_entry e
                JOIN core.race r USING(race_id) WHERE r.race_date=DATE '2017-01-01'""")
            canonical_cohort = {int(row[0]) for row in cur}
            cur.execute("""SELECT version_id,authoritative_source,date_start,date_end,
                source_manifest_hash FROM core.result_dataset_version
                ORDER BY created_at DESC LIMIT 1""")
            version = cur.fetchone()
        rows = construct_seed(cohort, f_rows)
        active = sum(row['state'] == 'ACTIVE_UNSERVED' for row in rows)
        serialized = json.dumps(rows, ensure_ascii=False, sort_keys=True,
                                separators=(',', ':')).encode('utf-8')
        issues = []
        if cohort != canonical_cohort:
            issues.append('2017-01-01 L3 and Canonical player cohorts differ')
        if l3_missing or l3_player_mismatch:
            issues.append('late-2016 K3 F key/player disagrees with L3')
        f_keys = [(year, md, venue, race, boat)
                  for _, year, md, venue, race, boat, _ in f_rows]
        if len(f_keys) != len(set(f_keys)):
            issues.append('duplicate late-2016 K3 F result key')
        if len(cohort) != 617:
            issues.append('unexpected initial cohort size')
        if version is None or version[1] != 'brd_k3' or version[2] != FIRST_DAY:
            issues.append('formal K3-only result dataset version absent')
        if any(row['latest_f_date'] and
               (FIRST_DAY - date.fromisoformat(row['latest_f_date'])).days >= 30
               for row in rows):
            issues.append('active seed outside 29-day window')
        return dict(status='PASS' if not issues else 'BLOCKED', issues=issues,
                    generated_at=datetime.now(timezone.utc).isoformat(),
                    cohort_source='pckyotei.public.brd_l3 2017-01-01; independently matched to core.race_entry',
                    initial_state_source='pckyotei.public.brd_k3 2016-12-03..2016-12-31 chakujun=F',
                    policy='late K3 F proves ACTIVE; all other initial states remain UNRESOLVED',
                    initial_day=FIRST_DAY.isoformat(), cohort_players=len(cohort),
                    active=active, unresolved=len(rows)-active,
                    source_window_f_rows=len(f_rows),
                    source_window_cohort_f_rows=sum(len(row['k3_f_events']) for row in rows),
                    source_window_cohort_l3_missing=l3_missing,
                    source_window_cohort_l3_player_mismatch=l3_player_mismatch,
                    player_rows_sha256=hashlib.sha256(serialized).hexdigest(),
                    result_dataset_version=dict(version_id=version[0],
                        authoritative_source=version[1], date_start=str(version[2]),
                        date_end=str(version[3]), source_manifest_hash=version[4]) if version else None,
                    players=rows)
    finally:
        source.rollback()
        source.close()
        if target is not None:
            target.rollback()
            target.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    report = audit()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n',
                           encoding='utf-8')
    print(json.dumps({key: report[key] for key in ('status', 'issues',
        'cohort_players', 'active', 'unresolved', 'source_window_f_rows',
        'source_window_cohort_f_rows', 'player_rows_sha256')}, ensure_ascii=False))
    if report['status'] != 'PASS':
        raise RuntimeError('K3-only initial seed audit blocked')


if __name__ == '__main__':
    main()
