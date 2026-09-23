"""Preserve K3 Raw and rebuild individual Canonical results from that source.

The raw and apply stages are separate. Apply is one transaction, requires the
direct-lookup gate, and fails before deleting any old result if keys differ.
"""

import argparse
import csv
from datetime import date, datetime, timezone, timedelta
import io
import json
from pathlib import Path

from scripts.db import source_connection, target_connection
from scripts.history_source import extract
from scripts.import_history import VERSION, preserve, stored
from scripts.import_sample import race_date
from scripts.normalize import normalize_result
from scripts.foundation import integer
from scripts.result_dataset_version import record_k3_result_dataset_version


SOURCE = 'brd_k3'
START = date(2017, 1, 1)
FIELDS = ('race_date','venue_code','race_no','boat_no','player_id',
          'actual_course_raw','actual_course','finish_raw','finish_position',
          'result_status','result_symbol_raw','start_timing_raw','start_timing',
          'start_timing_status','normalization_status','normalization_version',
          'source_record_id')


def months_through(last):
    current = START
    while current <= last:
        yield current.strftime('%Y-%m')
        current = (current.replace(day=28) + timedelta(days=4)).replace(day=1)


def raw_import(report):
    source = source_connection()
    target = target_connection()
    try:
        with source.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout='0'")
            cur.execute("SELECT max(kaisai_nen||kaisai_tsukihi),count(*) FROM public.brd_k3 WHERE kaisai_nen>='2017'")
            end, expected = cur.fetchone()
        if not end:
            raise RuntimeError('K3 source is empty')
        last = date.fromisoformat(end)
        total = 0
        report['source_end'] = last.isoformat()
        report['source_rows'] = expected
        for month in months_through(last):
            rows = extract(source, SOURCE, month)
            with target.cursor() as cur:
                batch, inserted, conflict = preserve(cur, SOURCE, month, rows,
                                                      datetime.now(timezone.utc))
            if conflict:
                target.rollback()
                raise RuntimeError('K3 raw source revision requires investigation: ' + month)
            target.commit()
            total += len(rows)
            report['raw_partitions'].append(dict(month=month, rows=len(rows),
                                                 batch_id=batch, inserted=inserted))
            print(json.dumps({'stage':'raw','month':month,'rows':len(rows)}), flush=True)
        if total != expected:
            raise RuntimeError('K3 partition count does not match source inventory')
        report['raw_rows'] = total
        return last
    finally:
        source.rollback()
        target.rollback()
        source.close()
        target.close()


def stage_month(cur, month):
    cur.execute('TRUNCATE k3_stage')
    records = stored(cur, SOURCE, month)
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator='\n')
    for source_id, row in records:
        day = race_date(row)
        venue = integer(row['kyoteijo_code'],1,24)
        race = integer(row['race_no'],1,12)
        boat = integer(row['teiban'],1,6)
        player = integer(row['toroku_bango'],1)
        if None in (venue,race,boat,player):
            raise RuntimeError('invalid mandatory K3 key in ' + month)
        result = normalize_result(row)
        data = dict(race_date=day,venue_code=venue,race_no=race,boat_no=boat,
                    player_id=player,source_record_id=source_id,**result)
        writer.writerow([r'\N' if data.get(field) is None else data[field] for field in FIELDS])
    buffer.seek(0)
    cur.copy_expert('COPY k3_stage ('+','.join(FIELDS)+
                    ") FROM STDIN WITH (FORMAT CSV, NULL '\\N')",buffer)
    cur.execute('SELECT count(*) FROM k3_stage')
    if cur.fetchone()[0] != len(records):
        raise RuntimeError('K3 staging count mismatch in ' + month)
    cur.execute('''SELECT count(*) FILTER (WHERE r.race_id IS NULL),
                          count(*) FILTER (WHERE e.player_id IS NULL),
                          count(*) FILTER (WHERE e.player_id IS NOT NULL
                                            AND e.player_id<>s.player_id)
                   FROM k3_stage s
                   LEFT JOIN core.race r USING(race_date,venue_code,race_no)
                   LEFT JOIN core.race_entry e ON e.race_id=r.race_id AND e.boat_no=s.boat_no''')
    failures = cur.fetchone()
    if any(failures):
        raise RuntimeError('K3 race/boat/player mapping failure '+month+': '+str(failures))
    return len(records)


