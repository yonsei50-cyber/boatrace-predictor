"""Read-only K3 result reconstruction and comparison with stored Canonical values.

This probe never reads another individual-result source and never updates either DB.
It keeps K3 strings intact and reports uncertainty for special finish codes.
"""
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import re

from scripts.db import source_connection, target_connection


OUT = Path('.local/k3_only_rebuild_probe.json')
START = date(2017, 1, 1)
SAMPLE_LIMIT = 8


def parsed_int(raw, low, high):
    if raw is None or not re.fullmatch(r'[0-9]+', raw):
        return None
    value = int(raw)
    return value if low <= value <= high else None


def normalize_k3(finish, course, st):
    """Map only the K3 finish classes needed by current Canonical consumers.

    K3 has no separate start symbol column. F and L classes are recognized from
    their finish tokens; S/K/00 retain their raw tokens and stay unresolved.
    """
    token = finish.strip() if finish is not None else ''
    position = parsed_int(token, 1, 6)
    if token == 'F':
        status = 'F'
    elif token in ('L0', 'L1'):
        status = 'L'
    elif position is not None:
        status = 'NORMAL'
    else:
        status = 'UNRESOLVED'
    if status in ('F', 'L'):
        timing, timing_status = None, status
    elif st is None or not st.strip():
        timing, timing_status = None, 'MISSING'
    elif re.fullmatch(r'[0-9]{3}', st):
        timing, timing_status = Decimal(st) / 100, 'NORMAL'
    else:
        timing, timing_status = None, 'UNRESOLVED'
    actual = parsed_int(course, 1, 6)
    unresolved = (status == 'UNRESOLVED' or timing_status == 'UNRESOLVED'
                  or (course is not None and course.strip() and actual is None))
    return dict(finish_raw=finish, finish_position=position, result_status=status,
                actual_course_raw=course, actual_course=actual,
                start_timing_raw=st, start_timing=timing,
                start_timing_status=timing_status,
                normalization_status='UNRESOLVED' if unresolved else 'NORMALIZED')


def source_key(row):
    return row[0] + row[1], row[2], row[3], row[4]


def target_key(row):
    day, venue, race_no, boat = row[:4]
    return day.strftime('%Y%m%d'), f'{venue:02d}', f'{race_no:02d}', f'{boat:1d}'


def add_example(report, name, payload):
    if len(report['examples'][name]) < SAMPLE_LIMIT:
        report['examples'][name].append(payload)


