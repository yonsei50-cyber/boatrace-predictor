"""Local connection settings read in memory; never log credentials or DSNs."""
from pathlib import Path
import xml.etree.ElementTree as ET
import psycopg2

TARGET_DATABASE = 'boatrace_predictor'
TARGET_ROLE = 'itgakko'
DEFAULT_CONFIG = Path.home() / 'AppData/Roaming/PC-KYOTEI Database/AppConfig.xml'

def settings(config=DEFAULT_CONFIG):
    values = {x.tag: x.text for x in ET.parse(config).getroot().iter()}
    if values['DbServer'] not in ('localhost', '127.0.0.1', '::1'):
        raise ValueError('local PostgreSQL required')
    return dict(host=values['DbServer'], port=values['DbPort'],
                user=values['DbUserId'], password=values['DbPassword'])

def source_connection(config=DEFAULT_CONFIG):
    connection = psycopg2.connect(**settings(config), dbname='pckyotei',
        connect_timeout=5, application_name='boatrace_phase2_source_readonly',
        options='-c default_transaction_read_only=on -c statement_timeout=15000 -c lock_timeout=1500')
    connection.set_session(readonly=True, isolation_level='REPEATABLE READ')
    with connection.cursor() as cursor:
        cursor.execute("SELECT current_setting('transaction_read_only')")
        if cursor.fetchone()[0] != 'on':
            connection.close()
            raise RuntimeError('source must be read-only')
    return connection

def target_connection(config=DEFAULT_CONFIG, database=TARGET_DATABASE):
    connection = psycopg2.connect(**settings(config), dbname=database,
        connect_timeout=5, application_name='boatrace_phase2_target',
        options='-c statement_timeout=30000 -c lock_timeout=2000')
    with connection.cursor() as cursor:
        cursor.execute('SET ROLE itgakko')
        cursor.execute('SELECT current_database(),current_user')
        if cursor.fetchone() != (database, TARGET_ROLE):
            raise RuntimeError('unexpected target identity')
    return connection
