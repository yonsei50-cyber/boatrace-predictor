"""Build a separate empty database and compare its K3-only result counts.

The temporary database is created with a random dedicated name. A successful
comparison removes only that database; a failure leaves it for diagnosis.
"""

import argparse
import json
from pathlib import Path
import secrets

import psycopg2
from psycopg2 import sql

from scripts import import_history, import_result_evidence
from scripts.db import DEFAULT_CONFIG, TARGET_DATABASE, settings, target_connection
from scripts.migrate import migration_sql


def counts(database, config):
    conn = target_connection(config, database=database)
    conn.commit()
    conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
    try:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout='0'")
            cur.execute('''SELECT (SELECT count(*) FROM core.race),
                       (SELECT count(DISTINCT race_id) FROM core.race_result),
                       count(*),
                       count(*) FILTER (WHERE result_status='F'),
                       count(*) FILTER (WHERE result_status='L'),
                       count(*) FILTER (WHERE finish_position IS NOT NULL),
                       count(*) FILTER (WHERE finish_position IS NULL
                                         AND result_status NOT IN ('F','L')),
                       count(*) FILTER (WHERE actual_course IS NOT NULL),
                       count(*) FILTER (WHERE start_timing IS NOT NULL)
                       FROM core.race_result''')
            keys = ('races','result_races','result_boats','f','l','numeric_finish',
                    'special_unresolved','actual_course_valid','start_timing_valid')
            values = dict(zip(keys,cur.fetchone()))
            cur.execute('''SELECT version_id,authoritative_source,date_start,date_end,
                                  source_manifest_hash,normalization_version,
                                  result_races,result_boats
                           FROM core.result_dataset_version ORDER BY created_at DESC LIMIT 1''')
            version = cur.fetchone()
            if version is None:
                raise RuntimeError('result dataset version is absent')
            values['version'] = [str(x) for x in version]
            cur.execute('''SELECT result_state,count(*) FROM core.race_result_state
                           GROUP BY result_state ORDER BY result_state''')
            values['result_states'] = {name:total for name,total in cur}
            return values
    finally:
        conn.rollback()
        conn.close()


def create_empty(config):
    database = 'boatrace_k3_verify_' + secrets.token_hex(4)
    admin = psycopg2.connect(**settings(config),dbname='postgres',connect_timeout=5)
    admin.autocommit = True
    try:
        with admin.cursor() as cur:
            cur.execute('SELECT 1 FROM pg_database WHERE datname=%s',(database,))
            if cur.fetchone():
                raise RuntimeError('random verification database name already exists')
            cur.execute(sql.SQL('CREATE DATABASE {} OWNER itgakko TEMPLATE template0').format(
                sql.Identifier(database)))
    finally:
        admin.close()
    try:
        conn = target_connection(config,database=database)
        try:
            with conn.cursor() as cur:
                cur.execute(migration_sql())
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    except Exception:
        drop_owned(database,config)
        raise
    return database


def drop_owned(database,config):
    if not database.startswith('boatrace_k3_verify_') or len(database) != 27:
        raise RuntimeError('refusing to remove an unexpected database name')
    admin=psycopg2.connect(**settings(config),dbname='postgres',connect_timeout=5)
    admin.autocommit=True
    try:
        with admin.cursor() as cur:
            cur.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(database)))
    finally:
        admin.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=DEFAULT_CONFIG)
    parser.add_argument('--report',type=Path,required=True)
    parser.add_argument('--keep-db',action='store_true')
    args=parser.parse_args()
    args.report.parent.mkdir(parents=True,exist_ok=True)
    report=dict(status='RUNNING',database=None)
    try:
        report['live_before']=counts(TARGET_DATABASE,args.config)
        database=create_empty(args.config)
        report['database']=database
        original=import_history.target_connection
        import_history.target_connection=lambda: target_connection(args.config,database=database)
        try:
            raw=import_history.run(raw_only=True)
            raw_path=args.report.with_name(args.report.stem+'_raw.json')
            raw_path.write_text(json.dumps(raw,ensure_ascii=False,indent=2,default=str),
                                encoding='utf-8')
            if raw['status']!='RAW_COMPLETE':
                raise RuntimeError('empty database raw import incomplete')
            canonical=import_history.run(canonical_only=True,inventory_path=raw_path)
            if canonical['status']!='CANONICAL_COMPLETE':
                raise RuntimeError('empty database canonical import incomplete')
        finally:
            import_history.target_connection=original
        original_r2=import_result_evidence.target_connection
        import_result_evidence.target_connection=lambda: target_connection(args.config,database=database)
        try:
            r2=import_result_evidence.run()
            report['r2_raw_rows']=r2['total_rows']
        finally:
            import_result_evidence.target_connection=original_r2
        report['empty']=counts(database,args.config)
        report['live_after']=counts(TARGET_DATABASE,args.config)
        report['match']=report['live_before']==report['live_after']==report['empty']
        if not report['match']:
            raise RuntimeError('empty database K3-only counts/version differ')
        report['status']='PASS'
        if not args.keep_db:
            drop_owned(database,args.config)
            report['database_removed']=True
    except Exception as exc:
        report['status']='BLOCKED'
        report['error_type']=type(exc).__name__
        report['error']=str(exc)
        raise
    finally:
        args.report.write_text(json.dumps(report,ensure_ascii=False,indent=2,default=str),
                               encoding='utf-8')
        print(json.dumps({k:v for k,v in report.items()
                          if k not in ('live_before','live_after','empty')},
                         ensure_ascii=False))


if __name__=='__main__':
    main()
