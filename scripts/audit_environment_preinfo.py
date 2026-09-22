"""Read-only Phase 3C audit of preserved C2/C3 and their Canonical projection."""
import argparse
from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sys

from psycopg2.extras import RealDictCursor

from scripts.db import DEFAULT_CONFIG, target_connection
from scripts.foundation import canonical_json


VERSION = 'phase3c-environment-preinfo-v1'
TABLES = ('brd_c2', 'brd_c3')
KEYS = {
    'brd_c2': ('kaisai_nen', 'kaisai_tsukihi', 'kyoteijo_code', 'race_no'),
    'brd_c3': ('kaisai_nen', 'kaisai_tsukihi', 'kyoteijo_code', 'race_no', 'teiban'),
}
EXPECTED = {
    'brd_c2': {'rows': 542003, 'races': 542003},
    'brd_c3': {'rows': 3252018, 'races': 542003},
    'core_races': 542160,
    'core_entries': 3252960,
    'missing_races': 157,
    'environment_rows': 542003,
    'boat_rows': 3252018,
    'course': {'VALID': 3206994, 'MISSING': 45024},
    'exhibition_time': {'VALID': 3207528, 'SOURCE_SENTINEL': 44490},
    'tilt': {'VALID': 3209860, 'MISSING': 42158},
    'start_symbol': {'F': 706149, 'L': 478},
    'environment_status': {
        'air_temperature_valid': 535384, 'air_temperature_missing': 6619,
        'water_temperature_valid': 535384, 'water_temperature_missing': 6619,
        'weather_valid': 541518, 'weather_missing': 485,
        'wind_direction_valid': 499760, 'wind_direction_missing': 42243,
        'venue_direction_valid': 542003, 'venue_direction_missing': 0,
        'wind_speed_unresolved': 535384, 'wind_speed_missing': 6619,
        'wave_height_unresolved': 535382, 'wave_height_missing': 6621,
        'surface_marker_unresolved': 44807, 'surface_marker_missing': 497196,
    },
    'start_status': {'VALID': 2500360, 'MISSING': 45031, 'F': 706149, 'L': 478},
}


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


def rows(cur, query, params=()):
    cur.execute(query, params)
    return [_json_value(dict(row)) for row in cur.fetchall()]


def row(cur, query, params=()):
    result = rows(cur, query, params)
    if len(result) != 1:
        raise RuntimeError('audit query did not return exactly one row')
    return result[0]