def old_only(cur, month):
    cur.execute('''SELECT r.race_date,r.venue_code,r.race_no,z.boat_no
                   FROM core.race_result z JOIN core.race r USING(race_id)
                   LEFT JOIN k3_stage s ON s.race_date=r.race_date
                        AND s.venue_code=r.venue_code AND s.race_no=r.race_no
                        AND s.boat_no=z.boat_no
                   WHERE to_char(r.race_date,'YYYY-MM')=%s
                     AND s.source_record_id IS NULL
                   ORDER BY r.race_date,r.venue_code,r.race_no,z.boat_no''',(month,))
    return cur.fetchall()


def apply(gate, raw_report, report):
    if gate.get('candidate_races') != 60 or gate.get('candidate_boats') != 360 \
            or gate.get('k3_absent') != 60 or gate.get('k3_present_probe_bug') != 0:
        raise RuntimeError('direct K3 lookup gate is not clear')
    permitted = {(date.fromisoformat(r['date']),r['venue'],r['race_no'],b['boat_no'])
                 for r in gate['races'] for b in r['canonical_boats']}
    if len(permitted) != 360:
        raise RuntimeError('direct lookup gate has duplicate or missing boats')
    if raw_report.get('status') != 'RAW_COMPLETE' or \
            raw_report.get('raw_rows') != raw_report.get('source_rows'):
        raise RuntimeError('complete K3 Raw acquisition report is required')
    target = target_connection()
    try:
        with target.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout='0'")
            cur.execute("SELECT pg_try_advisory_xact_lock(hashtext('k3-only-result-migration-v1'))")
            if not cur.fetchone()[0]:
                raise RuntimeError('K3 migration is already running')
            cur.execute('''CREATE TEMP TABLE k3_stage (
                race_date date NOT NULL, venue_code smallint NOT NULL,
                race_no smallint NOT NULL, boat_no smallint NOT NULL,
                player_id integer NOT NULL, actual_course_raw text,
                actual_course smallint, finish_raw text, finish_position smallint,
                result_status text NOT NULL, result_symbol_raw text,
                start_timing_raw text, start_timing numeric(6,3),
                start_timing_status text NOT NULL, normalization_status text NOT NULL,
                normalization_version text NOT NULL, source_record_id bigint NOT NULL,
                PRIMARY KEY (race_date,venue_code,race_no,boat_no)) ON COMMIT DROP''')
            cur.execute("SELECT max((s.raw_payload->>'kaisai_nen')||(s.raw_payload->>'kaisai_tsukihi')) FROM raw.source_record s JOIN raw.source_batch b USING(source_batch_id) WHERE b.source_table=%s AND b.extraction_condition->>'partition'>='2017-01'",(SOURCE,))
            last = date.fromisoformat(cur.fetchone()[0])
            if last.isoformat() != raw_report['source_end']:
                raise RuntimeError('K3 Raw endpoint differs from completed acquisition')
            all_old_only = []
            staged = 0
            # First pass validates all source keys before any Canonical write.
            for month in months_through(last):
                staged += stage_month(cur,month)
                all_old_only.extend(old_only(cur,month))
                print(json.dumps({'stage':'validate','month':month}),flush=True)
            actual = set(all_old_only)
            if actual != permitted:
                raise RuntimeError('old-only Canonical keys differ from the direct lookup gate: '
                                   +str((len(actual),len(permitted),len(actual-permitted),len(permitted-actual))))
            report['old_only_boats'] = len(actual)
            report['staged_rows'] = staged
            if staged != raw_report['raw_rows']:
                raise RuntimeError('staged K3 rows differ from complete Raw acquisition')
            # The second pass adopts only the validated, preserved K3 records.
            inserted_or_updated = 0
            for month in months_through(last):
                rows = stage_month(cur,month)
                cur.execute('''INSERT INTO core.race_result
                    (race_id,boat_no,actual_course_raw,actual_course,finish_raw,
                     finish_position,result_status,result_symbol_raw,start_timing_raw,
                     start_timing,start_timing_status,normalization_status,
                     normalization_version,source_record_id,provenance)
                    SELECT r.race_id,s.boat_no,s.actual_course_raw,s.actual_course,
                           s.finish_raw,s.finish_position,s.result_status,
                           s.result_symbol_raw,s.start_timing_raw,s.start_timing,
                           s.start_timing_status,s.normalization_status,
                           s.normalization_version,s.source_record_id,
                           jsonb_build_object('source','brd_k3',
                                              'normalization_version',s.normalization_version,
                                              'actual_course_field','shinnyu_course',
                                              'start_timing_field','st')
                    FROM k3_stage s JOIN core.race r USING(race_date,venue_code,race_no)
                    ON CONFLICT (race_id,boat_no) DO UPDATE SET
                    actual_course_raw=EXCLUDED.actual_course_raw,
                    actual_course=EXCLUDED.actual_course,finish_raw=EXCLUDED.finish_raw,
                    finish_position=EXCLUDED.finish_position,result_status=EXCLUDED.result_status,
                    result_symbol_raw=EXCLUDED.result_symbol_raw,
                    start_timing_raw=EXCLUDED.start_timing_raw,start_timing=EXCLUDED.start_timing,
                    start_timing_status=EXCLUDED.start_timing_status,
                    normalization_status=EXCLUDED.normalization_status,
                    normalization_version=EXCLUDED.normalization_version,
                    source_record_id=EXCLUDED.source_record_id,provenance=EXCLUDED.provenance''')
                inserted_or_updated += cur.rowcount
                cur.execute('''DELETE FROM core.race_result z USING core.race r
                    WHERE z.race_id=r.race_id AND to_char(r.race_date,'YYYY-MM')=%s
                      AND NOT EXISTS (SELECT 1 FROM k3_stage s
                          WHERE s.race_date=r.race_date AND s.venue_code=r.venue_code
                            AND s.race_no=r.race_no AND s.boat_no=z.boat_no)''',(month,))
                report['deleted_old_only'] = report.get('deleted_old_only',0) + cur.rowcount
                cur.execute('''UPDATE core.race r SET race_status=CASE WHEN
                    (SELECT count(*) FROM core.race_entry e WHERE e.race_id=r.race_id)=6
                    AND (SELECT count(*) FROM core.race_result z WHERE z.race_id=r.race_id)=6
                    THEN 'RESULT_RECORDS_PRESENT' ELSE 'SOURCE_INCOMPLETE' END
                    WHERE to_char(r.race_date,'YYYY-MM')=%s''',(month,))
                print(json.dumps({'stage':'canonical','month':month,'rows':rows}),flush=True)
            if inserted_or_updated != staged or report['deleted_old_only'] != 360:
                raise RuntimeError('adopted/deleted result counts failed')
            cur.execute('DROP VIEW core.boat_finish_state')
            cur.execute('DROP VIEW core.race_result_state')
            cur.execute('DROP VIEW core.result_source_evidence')
            ddl = Path(__file__).resolve().parents[1] / 'sql/migrations/0004_result_states.sql'
            cur.execute(ddl.read_text(encoding='utf-8-sig'))
            version_ddl = (Path(__file__).resolve().parents[1] /
                           'sql/migrations/0007_k3_result_dataset_version.sql')
            cur.execute("SELECT to_regclass('core.result_dataset_version')")
            if cur.fetchone()[0] is None:
                cur.execute(version_ddl.read_text(encoding='utf-8-sig'))
            cur.execute('''SELECT count(*),count(DISTINCT race_id),
                     count(*) FILTER (WHERE b.source_table<>'brd_k3')
                     FROM core.race_result z JOIN raw.source_record s USING(source_record_id)
                     JOIN raw.source_batch b USING(source_batch_id)''')
            total, races, foreign = cur.fetchone()
            if total != staged or foreign:
                raise RuntimeError('Canonical K3 lineage/count failure '+str((total,races,foreign)))
            version = record_k3_result_dataset_version(
                cur,date_start=START,date_end=last,extraction_version=VERSION)
            report.update(result_boats=total,result_races=races,source_end=last.isoformat(),
                          version_id=version['version_id'],
                          source_manifest_hash=version['source_manifest_hash'],status='APPLIED')
        target.commit()
        return report
    except Exception:
        target.rollback()
        raise
    finally:
        target.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage',choices=('raw','apply'),required=True)
    parser.add_argument('--gate-report',type=Path)
    parser.add_argument('--raw-report',type=Path)
    parser.add_argument('--report',type=Path,required=True)
    args = parser.parse_args()
    report = dict(version='k3-only-result-migration-v1',raw_partitions=[])
    if args.stage == 'raw':
        raw_import(report)
        report['status'] = 'RAW_COMPLETE'
    else:
        if args.gate_report is None or args.raw_report is None:
            parser.error('--gate-report and --raw-report are required for apply')
        gate = json.loads(args.gate_report.read_text(encoding='utf-8'))
        raw_report = json.loads(args.raw_report.read_text(encoding='utf-8'))
        apply(gate,raw_report,report)
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='raw_partitions'}))


if __name__ == '__main__':
    main()
