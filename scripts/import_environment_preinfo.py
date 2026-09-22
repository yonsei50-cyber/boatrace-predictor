"""Preserve C2/C3 monthly observations, without reading results or importing C4."""
import argparse
import csv
from datetime import date, datetime, timezone
import io
import json
from pathlib import Path
from psycopg2.extras import Json, RealDictCursor
from scripts.db import source_connection, target_connection
from scripts.foundation import canonical_json, digest
from scripts.import_sample import RACE_KEY, insert

VERSION = 'phase3c-environment-preinfo-v1'
TABLES = ('brd_c2', 'brd_c3')


def preserve(cur, table, partition, rows, extracted_at):
    if table not in TABLES:
        raise ValueError('only C2/C3 are authorized')
    if len(partition) != 7 or date.fromisoformat(partition+'-01') < date(2017, 1, 1):
        raise ValueError('C2/C3 scope starts 2017-01-01')
    fields = RACE_KEY + (('teiban',) if table == 'brd_c3' else ())
    keys = [tuple(r[k] for k in fields) for r in rows]
    if len(keys) != len(set(keys)):
        raise ValueError('duplicate source key')
    if keys != sorted(keys) or any(r['kaisai_nen']+'-'+r['kaisai_tsukihi'][:2] != partition for r in rows):
        raise ValueError('source partition/order mismatch')
    for row in rows:
        day = date(int(row['kaisai_nen']), int(row['kaisai_tsukihi'][:2]), int(row['kaisai_tsukihi'][2:]))
        if day.strftime('%Y%m%d') != row['kaisai_nen']+row['kaisai_tsukihi']:
            raise ValueError('invalid source date')
        if not 1 <= int(row['kyoteijo_code']) <= 24 or not 1 <= int(row['race_no']) <= 12:
            raise ValueError('invalid race identity')
        if table == 'brd_c3' and row['teiban'] not in tuple('123456'):
            raise ValueError('invalid boat identity')
    condition = dict(version=VERSION, partition=partition, order_by=list(fields))
    hashed = digest(rows)
    cur.execute('SELECT source_batch_id,content_hash FROM raw.source_batch '
                'WHERE source_table=%s AND extraction_condition=%s ORDER BY source_batch_id',
                (table, Json(condition)))
    prior = cur.fetchall()
    if prior:
        if len(prior) != 1 or prior[0][1] != hashed:
            raise RuntimeError('partition changed or ambiguous; automatic adoption blocked')
        return prior[0][0], False
    batch = insert(cur, 'raw.source_batch', dict(source_name='PC-KYOTEI',
        source_type='SOURCE_DB_EXTRACT', source_locator='pckyotei.public.'+table,
        extraction_condition=condition, source_database='pckyotei', source_schema='public',
        source_table=table, retrieved_at=None, extracted_at=extracted_at,
        content_hash=hashed, row_count=len(rows), metadata={'phase':'3C',
            'transaction_read_only':'on', 'acquisition_history':'UNKNOWN',
            'prediction_availability_policy':'PRE_RACE_SOURCE_CLASS_USER_POLICY',
            'historical_exact_asof':'NOT_VERIFIED', 'source_year_is_not_retrieval_time':True},
        status='PRESERVED' if rows else 'SOURCE_EMPTY'), 'source_batch_id')
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator='\n')
    for position, row in enumerate(rows, 1):
        writer.writerow((batch, canonical_json(dict(zip(fields, keys[position-1]))),
                         position, canonical_json(row), digest(row), 'PRESERVED'))
    buffer.seek(0)
    cur.copy_expert('COPY raw.source_record (source_batch_id,source_record_key,source_position,'
                   'raw_payload,record_hash,interpretation_status) FROM STDIN WITH (FORMAT CSV)', buffer)
    return batch, True


def run():
    source, target = source_connection(), target_connection()
    report = {'version':VERSION, 'partitions':[]}
    try:
        with source.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout='180s'")
            # Include L2 months so a successful zero-row fetch has an explicit empty batch.
            cur.execute("SELECT DISTINCT kaisai_nen||'-'||left(kaisai_tsukihi,2) FROM ("
                        "SELECT kaisai_nen,kaisai_tsukihi FROM public.brd_l2 UNION "
                        "SELECT kaisai_nen,kaisai_tsukihi FROM public.brd_c2 UNION "
                        "SELECT kaisai_nen,kaisai_tsukihi FROM public.brd_c3) s "
                        "WHERE kaisai_nen >= '2017' ORDER BY 1")
            partitions = [r[0] for r in cur.fetchall()]
        for table in TABLES:
            fields = RACE_KEY + (('teiban',) if table == 'brd_c3' else ())
            for partition in partitions:
                # Acquisition failure raises before preserve(), never a SOURCE_EMPTY batch.
                with source.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute('SELECT * FROM public.'+table+' WHERE kaisai_nen=%s '
                                'AND left(kaisai_tsukihi,2)=%s ORDER BY '+','.join(fields),
                                tuple(partition.split('-')))
                    rows = [dict(r) for r in cur.fetchall()]
                with target.cursor() as cur:
                    cur.execute("SET LOCAL statement_timeout='180s'")
                    cur.execute('SELECT pg_advisory_xact_lock(330017004)')
                    batch, added = preserve(cur, table, partition, rows, datetime.now(timezone.utc))
                target.commit()
                item = dict(table=table, partition=partition, rows=len(rows), batch=batch, new=added)
                report['partitions'].append(item)
                print(json.dumps(item), flush=True)
        report['rows'] = {t:sum(p['rows'] for p in report['partitions'] if p['table']==t) for t in TABLES}
        report['new_batches'] = sum(p['new'] for p in report['partitions'])
        report['new_records'] = sum(p['rows'] for p in report['partitions'] if p['new'])
        return report
    finally:
        source.rollback(); source.close()
        target.rollback(); target.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    result = run()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