def raw_hash_audit(connection, progress):
    """Recompute every row and batch hash with bounded client memory."""
    report = {'tables': {}}
    with connection.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute('''SELECT source_batch_id,source_table,source_type,source_locator,
                source_name,source_database,source_schema,retrieved_at,
                extraction_condition,metadata,status,row_count,content_hash
            FROM raw.source_batch
            WHERE source_table=ANY(%s) AND extraction_condition->>'version'=%s
            ORDER BY source_table,extraction_condition->>'partition',source_batch_id''',
            (list(TABLES), VERSION))
        batches = [dict(item) for item in cur.fetchall()]
    for table in TABLES:
        selected = [batch for batch in batches if batch['source_table'] == table]
        table_report = {'batches': len(selected), 'rows': 0, 'races': 0,
                        'row_hash_mismatches': 0, 'batch_hash_mismatches': 0,
                        'record_key_mismatches': 0, 'position_mismatches': 0,
                        'order_mismatches': 0, 'partition_mismatches': 0,
                        'batch_contract_mismatches': 0,
                        'out_of_scope_records': 0, 'first_date': None, 'last_date': None}
        venues = set()
        partitions = [batch['extraction_condition'].get('partition') for batch in selected]
        table_report['duplicate_batch_partitions'] = len(partitions) - len(set(partitions))
        for batch_index, batch in enumerate(selected):
            expected_condition = {
                'version': VERSION,
                'partition': batch['extraction_condition'].get('partition'),
                'order_by': list(KEYS[table]),
            }
            if (batch['source_type'] != 'SOURCE_DB_EXTRACT'
                    or batch['source_name'] != 'PC-KYOTEI'
                    or batch['source_database'] != 'pckyotei'
                    or batch['source_schema'] != 'public'
                    or batch['retrieved_at'] is not None
                    or batch['source_locator'] != 'pckyotei.public.' + table
                    or batch['extraction_condition'] != expected_condition
                    or batch['status'] not in ('PRESERVED', 'SOURCE_EMPTY')
                    or (batch['row_count'] == 0) != (batch['status'] == 'SOURCE_EMPTY')
                    or batch['metadata'].get('phase') != '3C'
                    or batch['metadata'].get('transaction_read_only') != 'on'
                    or batch['metadata'].get('prediction_availability_policy') != 'PRE_RACE_SOURCE_CLASS_USER_POLICY'
                    or batch['metadata'].get('historical_exact_asof') != 'NOT_VERIFIED'):
                table_report['batch_contract_mismatches'] += 1
            batch_hash = hashlib.sha256(b'[')
            count = 0
            previous_key = None
            cursor_name = f'phase3c_hash_{table}_{batch_index}'
            with connection.cursor(name=cursor_name, cursor_factory=RealDictCursor) as cur:
                cur.itersize = 10000
                cur.execute('''SELECT source_record_key,source_position,raw_payload,record_hash
                    FROM raw.source_record WHERE source_batch_id=%s ORDER BY source_position''',
                    (batch['source_batch_id'],))
                for record in cur:
                    count += 1
                    payload = record['raw_payload']
                    source_day = payload.get('kaisai_nen', '') + payload.get('kaisai_tsukihi', '')
                    if len(source_day) != 8 or not source_day.isascii() or not source_day.isdigit() or source_day < '20170101':
                        table_report['out_of_scope_records'] += 1
                    if table_report['first_date'] is None or source_day < table_report['first_date']:
                        table_report['first_date'] = source_day
                    if table_report['last_date'] is None or source_day > table_report['last_date']:
                        table_report['last_date'] = source_day
                    venues.add(payload.get('kyoteijo_code'))
                    encoded = canonical_json(payload).encode('utf-8')
                    if hashlib.sha256(encoded).hexdigest() != record['record_hash']:
                        table_report['row_hash_mismatches'] += 1
                    expected_key = {key: payload.get(key) for key in KEYS[table]}
                    if record['source_record_key'] != expected_key:
                        table_report['record_key_mismatches'] += 1
                    sortable_key = canonical_json([payload.get(key) for key in KEYS[table]])
                    if previous_key is not None and sortable_key <= previous_key:
                        table_report['order_mismatches'] += 1
                    previous_key = sortable_key
                    if (payload.get('kaisai_nen', '') + '-' +
                            payload.get('kaisai_tsukihi', '')[:2]
                            != batch['extraction_condition'].get('partition')):
                        table_report['partition_mismatches'] += 1
                    if record['source_position'] != count:
                        table_report['position_mismatches'] += 1
                    if count > 1:
                        batch_hash.update(b',')
                    batch_hash.update(encoded)
            batch_hash.update(b']')
            if count != batch['row_count'] or batch_hash.hexdigest() != batch['content_hash']:
                table_report['batch_hash_mismatches'] += 1
            table_report['rows'] += count
            if (batch_index + 1) % 12 == 0:
                progress(f"{table}: hashed {batch_index + 1}/{len(selected)} batches, {table_report['rows']} rows")
        with connection.cursor(cursor_factory=RealDictCursor) as cur:
            if table == 'brd_c2':
                cur.execute('''SELECT count(*) AS rows,count(DISTINCT s.source_record_key) AS keys,
                    count(*) FILTER (WHERE s.interpretation_status<>'PRESERVED') AS wrong_record_status
                    FROM raw.source_record s JOIN raw.source_batch b USING(source_batch_id)
                    WHERE b.source_table=%s AND b.extraction_condition->>'version'=%s''',
                    (table, VERSION))
            else:
                cur.execute('''SELECT count(*) AS rows,count(DISTINCT s.source_record_key) AS keys,
                    count(*) FILTER (WHERE s.interpretation_status<>'PRESERVED') AS wrong_record_status
                    FROM raw.source_record s JOIN raw.source_batch b USING(source_batch_id)
                    WHERE b.source_table=%s AND b.extraction_condition->>'version'=%s''',
                    (table, VERSION))
            key_counts = dict(cur.fetchone())
            cur.execute('''SELECT count(DISTINCT jsonb_build_object(
                    'kaisai_nen',s.raw_payload->>'kaisai_nen',
                    'kaisai_tsukihi',s.raw_payload->>'kaisai_tsukihi',
                    'kyoteijo_code',s.raw_payload->>'kyoteijo_code',
                    'race_no',s.raw_payload->>'race_no')) AS races
                FROM raw.source_record s JOIN raw.source_batch b USING(source_batch_id)
                WHERE b.source_table=%s AND b.extraction_condition->>'version'=%s''',
                (table, VERSION))
            table_report['races'] = cur.fetchone()['races']
        table_report['duplicate_natural_keys'] = key_counts['rows'] - key_counts['keys']
        table_report['wrong_record_status'] = key_counts['wrong_record_status']
        table_report['venues'] = sorted(venues, key=str)
        table_report['unexpected_period_or_venues'] = int(
            table_report['first_date'] != '20170101' or table_report['last_date'] != '20260918'
            or venues != {str(v).zfill(2) for v in range(1,25)})
        report['tables'][table] = table_report
        progress(f'raw hashes complete: {table}')
    return report