def main():
    source = source_connection()
    target = target_connection()
    target.commit()
    target.set_session(readonly=True, isolation_level='REPEATABLE READ')
    report = dict(probe='k3-only-result-v1', scope_start=START.isoformat(),
                  generated_at=datetime.now(timezone.utc).isoformat(),
                  source='pckyotei.public.brd_k3',
                  comparison='stored core.race_result and core.race_entry only',
                  counts=Counter(), differences=Counter(), by_year=defaultdict(Counter),
                  examples=defaultdict(list), special_finish=Counter())
    try:
        with source.cursor() as q:
            q.execute("SHOW transaction_read_only")
            assert q.fetchone()[0] == 'on'
            q.execute("SET LOCAL statement_timeout='0'")
            q.execute("SELECT max(kaisai_nen||kaisai_tsukihi) FROM public.brd_k3 WHERE kaisai_nen>='2017'")
            source_end = date.fromisoformat(q.fetchone()[0])
        with target.cursor() as q:
            q.execute("SHOW transaction_read_only")
            assert q.fetchone()[0] == 'on'
            q.execute("SET LOCAL statement_timeout='0'")
            q.execute("SELECT count(*),count(DISTINCT race_id) FROM core.race_entry e JOIN core.race r USING(race_id) WHERE r.race_date>%s", (source_end,))
            report['target_entries_beyond_source_end'], report['target_races_beyond_source_end'] = q.fetchone()
        report['source_end'] = source_end.isoformat()

        with source.cursor(name='k3_probe_source') as ks, target.cursor(name='k3_probe_target') as ct:
            ks.itersize = ct.itersize = 10000
            ks.execute("""SELECT kaisai_nen,kaisai_tsukihi,kyoteijo_code,race_no,
                       teiban,toroku_bango,chakujun,shinnyu_course,st
                       FROM public.brd_k3 WHERE kaisai_nen>='2017'
                       ORDER BY kaisai_nen,kaisai_tsukihi,kyoteijo_code,race_no,teiban""")
            ct.execute("""SELECT r.race_date,r.venue_code,r.race_no,e.boat_no,e.player_id,
                       z.finish_raw,z.finish_position,z.result_status,z.actual_course_raw,
                       z.actual_course,z.start_timing_raw,z.start_timing,
                       z.start_timing_status,z.normalization_status,z.source_record_id
                       FROM core.race_entry e JOIN core.race r USING(race_id)
                       LEFT JOIN core.race_result z USING(race_id,boat_no)
                       WHERE r.race_date BETWEEN %s AND %s
                       ORDER BY r.race_date,r.venue_code,r.race_no,e.boat_no""",
                       (START, source_end))
            src_iter, tgt_iter = iter(ks), iter(ct)
            src, tgt = next(src_iter, None), next(tgt_iter, None)
            last_source_race = last_canonical_race = None
            last_k3_without_result_race = last_canonical_without_k3_race = None
            while src is not None or tgt is not None:
                sk = source_key(src) if src is not None else None
                tk = target_key(tgt) if tgt is not None else None
                if src is not None and (tgt is None or sk < tk):
                    report['counts']['k3_rows'] += 1
                    report['counts']['k3_without_entry'] += 1
                    add_example(report, 'k3_without_entry', sk)
                    race_key = sk[:3]
                    if race_key != last_source_race:
                        report['counts']['k3_races'] += 1
                        last_source_race = race_key
                    src = next(src_iter, None)
                    continue
                if tgt is not None and (src is None or tk < sk):
                    report['counts']['canonical_entries'] += 1
                    report['counts']['entry_without_k3'] += 1
                    report['by_year'][tk[0][:4]]['entry_without_k3'] += 1
                    if tgt[14] is not None:
                        report['counts']['canonical_results'] += 1
                        report['counts']['canonical_result_without_k3'] += 1
                        report['by_year'][tk[0][:4]]['canonical_result_without_k3'] += 1
                        if tgt[6] is not None:
                            report['counts']['canonical_numeric_finish_without_k3'] += 1
                        if tk[:3] != last_canonical_without_k3_race:
                            report['counts']['canonical_result_races_without_k3'] += 1
                            last_canonical_without_k3_race = tk[:3]
                    add_example(report, 'entry_without_k3', tk)
                    race_key = tk[:3]
                    if race_key != last_canonical_race:
                        report['counts']['canonical_races'] += 1
                        last_canonical_race = race_key
                    tgt = next(tgt_iter, None)
                    continue
                report['counts']['k3_rows'] += 1
                report['counts']['canonical_entries'] += 1
                report['counts']['matched_keys'] += 1
                year = sk[0][:4]
                report['by_year'][year]['matched_keys'] += 1
                srace, trace = sk[:3], tk[:3]
                if srace != last_source_race:
                    report['counts']['k3_races'] += 1
                    last_source_race = srace
                if trace != last_canonical_race:
                    report['counts']['canonical_races'] += 1
                    last_canonical_race = trace
                if parsed_int(src[5], 1, 999999) != tgt[4]:
                    report['differences']['identity_mismatch'] += 1
                    add_example(report, 'identity_mismatch', [sk, src[5], tgt[4]])
                result = normalize_k3(src[6], src[7], src[8])
                if result['result_status'] == 'UNRESOLVED':
                    report['special_finish'][repr(src[6])] += 1
                if result['result_status'] == 'F':
                    report['counts']['k3_f_events'] += 1
                if result['result_status'] == 'L':
                    report['counts']['k3_l_events'] += 1
                if tgt[14] is None:
                    report['counts']['k3_without_canonical_result'] += 1
                    report['by_year'][year]['k3_without_canonical_result'] += 1
                    if result['finish_position'] is not None:
                        report['counts']['k3_new_numeric_finish'] += 1
                        report['by_year'][year]['k3_new_numeric_finish'] += 1
                    if result['actual_course'] is not None:
                        report['counts']['k3_new_actual_course'] += 1
                    if sk[:3] != last_k3_without_result_race:
                        report['counts']['k3_races_without_canonical_result'] += 1
                        last_k3_without_result_race = sk[:3]
                    add_example(report, 'k3_without_canonical_result', sk)
                else:
                    report['counts']['canonical_results'] += 1
                    report['counts']['compared_results'] += 1
                    stored = dict(zip(('finish_raw','finish_position','result_status',
                                       'actual_course_raw','actual_course','start_timing_raw',
                                       'start_timing','start_timing_status','normalization_status'), tgt[5:14]))
                    for field, new_value in result.items():
                        if stored[field] != new_value:
                            name = field + '_difference'
                            report['differences'][name] += 1
                            report['by_year'][year][name] += 1
                            add_example(report, name, [sk, new_value, stored[field]])
                    for field in ('finish_position','actual_course','start_timing'):
                        if (result[field] is None) != (stored[field] is None):
                            report['differences'][field + '_missingness_change'] += 1
                src = next(src_iter, None)
                tgt = next(tgt_iter, None)
        report['counts']['k3_boats'] = report['counts']['k3_rows']
        report['counts']['canonical_boats'] = report['counts']['canonical_entries']
        OUT.parent.mkdir(exist_ok=True)
        OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True,
                                  default=lambda x: str(x) if isinstance(x, Decimal) else dict(x)), encoding='utf-8')
        print(json.dumps({'output':str(OUT),'counts':report['counts'],
                          'differences':report['differences']}, ensure_ascii=False, default=dict))
    finally:
        source.rollback()
        target.rollback()
        source.close()
        target.close()


if __name__ == '__main__':
    main()
