"""Read-only coverage, replay, and lineage audit for C3 part changes."""

import argparse
import json
from pathlib import Path

from psycopg2.extras import RealDictCursor

from scripts.db import target_connection
from scripts.import_environment_preinfo import VERSION as C3_VERSION


FIELDS = ('propeller', 'piston', 'piston_ring', 'denki_isshiki',
          'carburetor', 'cylinder', 'crankshaft', 'gearcase', 'careerbody')


def fetch(cur, sql, params=()):
    cur.execute(sql, params)
    return [dict(row) for row in cur.fetchall()]


def one(cur, sql, params=()):
    result = fetch(cur, sql, params)
    if len(result) != 1:
        raise RuntimeError('audit query returned unexpected row count')
    return result[0]


def audit():
    conn = target_connection()
    try:
        conn.commit()
        conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SET LOCAL statement_timeout='900s'")
            read_only = one(cur, "SELECT current_setting('transaction_read_only') AS value")['value']
            report = {'version': 'phase3d-part-change-v1', 'source_version': C3_VERSION,
                      'transaction_read_only': read_only, 'source_fields': list(FIELDS)}
            report['coverage'] = one(cur, '''SELECT count(*) AS rows,
                count(DISTINCT race_id) AS races,
                count(DISTINCT (race_id,boat_no)) AS boats,
                count(DISTINCT r.venue_code) AS venues,
                min(r.race_date) AS first_date,max(r.race_date) AS last_date,
                count(*) FILTER (WHERE quantity IS NOT NULL) AS quantity_known,
                count(*) FILTER (WHERE quantity IS NULL) AS quantity_unknown,
                count(*) FILTER (WHERE part_type IS NULL) AS type_unresolved,
                count(*) FILTER (WHERE r.race_date<DATE '2017-01-01') AS pre_2017_rows,
                count(*) FILTER (WHERE status IN ('INVALID','UNRESOLVED_VALUE',
                   'UNRESOLVED_BLANK','UNRESOLVED_TYPE')) AS invalid_or_other_unresolved
                FROM core.race_boat_part_change p JOIN core.race r USING(race_id)''')
            report['status'] = fetch(cur, '''SELECT status,count(*) AS rows
                FROM core.race_boat_part_change GROUP BY status ORDER BY status''')
            report['part_types'] = fetch(cur, '''SELECT source_field,part_type,
                count(*) AS rows,count(DISTINCT race_id) AS races,
                count(DISTINCT (race_id,boat_no)) AS boats,
                count(*) FILTER (WHERE quantity IS NOT NULL) AS quantity_known,
                count(*) FILTER (WHERE quantity IS NULL) AS quantity_unknown
                FROM core.race_boat_part_change
                GROUP BY source_field,part_type ORDER BY source_field,part_type''')
            report['by_year'] = fetch(cur, '''SELECT extract(year FROM r.race_date)::int AS year,
                count(*) AS rows,count(DISTINCT p.race_id) AS races,
                count(DISTINCT (p.race_id,p.boat_no)) AS boats
                FROM core.race_boat_part_change p JOIN core.race r USING(race_id)
                GROUP BY 1 ORDER BY 1''')
            report['by_venue'] = fetch(cur, '''SELECT r.venue_code,
                count(*) AS rows,count(DISTINCT p.race_id) AS races,
                count(DISTINCT (p.race_id,p.boat_no)) AS boats
                FROM core.race_boat_part_change p JOIN core.race r USING(race_id)
                GROUP BY 1 ORDER BY 1''')
            report['by_year_venue'] = fetch(cur, '''SELECT
                extract(year FROM r.race_date)::int AS year,r.venue_code,
                count(*) AS rows,count(DISTINCT p.race_id) AS races,
                count(DISTINCT (p.race_id,p.boat_no)) AS boats
                FROM core.race_boat_part_change p JOIN core.race r USING(race_id)
                GROUP BY 1,2 ORDER BY 1,2''')
            report['multiple_changes'] = one(cur, '''WITH per_boat AS (
                SELECT race_id,boat_no,count(DISTINCT source_field) AS n,
                       count(*) AS observation_rows
                FROM core.race_boat_part_change GROUP BY race_id,boat_no)
                SELECT count(*) FILTER (WHERE n>1) AS boats_multiple,
                       coalesce(max(n),0) AS maximum_changes,
                       coalesce(sum(observation_rows) FILTER (WHERE n>1),0)
                         AS rows_on_multiple_boats
                FROM per_boat''')
            report['multiplicity'] = fetch(cur, '''SELECT n AS changes_per_boat,count(*) AS boats
                FROM (SELECT race_id,boat_no,count(DISTINCT source_field) AS n
                      FROM core.race_boat_part_change GROUP BY race_id,boat_no) x
                GROUP BY n ORDER BY n''')
            report['duplicate_candidates'] = one(cur, '''SELECT count(*) AS groups,
                coalesce(sum(n-1),0) AS excess_rows FROM (
                SELECT race_id,boat_no,part_type,count(*) AS n
                FROM core.race_boat_part_change
                GROUP BY race_id,boat_no,part_type HAVING count(*)>1) x''')
            report['lineage'] = one(cur, '''SELECT
                count(*) FILTER (WHERE s.source_record_id IS NULL) AS missing_raw,
                count(*) FILTER (WHERE b.source_table IS DISTINCT FROM 'brd_c3'
                    OR b.extraction_condition->>'version' IS DISTINCT FROM %s) AS wrong_source,
                count(*) FILTER (WHERE s.source_record_key IS DISTINCT FROM
                    jsonb_build_object('kaisai_nen',s.raw_payload->>'kaisai_nen',
                    'kaisai_tsukihi',s.raw_payload->>'kaisai_tsukihi',
                    'kyoteijo_code',s.raw_payload->>'kyoteijo_code',
                    'race_no',s.raw_payload->>'race_no','teiban',s.raw_payload->>'teiban'))
                    AS raw_key_mismatch,
                count(*) FILTER (WHERE s.raw_payload->>'kaisai_nen' IS DISTINCT FROM
                    to_char(r.race_date,'YYYY') OR s.raw_payload->>'kaisai_tsukihi'
                    IS DISTINCT FROM to_char(r.race_date,'MMDD') OR
                    s.raw_payload->>'kyoteijo_code' IS DISTINCT FROM
                    lpad(r.venue_code::text,2,'0') OR s.raw_payload->>'race_no'
                    IS DISTINCT FROM lpad(r.race_no::text,2,'0') OR
                    s.raw_payload->>'teiban' IS DISTINCT FROM p.boat_no::text)
                    AS identity_mismatch,
                count(*) FILTER (WHERE p.raw_value IS DISTINCT FROM
                    s.raw_payload->p.source_field OR p.quantity_raw IS DISTINCT FROM
                    s.raw_payload->>p.source_field OR p.part_type_raw IS DISTINCT FROM
                    p.source_field) AS raw_mismatch,
                count(*) FILTER (WHERE p.part_type IS DISTINCT FROM
                    upper(p.source_field)) AS part_type_mismatch,
                count(*) FILTER (WHERE p.status IS DISTINCT FROM CASE
                    WHEN p.raw_value IS NULL OR p.raw_value='null'::jsonb
                      OR btrim(p.raw_value #>> '{}')='' THEN 'UNRESOLVED_BLANK'
                    WHEN (p.source_field='piston' AND p.raw_value IN ('"1"'::jsonb,'"2"'::jsonb))
                      OR (p.source_field='piston_ring' AND p.raw_value IN
                          ('"1"'::jsonb,'"2"'::jsonb,'"3"'::jsonb,'"4"'::jsonb))
                      OR (p.source_field NOT IN ('piston','piston_ring')
                          AND p.raw_value='"1"'::jsonb)
                      THEN 'UNRESOLVED_QUANTITY'
                    ELSE 'UNRESOLVED_VALUE' END) AS status_mismatch,
                count(*) FILTER (WHERE p.quantity IS NOT NULL) AS inferred_quantity,
                count(*) FILTER (WHERE p.normalization_version IS DISTINCT FROM
                    'phase3d-part-change-v1') AS version_mismatch,
                count(*) FILTER (WHERE p.provenance->>'result_dependency'
                    IS DISTINCT FROM 'false') AS result_dependency_mismatch
                FROM core.race_boat_part_change p
                LEFT JOIN raw.source_record s USING(source_record_id)
                LEFT JOIN raw.source_batch b USING(source_batch_id)
                LEFT JOIN core.race r USING(race_id)''', (C3_VERSION,))
            report['orphans'] = one(cur, '''SELECT
                count(*) FILTER (WHERE r.race_id IS NULL) AS race,
                count(*) FILTER (WHERE e.race_id IS NULL) AS boat
                FROM core.race_boat_part_change p
                LEFT JOIN core.race r USING(race_id)
                LEFT JOIN core.race_entry e USING(race_id,boat_no)''')
            report['existing_preservation'] = one(cur, '''SELECT
                (SELECT count(*) FROM core.race_environment_preinfo) AS c2_rows,
                (SELECT count(*) FROM core.race_boat_preinfo) AS c3_rows,
                (SELECT count(*) FROM core.dataset_version) AS frozen_datasets,
                (SELECT count(*) FROM core.dataset_version WHERE
                    results_cutoff_date>=effective_date) AS d_minus_one_violations''')

            values = ','.join('(%s,s.raw_payload->%s)' for _ in FIELDS)
            params = tuple(x for field in FIELDS for x in (field, field)) + (C3_VERSION,)
            report['raw_replay'] = one(cur, '''WITH expected AS MATERIALIZED (
                SELECT s.source_record_id,f.source_field,f.raw_value
                FROM raw.source_record s
                JOIN raw.source_batch b USING(source_batch_id)
                CROSS JOIN LATERAL (VALUES ''' + values + ''') f(source_field,raw_value)
                WHERE b.source_table='brd_c3'
                  AND b.extraction_condition->>'version'=%s
                  AND s.raw_payload ? f.source_field
                  AND f.raw_value IS DISTINCT FROM '"0"'::jsonb)
                SELECT count(*) AS expected_rows,
                    count(*) FILTER (WHERE p.part_change_id IS NULL) AS missing_canonical,
                    count(*) FILTER (WHERE p.raw_value IS DISTINCT FROM e.raw_value)
                        AS raw_mismatch
                FROM expected e LEFT JOIN core.race_boat_part_change p
                  ON p.source_record_id=e.source_record_id
                 AND p.source_field=e.source_field AND p.ordinal=1''', params)
            blockers = {k: v for section in ('lineage', 'orphans')
                        for k, v in report[section].items() if v}
            blockers.update({k: v for k, v in report['raw_replay'].items()
                             if k != 'expected_rows' and v})
            blockers['unexpected_count'] = abs(report['raw_replay']['expected_rows'] -
                                               report['coverage']['rows'])
            blockers['pre_2017_rows'] = report['coverage']['pre_2017_rows']
            for key, expected in (('c2_rows', 542003), ('c3_rows', 3252018),
                                  ('frozen_datasets', 119)):
                blockers['unexpected_' + key] = int(
                    report['existing_preservation'][key] != expected)
            blockers['d_minus_one_violations'] = report['existing_preservation']['d_minus_one_violations']
            report['blocking_findings'] = {k: v for k, v in blockers.items() if v}
            report['status_verdict'] = 'PASS' if not report['blocking_findings'] else 'BLOCKING'
            return report
    finally:
        conn.rollback()
        conn.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    result = audit()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2, default=str) + '\n', encoding='utf-8')
    print(json.dumps({'status': result['status_verdict'], 'coverage': result['coverage'],
                      'blocking_findings': result['blocking_findings']}, default=str))
