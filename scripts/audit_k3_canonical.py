"""Read-only K3-only Canonical result and lineage audit."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from scripts.db import target_connection


def audit():
    conn = target_connection()
    conn.commit()
    conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
    try:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout='0'")
            cur.execute('SHOW transaction_read_only')
            assert cur.fetchone()[0] == 'on'
            cur.execute('''SELECT count(*) AS result_boats,count(DISTINCT z.race_id) AS result_races,
                  count(*) FILTER (WHERE z.boat_no NOT BETWEEN 1 AND 6) AS bad_boat,
                  count(*) FILTER (WHERE z.race_id IS NULL OR z.source_record_id IS NULL
                                    OR e.player_id IS NULL) AS mandatory_null,
                  count(*) FILTER (WHERE b.source_table IS DISTINCT FROM 'brd_k3') AS wrong_source,
                  count(*) FILTER (WHERE z.result_symbol_raw IS NOT NULL) AS invented_symbol,
                  count(*) FILTER (WHERE z.finish_position IS NOT NULL) AS numeric_finish,
                  count(*) FILTER (WHERE z.result_status='F') AS f_results,
                  count(*) FILTER (WHERE z.result_status='L') AS l_results,
                  count(*) FILTER (WHERE z.result_status='UNRESOLVED') AS special_unresolved,
                  count(*) FILTER (WHERE z.actual_course IS NOT NULL) AS valid_actual_course,
                  count(*) FILTER (WHERE z.start_timing IS NOT NULL) AS valid_start_timing,
                  count(*) FILTER (WHERE z.start_timing_status IN ('F','L')
                                    AND z.start_timing IS NOT NULL) AS numeric_fl,
                  count(*) FILTER (WHERE z.finish_raw IS DISTINCT FROM s.raw_payload->>'chakujun'
                                    OR z.actual_course_raw IS DISTINCT FROM s.raw_payload->>'shinnyu_course'
                                    OR z.start_timing_raw IS DISTINCT FROM s.raw_payload->>'st')
                      AS raw_field_mismatch,
                  count(*) FILTER (WHERE e.player_id::text IS DISTINCT FROM
                                    (s.raw_payload->>'toroku_bango')::integer::text)
                      AS player_mismatch,
                  count(*) FILTER (WHERE z.boat_no::text IS DISTINCT FROM s.raw_payload->>'teiban'
                                    OR to_char(r.race_date,'YYYY') IS DISTINCT FROM s.raw_payload->>'kaisai_nen'
                                    OR to_char(r.race_date,'MMDD') IS DISTINCT FROM s.raw_payload->>'kaisai_tsukihi'
                                    OR lpad(r.venue_code::text,2,'0') IS DISTINCT FROM s.raw_payload->>'kyoteijo_code'
                                    OR lpad(r.race_no::text,2,'0') IS DISTINCT FROM s.raw_payload->>'race_no')
                      AS key_mismatch
                FROM core.race_result z
                JOIN core.race r USING(race_id)
                JOIN core.race_entry e USING(race_id,boat_no)
                JOIN raw.source_record s ON s.source_record_id=z.source_record_id
                JOIN raw.source_batch b USING(source_batch_id)''')
            columns = [x[0] for x in cur.description]
            totals = dict(zip(columns,cur.fetchone()))
            cur.execute('''SELECT count(*) AS non_six_result_races
                           FROM (SELECT race_id,count(*) AS n FROM core.race_result
                                 GROUP BY race_id HAVING count(*)<>6) x''')
            totals['non_six_result_races'] = cur.fetchone()[0]
            cur.execute('''SELECT count(*) FROM
                (SELECT race_id,boat_no,count(*) FROM core.race_result
                 GROUP BY race_id,boat_no HAVING count(*)>1) x''')
            totals['duplicate_result_key'] = cur.fetchone()[0]
            cur.execute('''SELECT finish_raw,result_status,count(*) FROM core.race_result
                           WHERE finish_position IS NULL GROUP BY 1,2 ORDER BY 1,2''')
            special_codes = [dict(finish_raw=raw,status=status,boats=n)
                             for raw,status,n in cur]
            cur.execute('''SELECT version_id,authoritative_source,date_start,date_end,
                                  source_manifest_hash,result_races,result_boats
                           FROM core.result_dataset_version ORDER BY created_at DESC LIMIT 1''')
            version_row = cur.fetchone()
            version = dict(zip([x[0] for x in cur.description],version_row)) if version_row else None
            cur.execute('''SELECT count(*),count(DISTINCT (s.raw_payload->>'kaisai_nen',
                                  s.raw_payload->>'kaisai_tsukihi',
                                  s.raw_payload->>'kyoteijo_code',
                                  s.raw_payload->>'race_no'))
                           FROM raw.source_record s JOIN raw.source_batch b USING(source_batch_id)
                           WHERE b.source_table='brd_k3'
                             AND b.extraction_condition->>'partition'>='2017-01' ''')
            raw_boats,raw_races = cur.fetchone()
            totals['k3_raw_boats'] = raw_boats
            totals['k3_raw_races'] = raw_races
            blocked = [name for name in ('bad_boat','mandatory_null','wrong_source',
                'invented_symbol','numeric_fl','raw_field_mismatch','player_mismatch',
                'key_mismatch','non_six_result_races','duplicate_result_key') if totals[name]]
            if raw_boats != totals['result_boats'] or raw_races != totals['result_races']:
                blocked.append('raw_canonical_count')
            if version is None or version['authoritative_source'] != 'brd_k3' \
                    or version['result_boats'] != totals['result_boats'] \
                    or version['result_races'] != totals['result_races']:
                blocked.append('dataset_version')
            return dict(generated_at=datetime.now(timezone.utc).isoformat(),
                        status='PASS' if not blocked else 'BLOCKED',
                        blocked=blocked,totals=totals,special_codes=special_codes,
                        result_dataset_version=version)
    finally:
        conn.rollback()
        conn.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args()
    result=audit()
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),
                           encoding='utf-8')
    print(json.dumps({'status':result['status'],'blocked':result['blocked'],
                      'totals':result['totals']},default=str))
    if result['status']!='PASS':
        raise RuntimeError('K3 Canonical audit blocked')


if __name__=='__main__':
    main()