def audit(connection, progress=None):
    emit = progress or (lambda _message: None)
    with connection.cursor(cursor_factory=RealDictCursor) as cur:
        # First statements in this transaction: fail closed against all writes.
        cur.execute('SET TRANSACTION READ ONLY')
        cur.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ')
        cur.execute("SET LOCAL statement_timeout='15min'")
        cur.execute("SET LOCAL lock_timeout='5s'")
        cur.execute("SET LOCAL work_mem='64MB'")
        cur.execute("SELECT current_setting('transaction_read_only') AS read_only")
        if cur.fetchone()['read_only'] != 'on':
            raise RuntimeError('audit transaction is not read-only')

    emit('recompute all raw hashes')
    report = {
        'audit_version': 'PHASE_3C_ENVIRONMENT_PREINFO_AUDIT_V1',
        'normalization_version': VERSION,
        'transaction_read_only': 'on',
        'scope': {'date_start': '2017-01-01', 'sources': list(TABLES),
                  'c4': 'UNTOUCHED_NOT_IMPORTED'},
        'raw': raw_hash_audit(connection, emit),
    }

    # Canonical checks are below the hash pass so failures still identify raw integrity.
    with connection.cursor(cursor_factory=RealDictCursor) as cur:
        emit('canonical coverage and independent replay')
        report.update(canonical_audit(cur))
        report['frozen'] = frozen_audit(cur)
        report['mutation_check'] = (
            'Transaction was READ ONLY; original six-table before/after fingerprints '
            'are produced by scripts.apply_environment_preinfo.')

    blockers = {}
    for table in TABLES:
        actual = report['raw']['tables'][table]
        for name in ('row_hash_mismatches', 'batch_hash_mismatches',
                     'record_key_mismatches', 'position_mismatches',
                     'order_mismatches', 'partition_mismatches',
                     'batch_contract_mismatches', 'duplicate_natural_keys',
                     'duplicate_batch_partitions', 'wrong_record_status',
                     'out_of_scope_records', 'unexpected_period_or_venues'):
            blockers[f'{table}_{name}'] = actual[name]
        blockers[f'{table}_unexpected_rows'] = int(actual['rows'] != EXPECTED[table]['rows'])
        blockers[f'{table}_unexpected_races'] = int(actual['races'] != EXPECTED[table]['races'])
    for name, value in report['canonical']['blocking'].items():
        blockers[name] = value
    for name, value in report['frozen']['blocking'].items():
        blockers[name] = value
    report['blocking_findings'] = blockers
    report['status'] = 'PASS' if all(value == 0 for value in blockers.values()) else 'BLOCKING'
    return _json_value(report)


