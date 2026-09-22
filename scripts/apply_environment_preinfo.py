"""Apply only Phase 3C and backfill preserved C2/C3 in bounded transactions."""
import argparse
import json
from pathlib import Path
from scripts.db import target_connection
from scripts.import_environment_preinfo import VERSION

MIGRATION = Path(__file__).resolve().parents[1]/'sql/migrations/0005_environment_preinfo.sql'


def protected_state():
    conn = target_connection()
    try:
        conn.commit(); conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
        result = {}
        with conn.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout='600s'")
            for table, order in (
                ('venue','venue_code'),('player','player_id'),('motor','motor_id'),
                ('race','race_id'),('race_entry','race_id,boat_no'),('race_result','race_id,boat_no')):
                cur.execute('SELECT count(*),md5(string_agg(md5(to_jsonb(t)::text),\'\' ORDER BY '+order+')) FROM core.'+table+' t')
                result[table] = list(cur.fetchone())
            cur.execute('SELECT dataset_version_id,canonical_content_hash,manifest_hash,effective_date,results_cutoff_date '
                        'FROM core.dataset_version ORDER BY dataset_version_id')
            result['datasets'] = [list(r) for r in cur.fetchall()]
        return result
    finally:
        conn.rollback(); conn.close()


def apply():
    conn = target_connection()
    result = {'migration':MIGRATION.name, 'batches':[]}
    try:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout='600s'")
            # Canonical writers serialize with each other. Immutable Raw batch
            # acquisition uses a separate lock and commits before selection.
            cur.execute('SELECT pg_advisory_xact_lock(330017005)')
            cur.execute(MIGRATION.read_text(encoding='utf-8'))
        conn.commit()
        with conn.cursor() as cur:
            cur.execute('SELECT source_batch_id,source_table FROM raw.source_batch '
                        "WHERE extraction_condition->>'version'=%s ORDER BY source_batch_id",(VERSION,))
            batches = cur.fetchall()
        for batch, table in batches:
            function = {'brd_c2':'backfill_race_environment_preinfo_v1',
                        'brd_c3':'backfill_race_boat_preinfo_v1'}[table]
            with conn.cursor() as cur:
                cur.execute("SET LOCAL statement_timeout='600s'")
                cur.execute('SELECT pg_advisory_xact_lock(330017005)')
                cur.execute('SELECT core.'+function+'(%s)',(batch,))
                added = cur.fetchone()[0]
            conn.commit()
            item = dict(batch=batch,table=table,inserted=added)
            result['batches'].append(item)
            print(json.dumps(item),flush=True)
        result['inserted'] = sum(b['inserted'] for b in result['batches'])
        return result
    finally:
        conn.rollback(); conn.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fingerprint-only',action='store_true')
    parser.add_argument('--report',type=Path,required=True)
    args = parser.parse_args()
    result = protected_state() if args.fingerprint_only else apply()
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(result,indent=2,default=str)+'\n',encoding='utf-8')
