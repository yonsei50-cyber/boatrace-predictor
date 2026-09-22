"""Read-only aggregate audit of the Phase 2/2.5 history foundation."""
import argparse
from datetime import date, datetime
from decimal import Decimal
import json
from pathlib import Path
import sys

from psycopg2.extras import RealDictCursor

from scripts.db import DEFAULT_CONFIG, target_connection
from scripts.foundation import motor_generation, MOTOR_RULE_VERSION

HISTORY_VERSION = 'phase2.5-stored-history-v1'


def _json_value(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else float(value)
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _rows(cur, query, params=()):
    cur.execute(query, params)
    return [_json_value(dict(row)) for row in cur.fetchall()]


def _row(cur, query, params=()):
    rows = _rows(cur, query, params)
    if len(rows) != 1:
        raise RuntimeError('audit query did not return exactly one row')
    return rows[0]


def _counts(cur, schema, tables):
    values = {}
    for table in tables:
        cur.execute('SELECT count(*) AS n FROM ' + schema + '.' + table)
        values[table] = cur.fetchone()['n']
    return values


def audit(connection, progress=None):
    """Return a JSON-serializable audit report from one read-only snapshot.

    The connection must be idle. The caller retains ownership of the transaction
    and should roll it back after consuming the report.
    """
    with connection.cursor(cursor_factory=RealDictCursor) as cur:
        emit = progress or (lambda _message: None)
        # This must be the first command in the transaction. It prevents the audit
        # from mutating even if a future query is changed accidentally.
        cur.execute('SET TRANSACTION READ ONLY')
        cur.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        # Bound sort/hash workspace for million-row natural-key comparisons.
        # Transaction-local only; no database/server configuration is changed.
        cur.execute("SET LOCAL work_mem='64MB'")
        cur.execute("SELECT current_setting('transaction_read_only') AS value")
        read_only = cur.fetchone()['value']
        if read_only != 'on':
            raise RuntimeError('audit transaction is not read-only')

        report = {
            'audit_version': 'PHASE_2_5_HISTORY_AUDIT_V1',
            'history_scope': {
                'race_date_start': '2017-01-01',
                'batch_version': HISTORY_VERSION,
                'ki_exception': 'identity-before-2017 selected subset only',
            },
            'transaction_read_only': read_only,
            'scope_note': (
                'Observed canonical races only. Unobserved calendar dates are not '
                'classified as missing racing dates.'
            ),
        }

        emit('canonical counts and observed coverage')
        report['canonical'] = {
            'counts': _counts(cur, 'core', (
                'venue', 'race', 'player', 'motor', 'race_entry',
                'race_result', 'dataset_version')),
            'race_range': _row(cur, '''
                SELECT min(race_date) AS date_start,max(race_date) AS date_end,
                    count(DISTINCT race_date) AS observed_race_dates,
                    count(*) FILTER (WHERE race_date<'2017-01-01') AS races_before_scope,
                    CASE WHEN count(*)=0 THEN 0
                         ELSE max(race_date)-min(race_date)+1 END AS calendar_span_days
                FROM core.race'''),
            'result_range':_row(cur, '''SELECT min(r.race_date) AS date_start,max(r.race_date) AS date_end,
                count(DISTINCT r.race_date) AS observed_result_dates
                FROM core.race_result z JOIN core.race r USING(race_id)'''),
            'venue_coverage': _rows(cur, '''
                SELECT v.venue_code,v.venue_name,min(r.race_date) AS date_start,
                    max(r.race_date) AS date_end,count(DISTINCT r.race_date) AS observed_race_dates,
                    count(r.race_id) AS races,count(DISTINCT r.race_no) AS race_numbers_observed
                FROM core.venue v LEFT JOIN core.race r USING(venue_code)
                GROUP BY v.venue_code,v.venue_name ORDER BY v.venue_code'''),
            'monthly_observed_coverage': _rows(cur, '''
                SELECT extract(year FROM race_date)::int AS year,
                    extract(month FROM race_date)::int AS month,venue_code,
                    count(DISTINCT race_date) AS observed_race_dates,count(*) AS races
                FROM core.race GROUP BY 1,2,3 ORDER BY 1,2,3'''),
        }

        emit('race entry and result completeness')
        report['race_completeness'] = {
            'recorded_races_per_venue_day':_rows(cur, '''SELECT recorded_races,count(*) AS venue_days FROM (
                SELECT race_date,venue_code,count(*) AS recorded_races FROM core.race GROUP BY 1,2
                ) q GROUP BY recorded_races ORDER BY recorded_races'''),
            'entry_rows_per_race': _rows(cur, '''
                SELECT entry_count,count(*) AS races FROM (
                    SELECT r.race_id,count(e.boat_no) AS entry_count
                    FROM core.race r LEFT JOIN core.race_entry e USING(race_id)
                    GROUP BY r.race_id) q GROUP BY entry_count ORDER BY entry_count'''),
            'result_rows_per_race': _rows(cur, '''
                SELECT result_count,count(*) AS races FROM (
                    SELECT r.race_id,count(z.boat_no) AS result_count
                    FROM core.race r LEFT JOIN core.race_result z USING(race_id)
                    GROUP BY r.race_id) q GROUP BY result_count ORDER BY result_count'''),
            'races_not_six_entries': _row(cur, '''
                SELECT count(*) AS count FROM (
                    SELECT r.race_id FROM core.race r LEFT JOIN core.race_entry e USING(race_id)
                    GROUP BY r.race_id HAVING count(e.boat_no)<>6) q''')['count'],
            'races_not_six_results': _row(cur, '''
                SELECT count(*) AS count FROM (
                    SELECT r.race_id FROM core.race r LEFT JOIN core.race_result z USING(race_id)
                    GROUP BY r.race_id HAVING count(z.boat_no)<>6) q''')['count'],
            'entries_without_result': _row(cur, '''
                SELECT count(*) AS count FROM core.race_entry e LEFT JOIN core.race_result z
                USING(race_id,boat_no) WHERE z.race_id IS NULL''')['count'],
            'race_status_distribution': _rows(cur, '''
                SELECT race_status,count(*) AS races FROM core.race
                GROUP BY race_status ORDER BY race_status'''),
            'result_present_status_not_six_results': _row(cur, '''
                SELECT count(*) AS count FROM (
                    SELECT r.race_id FROM core.race r LEFT JOIN core.race_result z USING(race_id)
                    WHERE r.race_status='RESULT_RECORDS_PRESENT'
                    GROUP BY r.race_id HAVING count(z.boat_no)<>6) q''')['count'],
        }

        emit('player and KI boundary checks')
        report['players'] = {
            'sex_distribution': _rows(cur, '''
                SELECT coalesce(sex,'<NULL>') AS sex,count(*) AS players
                FROM core.player GROUP BY sex ORDER BY sex NULLS FIRST'''),
            'sex_normalization_status': _rows(cur, '''
                SELECT sex_normalization_status,count(*) AS players
                FROM core.player GROUP BY sex_normalization_status
                ORDER BY sex_normalization_status'''),
            'players_without_entries': _row(cur, '''
                SELECT count(*) AS count FROM core.player p LEFT JOIN core.race_entry e USING(player_id)
                WHERE e.player_id IS NULL''')['count'],
            'future_or_same_year_ki': _row(cur, '''
                WITH first_race AS (
                    SELECT e.player_id,min(extract(year FROM r.race_date)::int) AS first_year
                    FROM core.race_entry e JOIN core.race r USING(race_id) GROUP BY e.player_id
                ), selected_ki AS (
                    SELECT p.player_id,f.first_year,btrim(s.raw_payload->>'kaisai_nen') AS ki_year
                    FROM core.player p JOIN first_race f USING(player_id)
                    JOIN raw.source_record s ON s.source_record_id=p.sex_source_record_id
                    JOIN raw.source_batch b USING(source_batch_id)
                    WHERE b.source_table='brd_ki')
                SELECT count(*) FILTER (WHERE ki_year !~ '^[0-9]{4}$') AS invalid_year,
                    count(*) FILTER (WHERE ki_year ~ '^[0-9]{4}$'
                        AND ki_year::int>=first_year) AS blocking_count
                FROM selected_ki''') | {
                    'scope': 'selected canonical sex_source_record_id only'
                },
        }

        emit('motor interval checks')
        report['motors'] = {
            'entry_motor_presence': _row(cur, '''
                SELECT count(*) FILTER (WHERE motor_id IS NOT NULL) AS with_motor,
                    count(*) FILTER (WHERE motor_id IS NULL) AS without_motor
                FROM core.race_entry'''),
            'invalid_generation_intervals': _row(cur, '''
                SELECT count(*) AS count FROM core.motor
                WHERE generation_start_date>=generation_end_date
                   OR extract(year FROM generation_start_date)::int<>generation_start_year''')['count'],
            'entries_outside_motor_interval': _row(cur, '''
                SELECT count(*) AS count FROM core.race_entry e JOIN core.race r USING(race_id)
                JOIN core.motor m USING(motor_id)
                WHERE r.race_date<m.generation_start_date OR r.race_date>=m.generation_end_date
                   OR e.venue_code<>m.venue_code''')['count'],
        }

        emit('result and special-value distributions')
        report['result_distributions'] = {
            'numeric_start_summary':_row(cur, '''SELECT min(start_timing) AS minimum,
                max(start_timing) AS maximum,count(start_timing) AS observed_numeric,
                count(*) FILTER (WHERE start_timing=0) AS explicit_zero,
                count(*) FILTER (WHERE start_timing>=1) AS at_least_one_second,
                count(*) FILTER (WHERE result_status IN ('F','L') AND start_timing IS NOT NULL)
                    AS forbidden_numeric_fl FROM core.race_result'''),
            'special_value_row_limit': 100,
            'actual_course': _rows(cur, '''
                SELECT coalesce(actual_course::text,'<NULL>') AS value,count(*) AS rows
                FROM core.race_result GROUP BY actual_course ORDER BY actual_course NULLS FIRST'''),
            'actual_course_raw_special': _rows(cur, '''
                SELECT coalesce(actual_course_raw,'<NULL>') AS value,count(*) AS rows
                FROM core.race_result
                WHERE actual_course IS NULL
                GROUP BY actual_course_raw ORDER BY rows DESC,value LIMIT 100'''),
            'finish_position': _rows(cur, '''
                SELECT coalesce(finish_position::text,'<NULL>') AS value,count(*) AS rows
                FROM core.race_result GROUP BY finish_position ORDER BY finish_position NULLS FIRST'''),
            'result_status': _rows(cur, '''
                SELECT result_status,count(*) AS rows FROM core.race_result
                GROUP BY result_status ORDER BY result_status'''),
            'finish_raw_special': _rows(cur, '''
                SELECT coalesce(finish_raw,'<NULL>') AS finish_raw,
                    coalesce(result_symbol_raw,'<NULL>') AS result_symbol_raw,
                    result_status,count(*) AS rows
                FROM core.race_result
                WHERE result_status<>'NORMAL' OR finish_position IS NULL
                GROUP BY finish_raw,result_symbol_raw,result_status
                ORDER BY rows DESC,finish_raw,result_symbol_raw LIMIT 100'''),
            'start_timing_status': _rows(cur, '''
                SELECT start_timing_status,count(*) AS rows FROM core.race_result
                GROUP BY start_timing_status ORDER BY start_timing_status'''),
            'start_timing_raw_special': _rows(cur, '''
                SELECT coalesce(start_timing_raw,'<NULL>') AS value,start_timing_status,
                    count(*) AS rows FROM core.race_result
                WHERE start_timing_status<>'NORMAL'
                GROUP BY start_timing_raw,start_timing_status
                ORDER BY rows DESC,value,start_timing_status LIMIT 100'''),
            'normalization_status': _rows(cur, '''
                SELECT normalization_status,count(*) AS rows FROM core.race_result
                GROUP BY normalization_status ORDER BY normalization_status'''),
        }

        emit('canonical duplicate and required-field checks')
        report['duplicates_and_required_missing'] = {
            'duplicate_race_natural_keys': _row(cur, '''
                SELECT count(*) AS count FROM (SELECT race_date,venue_code,race_no
                FROM core.race GROUP BY 1,2,3 HAVING count(*)>1) q''')['count'],
            'duplicate_entry_keys': _row(cur, '''
                SELECT count(*) AS count FROM (SELECT race_id,boat_no FROM core.race_entry
                GROUP BY 1,2 HAVING count(*)>1) q''')['count'],
            'duplicate_result_keys': _row(cur, '''
                SELECT count(*) AS count FROM (SELECT race_id,boat_no FROM core.race_result
                GROUP BY 1,2 HAVING count(*)>1) q''')['count'],
            'duplicate_raw_batch_positions': _row(cur, '''
                SELECT count(*) AS count FROM (
                    SELECT s.source_batch_id,s.source_position
                    FROM raw.source_record s JOIN raw.source_batch b USING(source_batch_id)
                    WHERE b.extraction_condition->>'version'='phase2.5-stored-history-v1'
                      AND ((b.source_table<>'brd_ki'
                            AND b.extraction_condition->>'partition'>='2017-01')
                        OR (b.source_table='brd_ki' AND
                            (b.extraction_condition->>'partition'>='2017'
                             OR b.extraction_condition->>'partition'='identity-before-2017')))
                    GROUP BY 1,2 HAVING count(*)>1) q''')['count'],
            'required_key_missing': _rows(cur, '''
                SELECT 'race.source_record_id' AS field,count(*) AS rows FROM core.race WHERE source_record_id IS NULL
                UNION ALL SELECT 'player.source_record_id',count(*) FROM core.player WHERE source_record_id IS NULL
                UNION ALL SELECT 'motor.source_record_id',count(*) FROM core.motor WHERE source_record_id IS NULL
                UNION ALL SELECT 'race_entry.source_record_id',count(*) FROM core.race_entry WHERE source_record_id IS NULL
                UNION ALL SELECT 'race_result.source_record_id',count(*) FROM core.race_result WHERE source_record_id IS NULL
                UNION ALL SELECT 'race_entry.player_id',count(*) FROM core.race_entry WHERE player_id IS NULL
                ORDER BY field'''),
        }

        emit('raw batch, overlap, omission, and source-pair reconciliation')
        report['raw_sources'] = {
            'declared_inventory': _row(cur, '''
                SELECT count(*) AS total_batches,coalesce(sum(row_count),0) AS total_declared_records,
                    count(*) FILTER (WHERE extraction_condition->>'version'='phase2.5-stored-history-v1'
                      AND ((source_table<>'brd_ki' AND extraction_condition->>'partition'>='2017-01')
                        OR (source_table='brd_ki' AND
                            (extraction_condition->>'partition'>='2017'
                             OR extraction_condition->>'partition'='identity-before-2017')))) AS scoped_batches,
                    coalesce(sum(row_count) FILTER
                      (WHERE extraction_condition->>'version'='phase2.5-stored-history-v1'
                      AND ((source_table<>'brd_ki' AND extraction_condition->>'partition'>='2017-01')
                        OR (source_table='brd_ki' AND
                            (extraction_condition->>'partition'>='2017'
                             OR extraction_condition->>'partition'='identity-before-2017')))),0)
                        AS scoped_declared_records,
                    coalesce(sum(row_count) FILTER
                      (WHERE (extraction_condition->>'version'='phase2.5-stored-history-v1'
                      AND ((source_table<>'brd_ki' AND extraction_condition->>'partition'>='2017-01')
                        OR (source_table='brd_ki' AND
                            (extraction_condition->>'partition'>='2017'
                             OR extraction_condition->>'partition'='identity-before-2017')))) IS NOT TRUE),0)
                        AS retained_out_of_scope_declared_records,
                    count(*) FILTER
                      (WHERE (extraction_condition->>'version'='phase2.5-stored-history-v1'
                      AND ((source_table<>'brd_ki' AND extraction_condition->>'partition'>='2017-01')
                        OR (source_table='brd_ki' AND
                            (extraction_condition->>'partition'>='2017'
                             OR extraction_condition->>'partition'='identity-before-2017')))) IS NOT TRUE)
                        AS retained_out_of_scope_batches
                FROM raw.source_batch'''),
            'phase_2_5_batches': _row(cur, '''
                SELECT count(*) AS batches,coalesce(sum(row_count),0) AS declared_rows,
                    count(*) FILTER (WHERE status<>'PRESERVED') AS non_preserved_batches
                FROM raw.source_batch b
                WHERE b.extraction_condition->>'version'='phase2.5-stored-history-v1'
                  AND ((b.source_table<>'brd_ki' AND b.extraction_condition->>'partition'>='2017-01')
                    OR (b.source_table='brd_ki' AND
                        (b.extraction_condition->>'partition'>='2017'
                         OR b.extraction_condition->>'partition'='identity-before-2017')))'''),
            'phase_2_5_by_table': _rows(cur, '''
                SELECT source_table,count(*) AS batches,sum(row_count) AS declared_rows,
                    min(extracted_at) AS first_extracted_at,max(extracted_at) AS last_extracted_at
                FROM raw.source_batch b
                WHERE b.extraction_condition->>'version'='phase2.5-stored-history-v1'
                  AND ((b.source_table<>'brd_ki' AND b.extraction_condition->>'partition'>='2017-01')
                    OR (b.source_table='brd_ki' AND
                        (b.extraction_condition->>'partition'>='2017'
                         OR b.extraction_condition->>'partition'='identity-before-2017')))
                GROUP BY source_table ORDER BY source_table'''),
            'phase_2_5_partitions': _rows(cur, '''
                SELECT source_table,extraction_condition->>'partition' AS partition,
                    count(*) AS batches,sum(row_count) AS declared_rows,
                    count(DISTINCT content_hash) AS content_versions
                FROM raw.source_batch b
                WHERE b.extraction_condition->>'version'='phase2.5-stored-history-v1'
                  AND ((b.source_table<>'brd_ki' AND b.extraction_condition->>'partition'>='2017-01')
                    OR (b.source_table='brd_ki' AND
                        (b.extraction_condition->>'partition'>='2017'
                         OR b.extraction_condition->>'partition'='identity-before-2017')))
                GROUP BY source_table,extraction_condition->>'partition'
                ORDER BY source_table,partition'''),
            'ambiguous_phase_2_5_partitions': _row(cur, '''
                SELECT count(*) AS count FROM (
                    SELECT source_table,extraction_condition
                    FROM raw.source_batch b
                    WHERE b.extraction_condition->>'version'='phase2.5-stored-history-v1'
                      AND ((b.source_table<>'brd_ki' AND b.extraction_condition->>'partition'>='2017-01')
                        OR (b.source_table='brd_ki' AND
                            (b.extraction_condition->>'partition'>='2017'
                             OR b.extraction_condition->>'partition'='identity-before-2017')))
                    GROUP BY source_table,extraction_condition HAVING count(*)<>1) q''')['count'],
            'incomplete_batches': _row(cur, '''
                WITH scoped AS (
                    SELECT * FROM raw.source_batch b
                    WHERE b.extraction_condition->>'version'='phase2.5-stored-history-v1'
                      AND ((b.source_table<>'brd_ki' AND b.extraction_condition->>'partition'>='2017-01')
                        OR (b.source_table='brd_ki' AND
                            (b.extraction_condition->>'partition'>='2017'
                             OR b.extraction_condition->>'partition'='identity-before-2017')))
                )
                SELECT count(*) AS count FROM scoped b LEFT JOIN (
                    SELECT source_batch_id,count(*) AS actual_rows FROM raw.source_record
                    WHERE source_batch_id IN (SELECT source_batch_id FROM scoped)
                    GROUP BY source_batch_id) s USING(source_batch_id)
                WHERE coalesce(s.actual_rows,0)<>b.row_count''')['count'],
            'logical_key_overlap': _row(cur, '''
                WITH keys AS (
                    SELECT b.source_table,s.source_record_key,count(*) AS observations,
                        count(DISTINCT s.record_hash) AS versions
                    FROM raw.source_record s JOIN raw.source_batch b USING(source_batch_id)
                    WHERE b.extraction_condition->>'version'='phase2.5-stored-history-v1'
                      AND ((b.source_table<>'brd_ki' AND b.extraction_condition->>'partition'>='2017-01')
                        OR (b.source_table='brd_ki' AND
                            (b.extraction_condition->>'partition'>='2017'
                             OR b.extraction_condition->>'partition'='identity-before-2017')))
                    GROUP BY b.source_table,s.source_record_key)
                SELECT count(*) FILTER (WHERE observations>1 AND versions=1) AS repeated_identical_keys,
                    count(*) FILTER (WHERE versions>1) AS conflicting_keys
                FROM keys'''),
            'conflicting_logical_key_examples': _rows(cur, '''
                SELECT b.source_table,s.source_record_key,count(*) AS observations,
                    count(DISTINCT s.record_hash) AS versions
                FROM raw.source_record s JOIN raw.source_batch b USING(source_batch_id)
                WHERE b.extraction_condition->>'version'='phase2.5-stored-history-v1'
                  AND ((b.source_table<>'brd_ki' AND b.extraction_condition->>'partition'>='2017-01')
                    OR (b.source_table='brd_ki' AND
                        (b.extraction_condition->>'partition'>='2017'
                         OR b.extraction_condition->>'partition'='identity-before-2017')))
                GROUP BY b.source_table,s.source_record_key
                HAVING count(DISTINCT s.record_hash)>1
                ORDER BY b.source_table,s.source_record_key LIMIT 20'''),
            'raw_to_canonical_reconciliation': _rows(cur, '''
                WITH refs AS (
                    SELECT source_record_id FROM core.race
                    UNION SELECT grade_source_record_id FROM core.race WHERE grade_source_record_id IS NOT NULL
                    UNION SELECT source_record_id FROM core.player
                    UNION SELECT sex_source_record_id FROM core.player WHERE sex_source_record_id IS NOT NULL
                    UNION SELECT source_record_id FROM core.motor
                    UNION SELECT source_record_id FROM core.race_entry
                    UNION SELECT source_record_id FROM core.race_result
                ), canonical_keys AS (
                    SELECT DISTINCT b.source_table,s.source_record_key
                    FROM refs r JOIN raw.source_record s USING(source_record_id)
                    JOIN raw.source_batch b USING(source_batch_id)
                ), observed AS (
                    SELECT b.source_table,s.source_record_key,s.source_record_id,
                        (r.source_record_id IS NOT NULL) AS referenced
                    FROM raw.source_record s JOIN raw.source_batch b USING(source_batch_id)
                    LEFT JOIN refs r USING(source_record_id)
                    WHERE b.extraction_condition->>'version'='phase2.5-stored-history-v1'
                      AND ((b.source_table<>'brd_ki' AND b.extraction_condition->>'partition'>='2017-01')
                        OR (b.source_table='brd_ki' AND
                            (b.extraction_condition->>'partition'>='2017'
                             OR b.extraction_condition->>'partition'='identity-before-2017')))
                ), keys AS (
                    SELECT o.source_table,o.source_record_key,
                        (c.source_table IS NOT NULL) AS represented
                    FROM observed o LEFT JOIN canonical_keys c
                      USING(source_table,source_record_key)
                    GROUP BY o.source_table,o.source_record_key,c.source_table)
                SELECT o.source_table,count(*) AS observations,
                    count(*) FILTER (WHERE o.referenced) AS referenced_observations,
                    count(*) FILTER (WHERE NOT o.referenced) AS unreferenced_observations,
                    count(DISTINCT o.source_record_key) AS logical_keys,
                    count(DISTINCT o.source_record_key) FILTER (WHERE NOT k.represented)
                        AS unrepresented_logical_keys
                FROM observed o JOIN keys k USING(source_table,source_record_key)
                GROUP BY o.source_table ORDER BY o.source_table'''),
            'required_source_field_missing': _rows(cur, '''
                WITH required(source_table,field) AS (VALUES
                    ('brd_l1','kaisai_nen'),('brd_l1','kaisai_tsukihi'),
                    ('brd_l1','kyoteijo_code'),
                    ('brd_l2','kaisai_nen'),('brd_l2','kaisai_tsukihi'),
                    ('brd_l2','kyoteijo_code'),('brd_l2','race_no'),
                    ('brd_l3','kaisai_nen'),('brd_l3','kaisai_tsukihi'),
                    ('brd_l3','kyoteijo_code'),('brd_l3','race_no'),
                    ('brd_l3','teiban'),('brd_l3','toroku_bango'),
                    ('brd_r3','kaisai_nen'),('brd_r3','kaisai_tsukihi'),
                    ('brd_r3','kyoteijo_code'),('brd_r3','race_no'),
                    ('brd_r3','teiban'),('brd_r3','toroku_bango'),
                    ('brd_ki','toroku_bango'),('brd_ki','kaisai_nen'),('brd_ki','ki')
                )
                SELECT q.source_table,q.field,count(*) AS rows
                FROM required q JOIN raw.source_batch b USING(source_table)
                JOIN raw.source_record s USING(source_batch_id)
                WHERE b.extraction_condition->>'version'='phase2.5-stored-history-v1'
                  AND ((b.source_table<>'brd_ki' AND b.extraction_condition->>'partition'>='2017-01')
                    OR (b.source_table='brd_ki' AND
                        (b.extraction_condition->>'partition'>='2017'
                         OR b.extraction_condition->>'partition'='identity-before-2017')))
                  AND nullif(btrim(s.raw_payload->>q.field),'') IS NULL
                GROUP BY q.source_table,q.field ORDER BY q.source_table,q.field'''),
            'l3_r3_key_reconciliation': _row(cur, '''
                WITH l AS (SELECT DISTINCT s.source_record_key,s.raw_payload->>'toroku_bango' AS player
                    FROM raw.source_record s JOIN raw.source_batch b USING(source_batch_id)
                    WHERE b.source_table='brd_l3'
                      AND b.extraction_condition->>'version'='phase2.5-stored-history-v1'
                      AND b.extraction_condition->>'partition'>='2017-01'),
                z AS (SELECT DISTINCT s.source_record_key,s.raw_payload->>'toroku_bango' AS player
                    FROM raw.source_record s JOIN raw.source_batch b USING(source_batch_id)
                    WHERE b.source_table='brd_r3'
                      AND b.extraction_condition->>'version'='phase2.5-stored-history-v1'
                      AND b.extraction_condition->>'partition'>='2017-01'),
                lk AS (SELECT DISTINCT source_record_key FROM l),
                zk AS (SELECT DISTINCT source_record_key FROM z)
                SELECT (SELECT count(*) FROM zk LEFT JOIN lk USING(source_record_key)
                            WHERE lk.source_record_key IS NULL) AS unmatched_r3_keys,
                    (SELECT count(*) FROM lk LEFT JOIN zk USING(source_record_key)
                            WHERE zk.source_record_key IS NULL) AS unmatched_l3_keys,
                    (SELECT count(DISTINCT l.source_record_key) FROM l JOIN z USING(source_record_key)
                            WHERE l.player IS DISTINCT FROM z.player) AS registration_conflict_keys,
                    (SELECT count(DISTINCT l.source_record_key) FROM l JOIN z USING(source_record_key)
                            WHERE l.player IS DISTINCT FROM z.player AND nullif(btrim(z.player),'') IS NULL)
                        AS missing_r3_registration_keys,
                    (SELECT count(DISTINCT l.source_record_key) FROM l JOIN z USING(source_record_key)
                            WHERE l.player IS DISTINCT FROM z.player AND nullif(btrim(z.player),'') IS NOT NULL)
                        AS nonempty_registration_disagreement_keys'''),
        }

        emit('selected raw-to-canonical field lineage')
        report['raw_result_coverage'] = _row(cur, '''SELECT count(*) AS rows,
            count(*) FILTER (WHERE nullif(btrim(s.raw_payload->>'toroku_bango'),'') IS NULL) AS registration_blank,
            count(*) FILTER (WHERE nullif(btrim(s.raw_payload->>'chakujun'),'') IS NULL) AS finish_blank,
            count(*) FILTER (WHERE nullif(btrim(s.raw_payload->>'shinnyu_course'),'') IS NULL) AS actual_course_blank,
            count(*) FILTER (WHERE btrim(s.raw_payload->>'shinnyu_course') ~ '^0*[1-6]$') AS actual_course_1_to_6,
            count(*) FILTER (WHERE btrim(s.raw_payload->>'chakujun') ~ '^0*[1-6]$') AS finish_1_to_6,
            count(*) FILTER (WHERE nullif(btrim(s.raw_payload->>'st'),'') IS NULL) AS st_blank,
            count(*) FILTER (WHERE s.raw_payload->>'st' ~ '^[0-9]{3}$') AS three_digit_st_text
            FROM raw.source_record s JOIN raw.source_batch b USING(source_batch_id)
            WHERE b.source_table='brd_r3' AND b.extraction_condition->>'version'='phase2.5-stored-history-v1'
              AND b.extraction_condition->>'partition'>='2017-01' ''')
        report['raw_finish_codes'] = _rows(cur, '''SELECT s.raw_payload->>'chakujun' AS finish_raw,
            s.raw_payload->>'kigo' AS symbol_raw,count(*) AS rows
            FROM raw.source_record s JOIN raw.source_batch b USING(source_batch_id)
            WHERE b.source_table='brd_r3' AND b.extraction_condition->>'version'='phase2.5-stored-history-v1'
              AND b.extraction_condition->>'partition'>='2017-01'
            GROUP BY 1,2 ORDER BY 1,2''')
        report['source_codes'] = {
            'ki_sex_codes': _rows(cur, '''SELECT s.raw_payload->>'seibetsu_code' AS code,count(*) AS rows
                FROM raw.source_record s JOIN raw.source_batch b USING(source_batch_id)
                WHERE b.source_table='brd_ki' AND b.extraction_condition->>'version'='phase2.5-stored-history-v1'
                  AND b.extraction_condition->>'partition'>='2017'
                GROUP BY 1 ORDER BY 1'''),
            'ki_conflicting_known_sexes': _rows(cur, '''SELECT s.raw_payload->>'toroku_bango' AS player,
                    array_agg(DISTINCT s.raw_payload->>'seibetsu_code') AS codes,count(*) AS observations
                FROM raw.source_record s JOIN raw.source_batch b USING(source_batch_id)
                WHERE b.source_table='brd_ki' AND b.extraction_condition->>'version'='phase2.5-stored-history-v1'
                  AND b.extraction_condition->>'partition'>='2017'
                  AND s.raw_payload->>'seibetsu_code' IN ('1','2')
                GROUP BY 1 HAVING count(DISTINCT s.raw_payload->>'seibetsu_code')>1 ORDER BY 1'''),
            'grade_codes_by_year': _rows(cur, '''SELECT s.raw_payload->>'kaisai_nen' AS year,
                    s.raw_payload->>'grade_code' AS code,count(*) AS rows
                FROM raw.source_record s JOIN raw.source_batch b USING(source_batch_id)
                WHERE b.source_table='brd_l1' AND b.extraction_condition->>'version'='phase2.5-stored-history-v1'
                  AND b.extraction_condition->>'partition'>='2017-01'
                GROUP BY 1,2 ORDER BY 1,2'''),
            'finish_and_symbol_by_year': _rows(cur, '''SELECT extract(year FROM r.race_date)::int AS year,
                    z.finish_raw,z.result_symbol_raw,count(*) AS rows
                FROM core.race_result z JOIN core.race r USING(race_id)
                GROUP BY 1,2,3 ORDER BY 1,2,3'''),
            'l2_flags_by_year': _rows(cur, '''SELECT extract(year FROM race_date)::int AS year,
                    s.raw_payload->>'shinnyukotei' AS entry_fixed_code,
                    s.raw_payload->>'anteiban_shiyo' AS stabilizer_code,count(*) AS rows
                FROM core.race r JOIN raw.source_record s USING(source_record_id)
                GROUP BY 1,2,3 ORDER BY 1,2,3'''),
            'specification_change_note': 'Named DB columns only. Observed annual code distributions are evidence, not inferred new meanings.'
        }
        report['anomaly_examples'] = _rows(cur, '''SELECT DISTINCT ON (z.finish_raw,z.result_symbol_raw)
            r.race_date,r.venue_code,r.race_no,z.boat_no,z.finish_raw,z.result_symbol_raw,
            z.actual_course_raw,z.start_timing_raw,z.result_status,z.normalization_status,z.source_record_id
            FROM core.race_result z JOIN core.race r USING(race_id)
            WHERE z.result_status<>'NORMAL' OR z.normalization_status<>'NORMALIZED'
            ORDER BY z.finish_raw,z.result_symbol_raw,r.race_date,r.venue_code,r.race_no,z.boat_no''')
        report['race_level_value_duplicates'] = {
            'actual_course_groups':_row(cur, '''SELECT count(*) AS count FROM (
                SELECT race_id,actual_course FROM core.race_result WHERE actual_course IS NOT NULL
                GROUP BY race_id,actual_course HAVING count(*)>1) q''')['count'],
            'finish_position_groups':_row(cur, '''SELECT count(*) AS count FROM (
                SELECT race_id,finish_position FROM core.race_result WHERE finish_position IS NOT NULL
                GROUP BY race_id,finish_position HAVING count(*)>1) q''')['count'],
            'interpretation':'Preserve original observations; do not infer ties or repair courses.'
        }
        report['race_finish_completeness'] = {
            'numeric_finish_counts':_rows(cur, '''SELECT normal_finishes,count(*) AS races FROM (
                SELECT r.race_id,count(z.finish_position) AS normal_finishes
                FROM core.race r LEFT JOIN core.race_result z USING(race_id) GROUP BY r.race_id
                ) q GROUP BY normal_finishes ORDER BY normal_finishes'''),
            'six_result_rows_all_blank_finish':_row(cur, '''SELECT count(*) AS count FROM (
                SELECT race_id FROM core.race_result GROUP BY race_id
                HAVING count(*)=6 AND count(*) FILTER (WHERE nullif(btrim(finish_raw),'') IS NULL)=6
                ) q''')['count'],
            'interpretation':'Six source records do not imply a completed race; blank finishes are not assigned cancellation meaning.'
        }
        report['annual_field_coverage'] = {
            'results':_rows(cur, '''SELECT extract(year FROM r.race_date)::int AS year,count(*) AS rows,
                count(z.actual_course) AS actual_course,count(z.finish_position) AS numeric_finish,
                count(z.start_timing) AS numeric_st,
                count(*) FILTER (WHERE z.result_status IN ('F','L')) AS fl,
                count(*) FILTER (WHERE z.normalization_status='UNRESOLVED') AS unresolved
                FROM core.race_result z JOIN core.race r USING(race_id) GROUP BY 1 ORDER BY 1'''),
            'entries':_rows(cur, '''SELECT extract(year FROM r.race_date)::int AS year,count(*) AS rows,
                count(e.motor_id) AS motor,count(p.sex) AS sex
                FROM core.race_entry e JOIN core.race r USING(race_id) JOIN core.player p USING(player_id)
                GROUP BY 1 ORDER BY 1''')
        }
        report['lineage'] = {
            'wrong_source_table': _row(cur, '''
                SELECT
                  (SELECT count(*) FROM core.race c JOIN raw.source_record s USING(source_record_id)
                     JOIN raw.source_batch b USING(source_batch_id) WHERE b.source_table<>'brd_l2') AS race,
                  (SELECT count(*) FROM core.race_entry c JOIN raw.source_record s USING(source_record_id)
                     JOIN raw.source_batch b USING(source_batch_id) WHERE b.source_table<>'brd_l3') AS race_entry,
                  (SELECT count(*) FROM core.race_result c JOIN raw.source_record s USING(source_record_id)
                     JOIN raw.source_batch b USING(source_batch_id) WHERE b.source_table<>'brd_r3') AS race_result,
                  (SELECT count(*) FROM core.motor c JOIN raw.source_record s USING(source_record_id)
                     JOIN raw.source_batch b USING(source_batch_id) WHERE b.source_table<>'brd_l3') AS motor,
                  (SELECT count(*) FROM core.player c JOIN raw.source_record s USING(source_record_id)
                     JOIN raw.source_batch b USING(source_batch_id)
                     WHERE b.source_table NOT IN ('brd_ki','brd_l3')) AS player,
                  (SELECT count(*) FROM core.player c JOIN raw.source_record s
                     ON s.source_record_id=c.sex_source_record_id
                     JOIN raw.source_batch b USING(source_batch_id)
                     WHERE b.source_table<>'brd_ki') AS player_sex,
                  (SELECT count(*) FROM core.race c JOIN raw.source_record s
                     ON s.source_record_id=c.grade_source_record_id
                     JOIN raw.source_batch b USING(source_batch_id)
                     WHERE b.source_table<>'brd_l1') AS race_grade'''),
            'race_field_mismatches': _row(cur, '''
                SELECT count(*) AS count FROM core.race c
                JOIN raw.source_record s USING(source_record_id)
                WHERE s.raw_payload->>'kaisai_nen' IS DISTINCT FROM to_char(c.race_date,'YYYY')
                   OR s.raw_payload->>'kaisai_tsukihi' IS DISTINCT FROM to_char(c.race_date,'MMDD')
                   OR CASE WHEN btrim(s.raw_payload->>'kyoteijo_code') ~ '^[0-9]+$'
                                AND (btrim(s.raw_payload->>'kyoteijo_code'))::int BETWEEN 1 AND 24
                           THEN (btrim(s.raw_payload->>'kyoteijo_code'))::int END
                        IS DISTINCT FROM c.venue_code::int
                   OR CASE WHEN btrim(s.raw_payload->>'race_no') ~ '^[0-9]+$'
                                AND (btrim(s.raw_payload->>'race_no'))::int BETWEEN 1 AND 12
                           THEN (btrim(s.raw_payload->>'race_no'))::int END
                        IS DISTINCT FROM c.race_no::int''')['count'],
            'entry_field_mismatches': _row(cur, '''
                SELECT count(*) AS count FROM core.race_entry c
                JOIN raw.source_record s USING(source_record_id)
                WHERE CASE WHEN btrim(s.raw_payload->>'teiban') ~ '^[0-9]+$'
                                AND (btrim(s.raw_payload->>'teiban'))::int BETWEEN 1 AND 6
                           THEN (btrim(s.raw_payload->>'teiban'))::int END
                        IS DISTINCT FROM c.boat_no::int
                   OR CASE WHEN btrim(s.raw_payload->>'toroku_bango') ~ '^[0-9]+$'
                                AND (btrim(s.raw_payload->>'toroku_bango'))::numeric BETWEEN 1 AND 2147483647
                           THEN (btrim(s.raw_payload->>'toroku_bango'))::int END
                        IS DISTINCT FROM c.player_id
                   OR s.raw_payload->>'motor_no' IS DISTINCT FROM c.motor_no_raw
                   OR s.raw_payload->>'f_kaisu' IS DISTINCT FROM c.f_count_current_term_raw
                   OR s.raw_payload->>'l_kaisu' IS DISTINCT FROM c.l_count_current_term_raw''')['count'],
            'selected_entry_result_registration_conflicts': _row(cur, '''
                SELECT count(*) AS count FROM core.race_result z
                JOIN core.race_entry e USING(race_id,boat_no)
                JOIN raw.source_record ze ON ze.source_record_id=z.source_record_id
                JOIN raw.source_record ee ON ee.source_record_id=e.source_record_id
                WHERE ze.raw_payload->>'toroku_bango'
                    IS DISTINCT FROM ee.raw_payload->>'toroku_bango' ''')['count'],
            'result_raw_field_mismatches': _row(cur, '''
                SELECT count(*) AS count FROM core.race_result c
                JOIN raw.source_record s USING(source_record_id)
                WHERE s.raw_payload->>'shinnyu_course' IS DISTINCT FROM c.actual_course_raw
                   OR s.raw_payload->>'chakujun' IS DISTINCT FROM c.finish_raw
                   OR s.raw_payload->>'kigo' IS DISTINCT FROM c.result_symbol_raw
                   OR s.raw_payload->>'st' IS DISTINCT FROM c.start_timing_raw
                   OR CASE WHEN btrim(s.raw_payload->>'teiban') ~ '^[0-9]+$'
                                AND (btrim(s.raw_payload->>'teiban'))::int BETWEEN 1 AND 6
                           THEN (btrim(s.raw_payload->>'teiban'))::int END
                        IS DISTINCT FROM c.boat_no::int''')['count'],
            'result_typed_field_mismatches': _row(cur, '''
                SELECT count(*) AS count FROM core.race_result c
                JOIN raw.source_record s USING(source_record_id)
                WHERE CASE WHEN btrim(s.raw_payload->>'shinnyu_course') ~ '^[0-9]+$'
                           THEN CASE WHEN (btrim(s.raw_payload->>'shinnyu_course'))::numeric BETWEEN 1 AND 6
                                THEN (btrim(s.raw_payload->>'shinnyu_course'))::int END END
                          IS DISTINCT FROM c.actual_course::int
                   OR CASE WHEN btrim(s.raw_payload->>'chakujun') ~ '^[0-9]+$'
                           THEN CASE WHEN (btrim(s.raw_payload->>'chakujun'))::numeric BETWEEN 1 AND 6
                                THEN (btrim(s.raw_payload->>'chakujun'))::int END END
                          IS DISTINCT FROM c.finish_position::int
                   OR CASE WHEN c.start_timing_status='NORMAL'
                                AND s.raw_payload->>'st' ~ '^[0-9]{3}$'
                           THEN (s.raw_payload->>'st')::numeric/100 END
                          IS DISTINCT FROM c.start_timing''')['count'],
            'player_identity_mismatches': _row(cur, '''
                SELECT count(*) AS count FROM core.player c
                JOIN raw.source_record s USING(source_record_id)
                JOIN raw.source_batch b USING(source_batch_id)
                WHERE CASE WHEN btrim(s.raw_payload->>'toroku_bango') ~ '^[0-9]+$'
                                AND (btrim(s.raw_payload->>'toroku_bango'))::numeric BETWEEN 1 AND 2147483647
                           THEN (btrim(s.raw_payload->>'toroku_bango'))::int END
                        IS DISTINCT FROM c.player_id
                   OR CASE WHEN b.source_table='brd_ki' THEN s.raw_payload->>'shimei_kanji'
                           WHEN b.source_table='brd_l3' THEN s.raw_payload->>'shimei' END
                          IS DISTINCT FROM c.player_name_raw''')['count'],
            'player_sex_mismatches': _row(cur, '''
                SELECT count(*) AS count FROM core.player c
                LEFT JOIN raw.source_record s ON s.source_record_id=c.sex_source_record_id
                WHERE (c.sex IS NOT NULL AND s.source_record_id IS NULL)
                   OR CASE s.raw_payload->>'seibetsu_code'
                          WHEN '1' THEN 'MALE' WHEN '2' THEN 'FEMALE' END
                        IS DISTINCT FROM c.sex
                   OR s.raw_payload->>'seibetsu_code' IS DISTINCT FROM c.sex_raw''')['count'],
            'selected_ki_outside_history_scope': _row(cur, '''
                SELECT count(*) AS count FROM core.player c
                JOIN raw.source_record s ON s.source_record_id=c.sex_source_record_id
                JOIN raw.source_batch b USING(source_batch_id)
                WHERE (b.extraction_condition->>'version'='phase2.5-stored-history-v1'
                  AND b.source_table='brd_ki'
                  AND (b.extraction_condition->>'partition'>='2017'
                       OR b.extraction_condition->>'partition'='identity-before-2017')) IS NOT TRUE''')['count'],
            'race_grade_mismatches': _row(cur, '''
                SELECT count(*) AS count FROM core.race c
                LEFT JOIN raw.source_record s ON s.source_record_id=c.grade_source_record_id
                WHERE s.raw_payload->>'grade_code' IS DISTINCT FROM c.grade_raw''')['count'],
            'motor_source_mismatches': _row(cur, '''
                SELECT count(*) AS count FROM core.motor c
                JOIN raw.source_record s USING(source_record_id)
                WHERE CASE WHEN btrim(s.raw_payload->>'motor_no') ~ '^[0-9]+$'
                                AND (btrim(s.raw_payload->>'motor_no'))::numeric BETWEEN 1 AND 2147483647
                           THEN (btrim(s.raw_payload->>'motor_no'))::int END IS DISTINCT FROM c.motor_no
                   OR CASE WHEN btrim(s.raw_payload->>'kyoteijo_code') ~ '^[0-9]+$'
                                AND (btrim(s.raw_payload->>'kyoteijo_code'))::int BETWEEN 1 AND 24
                           THEN (btrim(s.raw_payload->>'kyoteijo_code'))::int END
                        IS DISTINCT FROM c.venue_code::int
                   OR (s.raw_payload->>'kaisai_nen')||(s.raw_payload->>'kaisai_tsukihi')
                        < to_char(c.generation_start_date,'YYYYMMDD')
                   OR (s.raw_payload->>'kaisai_nen')||(s.raw_payload->>'kaisai_tsukihi')
                        >= to_char(c.generation_end_date,'YYYYMMDD')''')['count'],
            'dataset_manifest_missing_records': _row(cur, '''
                SELECT count(*) AS count FROM core.dataset_version d
                CROSS JOIN LATERAL jsonb_array_elements(d.source_manifest->'records') item
                LEFT JOIN raw.source_record s
                  ON s.source_record_id=(item->>'source_record_id')::bigint
                WHERE s.source_record_id IS NULL
                   OR s.record_hash IS DISTINCT FROM item->>'record_hash' ''')['count'],
        }

        cur.execute('SELECT venue_code,generation_start_year,generation_start_date,generation_end_date,'
                    'identity_rule_version FROM core.motor')
        motor_rule_mismatches=0
        for row in cur.fetchall():
            expected=motor_generation(row['venue_code'],row['generation_start_date'])
            if expected!=(row['generation_start_year'],row['generation_start_date'],row['generation_end_date']) \
                    or row['identity_rule_version']!=MOTOR_RULE_VERSION:
                motor_rule_mismatches+=1
        report['motors']['fixed_rule_mismatches']=motor_rule_mismatches
        blocking = {
            'forbidden_numeric_fl':report['result_distributions']['numeric_start_summary']['forbidden_numeric_fl'],
            'fixed_motor_rule_mismatches':motor_rule_mismatches,
            'canonical_races_before_scope': report['canonical']['race_range']['races_before_scope'],
            'future_or_same_year_ki': report['players']['future_or_same_year_ki']['blocking_count'],
            'invalid_ki_year': report['players']['future_or_same_year_ki']['invalid_year'],
            'result_present_status_not_six_results':
                report['race_completeness']['result_present_status_not_six_results'],
            'invalid_motor_intervals': report['motors']['invalid_generation_intervals'],
            'entries_outside_motor_interval': report['motors']['entries_outside_motor_interval'],
            'incomplete_raw_batches': report['raw_sources']['incomplete_batches'],
            'ambiguous_phase_2_5_partitions': report['raw_sources']['ambiguous_phase_2_5_partitions'],
            'selected_registration_conflicts': report['lineage']['selected_entry_result_registration_conflicts'],
            'race_lineage_mismatches': report['lineage']['race_field_mismatches'],
            'entry_lineage_mismatches': report['lineage']['entry_field_mismatches'],
            'result_raw_lineage_mismatches': report['lineage']['result_raw_field_mismatches'],
            'result_typed_lineage_mismatches': report['lineage']['result_typed_field_mismatches'],
            'player_lineage_mismatches': report['lineage']['player_identity_mismatches'],
            'player_sex_lineage_mismatches': report['lineage']['player_sex_mismatches'],
            'selected_ki_outside_history_scope':
                report['lineage']['selected_ki_outside_history_scope'],
            'race_grade_lineage_mismatches': report['lineage']['race_grade_mismatches'],
            'motor_lineage_mismatches': report['lineage']['motor_source_mismatches'],
            'dataset_manifest_missing_records': report['lineage']['dataset_manifest_missing_records'],
        }
        # Missing entries/results remain visible above but are not integrity blockers:
        # SOURCE_INCOMPLETE races and excluded conflicting results are intentional.
        blocking['wrong_source_table_total'] = sum(report['lineage']['wrong_source_table'].values())
        blocking['duplicate_canonical_keys'] = sum(
            report['duplicates_and_required_missing'][name] for name in (
                'duplicate_race_natural_keys', 'duplicate_entry_keys', 'duplicate_result_keys'))
        blocking['required_key_missing'] = sum(
            row['rows'] for row in report['duplicates_and_required_missing']['required_key_missing'])
        report['blocking_findings'] = blocking
        report['status'] = 'PASS' if all(value == 0 for value in blocking.values()) else 'BLOCKING'
        emit('audit report complete')
        return _json_value(report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args()
    connection = target_connection(args.config)
    try:
        # Preserve the verified SET ROLE and allow full-history aggregate scans;
        # the audit transaction itself is still explicitly read-only.
        with connection.cursor() as cur:
            cur.execute("SET statement_timeout='0'")
        connection.commit()
        def progress(message):
            stamp = datetime.now().astimezone().isoformat(timespec='seconds')
            print(f'[{stamp}] {message}', file=sys.stderr, flush=True)
        print(json.dumps(audit(connection, progress=progress), indent=2, ensure_ascii=False))
    finally:
        connection.rollback()
        connection.close()


if __name__ == '__main__':
    main()