def canonical_audit(cur):
    """Independently replay Canonical fields from the preserved payloads."""
    coverage = {
        'environment': rows(cur, '''SELECT extract(year FROM race_date)::int AS year,
            venue_code,coverage_status,count(*) AS races
            FROM core.race_environment_preinfo_status
            GROUP BY 1,2,3 ORDER BY 1,2,3'''),
        'boat': rows(cur, '''SELECT extract(year FROM race_date)::int AS year,
            venue_code,coverage_status,count(*) AS boats
            FROM core.race_boat_preinfo_status
            GROUP BY 1,2,3 ORDER BY 1,2,3'''),
    }
    missing = rows(cur, '''SELECT race_date,venue_code,race_no
        FROM core.race_environment_preinfo_status WHERE coverage_status='MISSING_SOURCE'
        ORDER BY 1,2,3''')
    missing_shape = row(cur, '''SELECT count(*) AS missing_races,
        count(*) FILTER (WHERE (race_date=DATE '2022-04-09' AND venue_code=16 AND race_no=4)
          OR race_date=DATE '2026-09-19') AS expected_missing_races,
        (SELECT count(*) FROM core.race_environment_preinfo_status
          WHERE coverage_status NOT IN ('AVAILABLE','MISSING_SOURCE')) AS invalid_status
        FROM core.race_environment_preinfo_status WHERE coverage_status='MISSING_SOURCE' ''')
    missing_set = row(cur, '''WITH actual AS (
          SELECT race_date,venue_code,race_no FROM core.race_environment_preinfo_status
          WHERE coverage_status='MISSING_SOURCE'
        ), expected AS (
          SELECT race_date,venue_code,race_no FROM core.race
          WHERE race_date=DATE '2026-09-19'
             OR (race_date=DATE '2022-04-09' AND venue_code=16 AND race_no=4)
        )
        SELECT (SELECT count(*) FROM (SELECT * FROM actual EXCEPT SELECT * FROM expected) q)
                 AS unexpected_missing,
               (SELECT count(*) FROM (SELECT * FROM expected EXCEPT SELECT * FROM actual) q)
                 AS expected_not_missing''')
    totals = row(cur, '''SELECT
        (SELECT count(*) FROM core.race) AS core_races,
        (SELECT count(*) FROM core.race_entry) AS core_entries,
        (SELECT count(*) FROM core.race_environment_preinfo) AS environment_rows,
        (SELECT count(*) FROM core.race_boat_preinfo) AS boat_rows,
        (SELECT count(*) FROM core.race_environment_preinfo_status
          WHERE coverage_status='AVAILABLE') AS available_races,
        (SELECT count(*) FROM core.race_environment_preinfo_status
          WHERE coverage_status='MISSING_SOURCE') AS missing_races,
        (SELECT count(*) FROM core.race_boat_preinfo_status
          WHERE coverage_status='AVAILABLE') AS available_boats,
        (SELECT count(*) FROM core.race_boat_preinfo_status
          WHERE coverage_status='MISSING_SOURCE') AS missing_boats''')
    six_boats = row(cur, '''SELECT
        count(*) FILTER (WHERE boats<>6) AS races_not_six_boats,
        count(*) AS races FROM (
          SELECT race_id,count(*) AS boats FROM core.race_boat_preinfo GROUP BY race_id
        ) q''')

    environment_replay = row(cur, '''SELECT count(*) AS rows,
        count(*) FILTER (WHERE b.source_table IS DISTINCT FROM 'brd_c2'
          OR b.source_type IS DISTINCT FROM 'SOURCE_DB_EXTRACT') AS wrong_source,
        count(*) FILTER (WHERE p.normalization_version IS DISTINCT FROM %s) AS wrong_version,
        count(*) FILTER (WHERE s.source_record_id IS NULL OR b.source_batch_id IS NULL) AS missing_lineage,
        count(*)-count(DISTINCT p.source_record_id) AS duplicate_source_record_ids,
        count(*)-count(DISTINCT p.race_id) AS duplicate_canonical_keys,
        count(*) FILTER (WHERE r.race_date IS DISTINCT FROM
              make_date((x.kaisai_nen)::int,left(x.kaisai_tsukihi,2)::int,right(x.kaisai_tsukihi,2)::int)
          OR r.venue_code IS DISTINCT FROM (x.kyoteijo_code)::int
          OR r.race_no IS DISTINCT FROM (x.race_no)::int) AS identity_mismatch,
        count(*) FILTER (WHERE s.source_record_key IS DISTINCT FROM jsonb_build_object(
          'kaisai_nen',x.kaisai_nen,'kaisai_tsukihi',x.kaisai_tsukihi,
          'kyoteijo_code',x.kyoteijo_code,'race_no',x.race_no)) AS record_key_mismatch,
        count(*) FILTER (WHERE p.air_temperature_raw IS DISTINCT FROM x.kion
          OR p.water_temperature_raw IS DISTINCT FROM x.suion
          OR p.weather_code_raw IS DISTINCT FROM x.tenki_code
          OR p.wind_direction_code_raw IS DISTINCT FROM x.fuko_code
          OR p.venue_direction_code_raw IS DISTINCT FROM x.hogaku_code
          OR p.wind_speed_raw IS DISTINCT FROM x.fusoku
          OR p.wave_height_raw IS DISTINCT FROM x.hako
          OR p.surface_weather_marker_raw IS DISTINCT FROM x.suimenkisho_joho) AS raw_mismatch,
        count(*) FILTER (WHERE
          p.air_temperature_status IS DISTINCT FROM CASE WHEN x.kion IS NULL OR btrim(x.kion)='' THEN 'MISSING' WHEN x.kion ~ '^([0-9]{3}|-[0-9]{2})$' THEN 'VALID' ELSE 'INVALID' END
          OR p.air_temperature_c IS DISTINCT FROM CASE WHEN x.kion ~ '^([0-9]{3}|-[0-9]{2})$' THEN x.kion::numeric/10 END
          OR p.water_temperature_status IS DISTINCT FROM CASE WHEN x.suion IS NULL OR btrim(x.suion)='' THEN 'MISSING' WHEN x.suion ~ '^([0-9]{3}|-[0-9]{2})$' THEN 'VALID' ELSE 'INVALID' END
          OR p.water_temperature_c IS DISTINCT FROM CASE WHEN x.suion ~ '^([0-9]{3}|-[0-9]{2})$' THEN x.suion::numeric/10 END
          OR p.weather_status IS DISTINCT FROM CASE WHEN x.tenki_code IS NULL OR btrim(x.tenki_code)='' THEN 'MISSING' WHEN x.tenki_code ~ '^[1-6]$' THEN 'VALID' ELSE 'INVALID' END
          OR p.weather_code IS DISTINCT FROM CASE WHEN x.tenki_code ~ '^[1-6]$' THEN x.tenki_code::int END
          OR p.wind_direction_status IS DISTINCT FROM CASE WHEN x.fuko_code IS NULL OR btrim(x.fuko_code)='' THEN 'MISSING' WHEN x.fuko_code ~ '^(0[1-9]|1[0-6])$' THEN 'VALID' ELSE 'INVALID' END
          OR p.wind_direction_code IS DISTINCT FROM CASE WHEN x.fuko_code ~ '^(0[1-9]|1[0-6])$' THEN x.fuko_code::int END
          OR p.venue_direction_status IS DISTINCT FROM CASE WHEN x.hogaku_code IS NULL OR btrim(x.hogaku_code)='' THEN 'MISSING' WHEN x.hogaku_code ~ '^(0[1-9]|1[0-6])$' THEN 'VALID' ELSE 'INVALID' END
          OR p.venue_direction_code IS DISTINCT FROM CASE WHEN x.hogaku_code ~ '^(0[1-9]|1[0-6])$' THEN x.hogaku_code::int END
          OR p.wind_speed_status IS DISTINCT FROM CASE WHEN x.fusoku IS NULL OR btrim(x.fusoku)='' THEN 'MISSING' ELSE 'UNRESOLVED' END
          OR p.wave_height_status IS DISTINCT FROM CASE WHEN x.hako IS NULL OR btrim(x.hako)='' THEN 'MISSING' ELSE 'UNRESOLVED' END
          OR p.surface_weather_marker_status IS DISTINCT FROM CASE WHEN x.suimenkisho_joho IS NULL OR btrim(x.suimenkisho_joho)='' THEN 'MISSING' ELSE 'UNRESOLVED' END) AS value_status_mismatch,
        count(*) FILTER (WHERE p.provenance->>'normalization_version' IS DISTINCT FROM %s
          OR p.provenance->>'source_table' IS DISTINCT FROM 'brd_c2'
          OR p.provenance->>'information_kind' IS DISTINCT FROM 'PRE_RACE_SOURCE_CLASS'
          OR p.provenance->>'historical_availability_status' IS DISTINCT FROM 'SOURCE_CLASS_POLICY_NOT_EXACT_AS_OF_PROOF'
          OR p.provenance->'result_dependency' IS DISTINCT FROM 'false'::jsonb
          OR p.provenance->'source_fields' IS DISTINCT FROM
             '["kion","suion","tenki_code","fuko_code","hogaku_code","fusoku","hako","suimenkisho_joho"]'::jsonb) AS provenance_mismatch
        FROM core.race_environment_preinfo p JOIN core.race r USING(race_id)
        LEFT JOIN raw.source_record s ON s.source_record_id=p.source_record_id
        LEFT JOIN raw.source_batch b ON b.source_batch_id=s.source_batch_id
        CROSS JOIN LATERAL jsonb_to_record(s.raw_payload) AS x(
          kaisai_nen text,kaisai_tsukihi text,kyoteijo_code text,race_no text,
          kion text,suion text,tenki_code text,fuko_code text,hogaku_code text,
          fusoku text,hako text,suimenkisho_joho text)''', (VERSION, VERSION))

    boat_replay = row(cur, '''SELECT count(*) AS rows,
        count(*) FILTER (WHERE b.source_table IS DISTINCT FROM 'brd_c3'
          OR b.source_type IS DISTINCT FROM 'SOURCE_DB_EXTRACT') AS wrong_source,
        count(*) FILTER (WHERE p.normalization_version IS DISTINCT FROM %s) AS wrong_version,
        count(*) FILTER (WHERE s.source_record_id IS NULL OR b.source_batch_id IS NULL) AS missing_lineage,
        count(*)-count(DISTINCT p.source_record_id) AS duplicate_source_record_ids,
        count(*)-count(DISTINCT (p.race_id,p.boat_no)) AS duplicate_canonical_keys,
        count(*) FILTER (WHERE r.race_date IS DISTINCT FROM
              make_date((x.kaisai_nen)::int,left(x.kaisai_tsukihi,2)::int,right(x.kaisai_tsukihi,2)::int)
          OR r.venue_code IS DISTINCT FROM (x.kyoteijo_code)::int
          OR r.race_no IS DISTINCT FROM (x.race_no)::int
          OR p.boat_no IS DISTINCT FROM (x.teiban)::int) AS identity_mismatch,
        count(*) FILTER (WHERE s.source_record_key IS DISTINCT FROM jsonb_build_object(
          'kaisai_nen',x.kaisai_nen,'kaisai_tsukihi',x.kaisai_tsukihi,
          'kyoteijo_code',x.kyoteijo_code,'race_no',x.race_no,'teiban',x.teiban)) AS record_key_mismatch,
        count(*) FILTER (WHERE p.exhibition_time_raw IS DISTINCT FROM x.tenji_time
          OR p.tilt_raw IS DISTINCT FROM x.tilt
          OR p.exhibition_course_raw IS DISTINCT FROM x.tenji_shinnyu_course
          OR p.exhibition_start_timing_raw IS DISTINCT FROM x.tenji_st
          OR p.exhibition_start_symbol_raw IS DISTINCT FROM x.tenji_kigo) AS raw_mismatch,
        count(*) FILTER (WHERE
          p.exhibition_time_status IS DISTINCT FROM CASE WHEN x.tenji_time IS NULL OR btrim(x.tenji_time)='' THEN 'MISSING' WHEN x.tenji_time='0000' THEN 'SOURCE_SENTINEL' WHEN x.tenji_time ~ '^[0-9]{4}$' THEN 'VALID' ELSE 'INVALID' END
          OR p.exhibition_time_seconds IS DISTINCT FROM CASE WHEN x.tenji_time ~ '^[0-9]{4}$' AND x.tenji_time<>'0000' THEN x.tenji_time::numeric/100 END
          OR p.tilt_status IS DISTINCT FROM CASE WHEN x.tilt IS NULL OR btrim(x.tilt)='' THEN 'MISSING' WHEN btrim(x.tilt) ~ '^-?[0-9]{2}$' THEN 'VALID' ELSE 'INVALID' END
          OR p.tilt_degrees IS DISTINCT FROM CASE WHEN btrim(x.tilt) ~ '^-?[0-9]{2}$' THEN btrim(x.tilt)::numeric/10 END
          OR p.exhibition_course_status IS DISTINCT FROM CASE WHEN x.tenji_shinnyu_course IS NULL OR btrim(x.tenji_shinnyu_course)='' THEN 'MISSING' WHEN btrim(x.tenji_shinnyu_course) ~ '^[1-6]$' THEN 'VALID' ELSE 'INVALID' END
          OR p.exhibition_course IS DISTINCT FROM CASE WHEN btrim(x.tenji_shinnyu_course) ~ '^[1-6]$' THEN btrim(x.tenji_shinnyu_course)::int END
          OR p.exhibition_start_status IS DISTINCT FROM CASE WHEN btrim(coalesce(x.tenji_kigo,''))='F' THEN 'F' WHEN btrim(coalesce(x.tenji_kigo,''))='L' THEN 'L' WHEN btrim(coalesce(x.tenji_kigo,''))<>'' THEN 'UNRESOLVED_SYMBOL' WHEN x.tenji_st IS NULL OR btrim(x.tenji_st)='' THEN 'MISSING' WHEN x.tenji_st ~ '^[0-9]{3}$' THEN 'VALID' ELSE 'INVALID' END
          OR p.exhibition_start_timing IS DISTINCT FROM CASE WHEN btrim(coalesce(x.tenji_kigo,''))='' AND x.tenji_st ~ '^[0-9]{3}$' THEN x.tenji_st::numeric/100 END) AS value_status_mismatch,
        count(*) FILTER (WHERE p.provenance->>'normalization_version' IS DISTINCT FROM %s
          OR p.provenance->>'source_table' IS DISTINCT FROM 'brd_c3'
          OR p.provenance->>'information_kind' IS DISTINCT FROM 'PRE_RACE_SOURCE_CLASS'
          OR p.provenance->>'historical_availability_status' IS DISTINCT FROM 'SOURCE_CLASS_POLICY_NOT_EXACT_AS_OF_PROOF'
          OR p.provenance->'result_dependency' IS DISTINCT FROM 'false'::jsonb
          OR p.provenance->>'boat_identity_field' IS DISTINCT FROM 'teiban'
          OR p.provenance->'source_fields' IS DISTINCT FROM
             '["tenji_time","tilt","tenji_shinnyu_course","tenji_st","tenji_kigo"]'::jsonb) AS provenance_mismatch
        FROM core.race_boat_preinfo p JOIN core.race r USING(race_id)
        LEFT JOIN raw.source_record s ON s.source_record_id=p.source_record_id
        LEFT JOIN raw.source_batch b ON b.source_batch_id=s.source_batch_id
        CROSS JOIN LATERAL jsonb_to_record(s.raw_payload) AS x(
          kaisai_nen text,kaisai_tsukihi text,kyoteijo_code text,race_no text,teiban text,
          tenji_time text,tilt text,tenji_shinnyu_course text,tenji_st text,tenji_kigo text)''',
        (VERSION, VERSION))

    field_status = {
        'environment_year_venue': rows(cur, '''SELECT extract(year FROM r.race_date)::int AS year,
            r.venue_code,v.field,v.status,count(*) AS rows
            FROM core.race_environment_preinfo p JOIN core.race r USING(race_id)
            CROSS JOIN LATERAL (VALUES
              ('air_temperature',p.air_temperature_status),('water_temperature',p.water_temperature_status),
              ('weather',p.weather_status),('wind_direction',p.wind_direction_status),
              ('venue_direction',p.venue_direction_status),('wind_speed',p.wind_speed_status),
              ('wave_height',p.wave_height_status),('surface_weather_marker',p.surface_weather_marker_status)
            ) v(field,status) GROUP BY 1,2,3,4 ORDER BY 1,2,3,4'''),
        'boat_year_venue': rows(cur, '''SELECT extract(year FROM r.race_date)::int AS year,
            r.venue_code,v.field,v.status,count(*) AS rows
            FROM core.race_boat_preinfo p JOIN core.race r USING(race_id)
            CROSS JOIN LATERAL (VALUES
              ('exhibition_time',p.exhibition_time_status),('tilt',p.tilt_status),
              ('exhibition_course',p.exhibition_course_status),
              ('exhibition_start',p.exhibition_start_status)
            ) v(field,status) GROUP BY 1,2,3,4 ORDER BY 1,2,3,4'''),
    }
    environment_checkpoint = row(cur, '''SELECT
        count(*) FILTER (WHERE air_temperature_status='VALID') AS air_temperature_valid,
        count(*) FILTER (WHERE air_temperature_status='MISSING') AS air_temperature_missing,
        count(*) FILTER (WHERE water_temperature_status='VALID') AS water_temperature_valid,
        count(*) FILTER (WHERE water_temperature_status='MISSING') AS water_temperature_missing,
        count(*) FILTER (WHERE weather_status='VALID') AS weather_valid,
        count(*) FILTER (WHERE weather_status='MISSING') AS weather_missing,
        count(*) FILTER (WHERE wind_direction_status='VALID') AS wind_direction_valid,
        count(*) FILTER (WHERE wind_direction_status='MISSING') AS wind_direction_missing,
        count(*) FILTER (WHERE venue_direction_status='VALID') AS venue_direction_valid,
        count(*) FILTER (WHERE venue_direction_status='MISSING') AS venue_direction_missing,
        count(*) FILTER (WHERE wind_speed_status='UNRESOLVED') AS wind_speed_unresolved,
        count(*) FILTER (WHERE wind_speed_status='MISSING') AS wind_speed_missing,
        count(*) FILTER (WHERE wave_height_status='UNRESOLVED') AS wave_height_unresolved,
        count(*) FILTER (WHERE wave_height_status='MISSING') AS wave_height_missing,
        count(*) FILTER (WHERE surface_weather_marker_status='UNRESOLVED') AS surface_marker_unresolved,
        count(*) FILTER (WHERE surface_weather_marker_status='MISSING') AS surface_marker_missing
        FROM core.race_environment_preinfo''')
    boat_checkpoint = row(cur, '''SELECT
        count(*) FILTER (WHERE exhibition_course_status='VALID') AS course_valid,
        count(*) FILTER (WHERE exhibition_course_status='MISSING') AS course_missing,
        count(*) FILTER (WHERE exhibition_time_status='VALID') AS time_valid,
        count(*) FILTER (WHERE exhibition_time_status='SOURCE_SENTINEL') AS time_sentinel,
        count(*) FILTER (WHERE tilt_status='VALID') AS tilt_valid,
        count(*) FILTER (WHERE tilt_status='MISSING') AS tilt_missing,
        count(*) FILTER (WHERE exhibition_start_status='VALID') AS start_valid,
        count(*) FILTER (WHERE exhibition_start_status='MISSING') AS start_missing,
        count(*) FILTER (WHERE exhibition_start_status='F') AS start_f,
        count(*) FILTER (WHERE exhibition_start_status='L') AS start_l
        FROM core.race_boat_preinfo''')
    expected_boat_checkpoint = {'course_valid': EXPECTED['course']['VALID'],
        'course_missing': EXPECTED['course']['MISSING'],
        'time_valid': EXPECTED['exhibition_time']['VALID'],
        'time_sentinel': EXPECTED['exhibition_time']['SOURCE_SENTINEL'],
        'tilt_valid': EXPECTED['tilt']['VALID'], 'tilt_missing': EXPECTED['tilt']['MISSING'],
        'start_valid': EXPECTED['start_status']['VALID'],
        'start_missing': EXPECTED['start_status']['MISSING'],
        'start_f': EXPECTED['start_symbol']['F'], 'start_l': EXPECTED['start_symbol']['L']}
    c4 = row(cur, '''SELECT count(*) AS batches,coalesce(sum(b.row_count),0) AS records,
        count(*) FILTER (WHERE b.extraction_condition->>'version'=%s) AS phase3c_batches,
        coalesce(sum(b.row_count) FILTER (WHERE b.extraction_condition->>'version'=%s),0)
          AS phase3c_records
        FROM raw.source_batch b WHERE b.source_table='brd_c4' ''', (VERSION, VERSION))
    c4_structure = row(cur, '''SELECT count(*) AS cells,
        count(*) FILTER (WHERE structural_status='STRUCTURALLY_NOT_PROVIDED') AS structural,
        count(*) FILTER (WHERE structural_status='UNRESOLVED') AS unresolved,
        count(*) FILTER (WHERE source_basis<>'environment_preinfo_source_inventory_v1') AS wrong_basis
        FROM core.c4_field_structural_status''')
    blocking = {
        'unexpected_core_races': int(totals['core_races'] != EXPECTED['core_races']),
        'unexpected_core_entries': int(totals['core_entries'] != EXPECTED['core_entries']),
        'unexpected_environment_rows': int(totals['environment_rows'] != EXPECTED['environment_rows']),
        'unexpected_boat_rows': int(totals['boat_rows'] != EXPECTED['boat_rows']),
        'unexpected_missing_races': int(totals['missing_races'] != EXPECTED['missing_races']),
        'unexpected_missing_boats': int(totals['missing_boats'] != EXPECTED['missing_races'] * 6),
        'unexpected_missing_keys': missing_shape['missing_races'] - missing_shape['expected_missing_races'],
        'missing_set_unexpected': missing_set['unexpected_missing'],
        'missing_set_expected_not_missing': missing_set['expected_not_missing'],
        'invalid_coverage_status': missing_shape['invalid_status'],
        'races_not_six_boats': six_boats['races_not_six_boats'],
        'unexpected_environment_field_checkpoints': int(
            environment_checkpoint != EXPECTED['environment_status']),
        'unexpected_boat_field_checkpoints': int(
            boat_checkpoint != expected_boat_checkpoint),
        'c4_raw_rows_or_batches': c4['batches'] + c4['records'],
        'c4_structural_contract': int(c4_structure !=
            {'cells': 96, 'structural': 8, 'unresolved': 88, 'wrong_basis': 0}),
    }
    for prefix, replay in (('environment', environment_replay), ('boat', boat_replay)):
        for name, value in replay.items():
            if name != 'rows':
                blocking[prefix + '_' + name] = value
    return {'canonical': {'totals': totals, 'missing_race_keys': missing,
        'six_boats': six_boats, 'coverage_year_venue': coverage,
        'field_status_year_venue': field_status,
        'field_checkpoint': {'environment': environment_checkpoint, 'boat': boat_checkpoint},
        'units': {'air_temperature_c':'degree_C','water_temperature_c':'degree_C',
          'exhibition_time_seconds':'second','tilt_degrees':'degree',
          'exhibition_start_timing':'second','wind_speed_raw':'UNRESOLVED',
          'wave_height_raw':'UNRESOLVED','surface_weather_marker_raw':'UNRESOLVED'},
        'lineage_replay': {'environment': environment_replay, 'boat': boat_replay},
        'c4_untouched': c4, 'c4_structural_status': c4_structure, 'blocking': blocking}}


