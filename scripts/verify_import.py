"""Replay the sample and inject a failed source recheck in disposable databases."""
from contextlib import contextmanager
from copy import deepcopy
import json
from unittest.mock import patch
from uuid import uuid4
import psycopg2
from psycopg2 import sql
from scripts.db import settings, target_connection
from scripts.import_sample import extract_source, import_sample
from scripts.migrate import migration_sql

@contextmanager
def disposable_database():
    name='boatrace_phase2_replay_'+uuid4().hex[:12]
    admin=psycopg2.connect(**settings(),dbname='postgres',connect_timeout=5)
    admin.autocommit=True
    created=False
    def connect(*_):
        conn=psycopg2.connect(**settings(),dbname=name,connect_timeout=5)
        with conn.cursor() as cur:
            cur.execute('SET ROLE itgakko')
            cur.execute('SELECT current_database(),current_user')
            if cur.fetchone() != (name,'itgakko'):
                conn.close()
                raise RuntimeError('unexpected verification database')
        return conn
    try:
        with admin.cursor() as cur:
            cur.execute('SET ROLE itgakko')
            cur.execute(sql.SQL('CREATE DATABASE {} OWNER itgakko TEMPLATE template0').format(sql.Identifier(name)))
            created=True
        conn=connect()
        try:
            with conn.cursor() as cur:
                cur.execute(migration_sql())
            conn.commit()
        finally:
            conn.close()
        yield connect
    finally:
        if created:
            with admin.cursor() as cur:
                cur.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))
        admin.close()

def datasets(connect):
    conn=connect()
    try:
        with conn.cursor() as cur:
            cur.execute('''SELECT effective_date,canonical_content_hash,manifest_hash,
                canonical_snapshot,source_manifest FROM core.dataset_version ORDER BY effective_date''')
            return cur.fetchall()
    finally:
        conn.rollback();conn.close()

def verify_import():
    expected=datasets(target_connection)
    with disposable_database() as connect:
        with patch('scripts.import_sample.target_connection',connect):
            import_sample()
        actual=datasets(connect)
        if actual != expected:
            raise RuntimeError('sample replay differs from frozen target datasets')
    # Fault injection is a deterministic transaction test, not a real source change.
    original=extract_source()
    changed=deepcopy(original)
    changed[0]['brd_r3'][0]['st']='FAULT_INJECTION'
    with disposable_database() as connect:
        with patch('scripts.import_sample.target_connection',connect), patch(
                'scripts.import_sample.extract_source',side_effect=[original,changed]):
            try:
                import_sample()
            except RuntimeError as exc:
                if 'sampled source changed' not in str(exc):
                    raise
            else:
                raise RuntimeError('injected source change was not rejected')
        conn=connect()
        try:
            with conn.cursor() as cur:
                for table in ('raw.source_batch','raw.source_record','core.venue','core.race',
                              'core.player','core.motor','core.race_entry','core.race_result','core.dataset_version'):
                    cur.execute('SELECT count(*) FROM '+table)
                    if cur.fetchone()[0] != 0:
                        raise RuntimeError('partial import escaped rollback')
        finally:
            conn.rollback();conn.close()
    return {'real_source_replay':'PASS','frozen_dataset_content_and_manifest_equal':True,
            'injected_source_change_full_rollback':'PASS','temporary_databases_removed':True}

if __name__=='__main__':
    print(json.dumps(verify_import(),indent=2))
