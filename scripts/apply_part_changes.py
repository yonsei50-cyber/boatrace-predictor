"""Apply the additive part-change migration and project preserved C3 Raw rows."""

import argparse
import json
from pathlib import Path

from scripts.db import target_connection
from scripts.import_environment_preinfo import VERSION as C3_VERSION


MIGRATION = Path(__file__).resolve().parents[1] / 'sql/migrations/0006_race_boat_part_change.sql'


def apply():
    conn = target_connection()
    report = {'migration': MIGRATION.name, 'source_version': C3_VERSION, 'batches': []}
    try:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout='600s'")
            cur.execute('SELECT pg_advisory_xact_lock(330017006)')
            cur.execute(MIGRATION.read_text(encoding='utf-8'))
        conn.commit()

        with conn.cursor() as cur:
            cur.execute("""SELECT source_batch_id FROM raw.source_batch
                WHERE source_table='brd_c3' AND extraction_condition->>'version'=%s
                ORDER BY source_batch_id""", (C3_VERSION,))
            batches = [row[0] for row in cur.fetchall()]
        conn.rollback()
        if not batches:
            raise RuntimeError('no preserved Phase 3C C3 batches')

        for batch in batches:
            with conn.cursor() as cur:
                cur.execute("SET LOCAL statement_timeout='600s'")
                cur.execute('SELECT pg_advisory_xact_lock(330017006)')
                cur.execute('SELECT core.backfill_race_boat_part_change_v1(%s)', (batch,))
                inserted = cur.fetchone()[0]
            conn.commit()
            report['batches'].append({'source_batch_id': batch, 'inserted': inserted})
        report['inserted'] = sum(item['inserted'] for item in report['batches'])
        report['batch_count'] = len(batches)
        return report
    finally:
        conn.rollback()
        conn.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    result = apply()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'migration': result['migration'], 'batch_count': result['batch_count'],
                      'inserted': result['inserted']}))