def frozen_audit(cur):
    datasets = row(cur, '''SELECT count(*) AS rows,
        count(*) FILTER (WHERE results_cutoff_date<>effective_date-1) AS cutoff_mismatch,
        count(*) FILTER (WHERE date_end>results_cutoff_date) AS date_end_after_cutoff,
        count(*) FILTER (WHERE canonical_content_hash !~ '^[0-9a-f]{64}$'
                         OR manifest_hash !~ '^[0-9a-f]{64}$') AS invalid_hash
        FROM core.dataset_version''')
    manifest = row(cur, '''SELECT count(*) AS missing_records FROM core.dataset_version d
        CROSS JOIN LATERAL jsonb_array_elements(d.source_manifest->'records') item
        LEFT JOIN raw.source_record s
          ON s.source_record_id=(item->>'source_record_id')::bigint
        WHERE s.source_record_id IS NULL
           OR s.record_hash IS DISTINCT FROM item->>'record_hash' ''')
    phase3c = row(cur, '''SELECT count(*) AS records FROM core.dataset_version d
        CROSS JOIN LATERAL jsonb_array_elements(d.source_manifest->'records') item
        JOIN raw.source_record s
          ON s.source_record_id=(item->>'source_record_id')::bigint
        JOIN raw.source_batch b USING(source_batch_id)
        WHERE b.source_table IN ('brd_c2','brd_c3')
           OR b.extraction_condition->>'version'=%s''', (VERSION,))
    return {'datasets': datasets, 'manifest': manifest,
            'phase3c_records_in_frozen_datasets': phase3c['records'],
            'blocking': {'dataset_cutoff_mismatch': datasets['cutoff_mismatch'],
                         'dataset_date_end_after_cutoff': datasets['date_end_after_cutoff'],
                         'dataset_invalid_hash': datasets['invalid_hash'],
                         'dataset_manifest_missing_records': manifest['missing_records'],
                         'phase3c_records_in_frozen_datasets': phase3c['records']}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    connection = target_connection(args.config)
    try:
        connection.commit()

        def progress(message):
            stamp = datetime.now().astimezone().isoformat(timespec='seconds')
            print(f'[{stamp}] {message}', file=sys.stderr, flush=True)

        result = audit(connection, progress=progress)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n',
                               encoding='utf-8')
        print(json.dumps({'status': result['status'],
                          'blocking_findings': result['blocking_findings']}))
        if result['status'] != 'PASS':
            raise SystemExit(1)
    finally:
        connection.rollback()
        connection.close()


if __name__ == '__main__':
    main()
