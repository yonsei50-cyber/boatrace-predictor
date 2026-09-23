"""Read-only input extraction smoke test for frozen methods, before 2025."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from scripts.compare_rating_methods import EXTRACT_SQL as RATING_SQL
from scripts.evaluate_entry_course_index_v1_holdout_2025 import DEVELOPMENT_SQL as ENTRY_SQL
from scripts.db import target_connection


MOTOR_SQL = """
SELECT r.race_date,r.venue_code,r.race_no,e.boat_no,e.player_id,
       m.generation_start_year,m.motor_no,e.national_win_rate_status,
       e.national_win_rate,b.finish_state,b.finish_position,
       z.race_id IS NOT NULL AS has_canonical_result,s.result_state,
       src.source_table AS result_source
FROM core.race r JOIN core.race_entry e USING(race_id)
LEFT JOIN core.motor m ON m.motor_id=e.motor_id
LEFT JOIN core.boat_finish_state b USING(race_id,boat_no)
LEFT JOIN core.race_result z USING(race_id,boat_no)
LEFT JOIN raw.source_record rec ON rec.source_record_id=z.source_record_id
LEFT JOIN raw.source_batch src ON src.source_batch_id=rec.source_batch_id
LEFT JOIN core.race_result_state s USING(race_id)
WHERE r.race_date >= DATE '2017-01-01' AND r.race_date < DATE '2025-01-01'
LIMIT 6
"""


def smoke():
    conn=target_connection()
    conn.commit()
    conn.set_session(readonly=True,isolation_level='REPEATABLE READ')
    try:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout='0'")
            out={}
            for name,query in (('rating',RATING_SQL),('entry_course',ENTRY_SQL)):
                bounded=query.rsplit('ORDER BY',1)[0] + ' LIMIT 6'
                cur.execute(bounded)
                result=cur.fetchall()
                if len(result)!=6:
                    raise RuntimeError(name+' input extract returned fewer than six rows')
                out[name]=dict(rows=len(result),columns=[x[0] for x in cur.description])
            cur.execute(MOTOR_SQL)
            result=cur.fetchall()
            if len(result)!=6:
                raise RuntimeError('motor input extract returned fewer than six rows')
            out['motor_a']=dict(rows=len(result),columns=[x[0] for x in cur.description])
            cur.execute('''SELECT count(*) FILTER (WHERE b.source_table<>'brd_k3'),count(*)
                           FROM core.race_result z JOIN core.race r USING(race_id)
                           JOIN raw.source_record s ON s.source_record_id=z.source_record_id
                           JOIN raw.source_batch b USING(source_batch_id)
                           WHERE r.race_date<DATE '2025-01-01' ''')
            foreign,total=cur.fetchone()
            if foreign or total==0:
                raise RuntimeError('pre-2025 result input lineage is not K3-only')
            out['pre_2025_result_boats']=total
            out['pre_2025_foreign_result_boats']=foreign
            return dict(status='PASS',generated_at=datetime.now(timezone.utc).isoformat(),
                        holdout_evaluated=False,inputs=out)
    finally:
        conn.rollback();conn.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args()
    result=smoke()
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'status':result['status'],'inputs':result['inputs']},ensure_ascii=False))


if __name__=='__main__':
    main()
