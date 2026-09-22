"""Create the dedicated database and apply plain SQL, refusing existing objects."""
import argparse
import hashlib
import json
from pathlib import Path
import psycopg2
from scripts.db import DEFAULT_CONFIG, TARGET_DATABASE, settings, target_connection

MIGRATION = Path(__file__).resolve().parents[1] / 'sql/migrations/0001_initial_core.sql'

def migration_sql():
    return '\n'.join(p.read_text(encoding='utf-8') for p in sorted(MIGRATION.parent.glob('*.sql')))

def schema_signature(cursor):
    cursor.execute("""SELECT table_schema,table_name,column_name,data_type,is_nullable,
        column_default,is_identity FROM information_schema.columns
        WHERE table_schema IN ('raw','core') ORDER BY 1,2,ordinal_position""")
    columns = cursor.fetchall()
    cursor.execute("""SELECT n.nspname,c.relname,con.conname,pg_get_constraintdef(con.oid)
        FROM pg_constraint con JOIN pg_class c ON c.oid=con.conrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname IN ('raw','core')
        ORDER BY 1,2,3""")
    constraints = cursor.fetchall()
    cursor.execute("""SELECT n.nspname,c.relname,t.tgname,pg_get_triggerdef(t.oid)
        FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname IN ('raw','core') AND NOT t.tgisinternal ORDER BY 1,2,3""")
    triggers = cursor.fetchall()
    cursor.execute("""SELECT n.nspname,p.proname,pg_get_functiondef(p.oid)
        FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
        WHERE n.nspname IN ('raw','core') ORDER BY 1,2""")
    functions = cursor.fetchall()
    cursor.execute("""SELECT schemaname,tablename,indexname,indexdef FROM pg_indexes
        WHERE schemaname IN ('raw','core') ORDER BY 1,2,3""")
    return hashlib.sha256(json.dumps([columns,constraints,triggers,functions,cursor.fetchall()],
                                    sort_keys=True).encode()).hexdigest()

def migrate(config=DEFAULT_CONFIG):
    admin = psycopg2.connect(**settings(config), dbname='postgres', connect_timeout=5)
    admin.autocommit = True
    try:
        with admin.cursor() as cur:
            cur.execute("SELECT rolcreatedb,rolsuper FROM pg_roles WHERE rolname='itgakko'")
            if cur.fetchone() != (True, False):
                raise RuntimeError('expected existing non-superuser owner not available')
            cur.execute('SELECT 1 FROM pg_database WHERE datname=%s', (TARGET_DATABASE,))
            exists = cur.fetchone() is not None
            if not exists:
                cur.execute('SET ROLE itgakko')
                cur.execute('CREATE DATABASE boatrace_predictor OWNER itgakko TEMPLATE template0')
    finally:
        admin.close()
    conn = target_connection(config)
    try:
        with conn.cursor() as cur:
            cur.execute("""SELECT nspname FROM pg_namespace WHERE nspname NOT LIKE 'pg_%'
                AND nspname NOT IN ('public','information_schema')""")
            schemas = cur.fetchall()
            cur.execute("""SELECT n.nspname,c.relname FROM pg_class c
                JOIN pg_namespace n ON n.oid=c.relnamespace
                WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname <> 'information_schema'""")
            objects = cur.fetchall()
            cur.execute("""SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
                WHERE n.nspname NOT LIKE 'pg_%' AND n.nspname <> 'information_schema'""")
            routines = cur.fetchone()[0]
            if schemas or objects or routines:
                raise RuntimeError('BLOCKING: target is not empty; no migration applied')
            ddl = migration_sql()
            cur.execute(ddl)
            first = schema_signature(cur)
        # Verify a second application to the same empty database after rollback.
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute('SET ROLE itgakko')
            cur.execute(ddl)
            second = schema_signature(cur)
            if first != second:
                raise RuntimeError('schema reproduction failed')
            cur.execute("""SELECT count(*) FROM information_schema.tables
                WHERE table_schema IN ('raw','core') AND table_type='BASE TABLE'""")
            if cur.fetchone()[0] != 9:
                raise RuntimeError('expected exactly nine tables')
        conn.commit()
        return {'database_created': not exists, 'schema_reproduction': 'PASS',
                'schema_sha256': second, 'migration_sha256': hashlib.sha256(ddl.encode()).hexdigest()}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args()
    print(json.dumps(migrate(args.config), indent=2))
