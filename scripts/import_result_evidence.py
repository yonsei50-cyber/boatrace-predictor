"""Preserve complete 2017+ R2 rows using the immutable Raw batch contract."""
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

VERSION = 'phase3b-r2-evidence-v1'


def preserve_r2(cur, partition, rows, extracted_at):
    if len(partition) != 7 or date.fromisoformat(partition+'-01') < date(2017,1,1):
        raise ValueError('R2 scope starts 2017-01-01')
    keys = [tuple(r[k] for k in RACE_KEY) for r in rows]
    if len(keys) != len(set(keys)):
        raise ValueError('duplicate R2 source key')
    if keys != sorted(keys) or any(r['kaisai_nen']+'-'+r['kaisai_tsukihi'][:2] != partition for r in rows):
        raise ValueError('R2 partition/order mismatch')
    condition = dict(version=VERSION, partition=partition, order_by=list(RACE_KEY))
    hashed = digest(rows)
    cur.execute('SELECT source_batch_id,content_hash FROM raw.source_batch '
                'WHERE source_table=%s AND extraction_condition=%s ORDER BY source_batch_id',
                ('brd_r2', Json(condition)))
    prior = cur.fetchall()
    if prior:
        if len(prior) != 1 or prior[0][1] != hashed:
            raise RuntimeError('R2 partition changed or ambiguous; automatic adoption blocked')
        return prior[0][0], False
    batch = insert(cur, 'raw.source_batch', dict(source_name='PC-KYOTEI',
        source_type='SOURCE_DB_EXTRACT', source_locator='pckyotei.public.brd_r2',
        extraction_condition=condition, source_database='pckyotei', source_schema='public',
        source_table='brd_r2', retrieved_at=None, extracted_at=extracted_at,
        content_hash=hashed, row_count=len(rows), metadata={'phase':'3B',
            'transaction_read_only':'on', 'acquisition_history':'UNKNOWN',
            'source_year_is_not_retrieval_time':True},
        status='PRESERVED' if rows else 'SOURCE_EMPTY'), 'source_batch_id')
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator='\n')
    for position, row in enumerate(rows, 1):
        writer.writerow((batch, canonical_json(dict(zip(RACE_KEY, keys[position-1]))),
                         position, canonical_json(row), digest(row), 'PRESERVED'))
    buffer.seek(0)
    cur.copy_expert('COPY raw.source_record (source_batch_id,source_record_key,source_position,'
                   'raw_payload,record_hash,interpretation_status) FROM STDIN WITH (FORMAT CSV)', buffer)
    return batch, True


def run():
    source, target = source_connection(), target_connection()
    report = {'version':VERSION, 'source':'pckyotei.public.brd_r2', 'partitions':[]}
    try:
        with source.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout='180s'")
            cur.execute("SELECT DISTINCT kaisai_nen||'-'||left(kaisai_tsukihi,2) "
                        "FROM public.brd_r2 WHERE kaisai_nen >= '2017' ORDER BY 1")
            partitions = [r[0] for r in cur.fetchall()]
        for partition in partitions:
            with source.cursor(cursor_factory=RealDictCursor) as cur:
                cur.execute('SELECT * FROM public.brd_r2 WHERE kaisai_nen=%s '
                            'AND left(kaisai_tsukihi,2)=%s ORDER BY '+','.join(RACE_KEY),
                            tuple(partition.split('-')))
                rows = [dict(r) for r in cur.fetchall()]
            with target.cursor() as cur:
                cur.execute("SET LOCAL statement_timeout='180s'")
                cur.execute('SELECT pg_advisory_xact_lock(330017003)')
                batch, added = preserve_r2(cur, partition, rows, datetime.now(timezone.utc))
            target.commit()
            item = dict(partition=partition, rows=len(rows), batch=batch, new=added)
            report['partitions'].append(item)
            print(json.dumps(item), flush=True)
        report['total_rows'] = sum(p['rows'] for p in report['partitions'])
        return report
    finally:
        source.rollback()
        source.close()
        target.rollback()
        target.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    result = run()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
