"""Reproduce all migrations in a newly-created disposable empty database."""
import json
from uuid import uuid4
import psycopg2
from psycopg2 import sql
from scripts.db import settings, target_connection
from scripts.migrate import migration_sql, schema_signature

def verify_schema():
    database='boatrace_phase2_verify_'+uuid4().hex[:12]
    admin=psycopg2.connect(**settings(),dbname='postgres',connect_timeout=5)
    admin.autocommit=True
    created=False
    scratch=None
    try:
        with admin.cursor() as cur:
            cur.execute('SET ROLE itgakko')
            # No IF EXISTS, no reuse: only the database created by this call is removed.
            cur.execute(sql.SQL('CREATE DATABASE {} OWNER itgakko TEMPLATE template0').format(sql.Identifier(database)))
            created=True
        scratch=psycopg2.connect(**settings(),dbname=database,connect_timeout=5)
        signatures=[]
        for _ in range(2):
            with scratch.cursor() as cur:
                cur.execute('SET ROLE itgakko')
                cur.execute(migration_sql())
                signatures.append(schema_signature(cur))
            scratch.rollback()
        target=target_connection()
        try:
            with target.cursor() as cur:
                signatures.append(schema_signature(cur))
        finally:
            target.rollback();target.close()
        if len(set(signatures)) != 1:
            raise RuntimeError('schema reproduction mismatch')
        return {'empty_database_reproduction':'PASS','target_schema_sha256':signatures[0]}
    finally:
        if scratch is not None:
            scratch.close()
        if created:
            with admin.cursor() as cur:
                cur.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(database)))
        admin.close()

if __name__=='__main__':
    print(json.dumps(verify_schema(),indent=2))
