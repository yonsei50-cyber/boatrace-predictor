"""Build the race-grain Natural Environment v1 interface before 2025.

Only source rows needed for 2017-2024 races are read. All target writes are in
one transaction; the existing interface is never overwritten. This does not
fit or evaluate a prediction model.
"""
from __future__ import annotations

from bisect import bisect_left
from collections import Counter, defaultdict
import csv
from datetime import datetime
import hashlib
from io import StringIO
import json
from pathlib import Path
import re

import numpy as np

from scripts.db import source_connection, target_connection
from scripts.natural_environment_tide_v1 import (
    VENUE_TO_CHITEN_CODE, derive_tide_feature, race_deadline_timestamp,
    tide_chiten_code,
)
from scripts.p1_p2_baseline_v1 import load_cache


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / 'sql/migrations/0010_natural_environment_feature_v1.sql'
CACHE = ROOT / '.local/natural_environment_v1_development.npz'
SOURCE_REPORT = ROOT / 'artifacts/natural_environment_v1_source_report.json'
FIRST_YEAR = '2017'
END_YEAR = '2025'
SOURCE_C2 = 'pckyotei.public.brd_c2'
SOURCE_L2 = 'pckyotei.public.brd_l2'
SOURCE_TIDE = 'pckyotei.public.apd_choihyo'

RACE_SQL = """
SELECT race_id,race_date,venue_code,race_no FROM core.race
WHERE race_date >= DATE '2017-01-01' AND race_date < DATE '2025-01-01'
ORDER BY race_date,race_id
"""
TIDE_SQL = """
SELECT data_kubun,chiten_code,kaisai_nen,kaisai_tsukihi,jikoku,choi
FROM public.apd_choihyo
WHERE data_kubun IN ('1','2')
  AND ((kaisai_nen = '2016' AND kaisai_tsukihi = '1231')
       OR (kaisai_nen >= '2017' AND kaisai_nen < '2025'))
ORDER BY chiten_code,kaisai_nen,kaisai_tsukihi,jikoku,data_kubun
"""
SOURCE_SQL = """
SELECT l.record_id,l.kaisai_nen,l.kaisai_tsukihi,l.kyoteijo_code,
       l.race_no,l.shimekiri_yotei_jikoku,
       c.record_id,c.hogaku_code,c.fuko_code,c.fusoku,c.tenki_code,c.kion
FROM public.brd_l2 l
LEFT JOIN public.brd_c2 c USING
    (kaisai_nen,kaisai_tsukihi,kyoteijo_code,race_no)
WHERE l.kaisai_nen >= '2017' AND l.kaisai_nen < '2025'
ORDER BY l.kaisai_nen,l.kaisai_tsukihi,l.kyoteijo_code,l.race_no
"""
COLUMNS = (
    'race_id race_date venue_code race_no l2_deadline_raw c2_record_id_raw '
    'hogaku_code_raw fuko_code_raw fusoku_raw tenki_code_raw kion_raw '
    'wind_relative_d wind_category wind_speed_m weather air_temperature_c '
    'tide_source_available tide_chiten_code tide_height tide_direction '
    'tide_change_speed tide_status tide_unresolved_reason '
    'tide_extrema_lineage source_provenance'
).split()


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), default=str,
                      ensure_ascii=False)


def _key(year, monthday, venue, race_no):
    return (str(year).zfill(4), str(monthday).zfill(4),
            str(venue).zfill(2), str(race_no).zfill(2))


def _source_code(value, pattern):
    if value is None or not str(value).strip():
        return None, 'MISSING'
    text = str(value).strip()
    if not re.fullmatch(pattern, text):
        return None, 'UNRESOLVED'
    return text, 'VALID'


def c2_features(hogaku_code, fuko_code, fusoku, tenki_code, kion):
    """Interpret only the specified C2 raw fields; preserve nulls and codes."""
    wind_raw, wind_state = _source_code(fusoku, r'[0-9]{2}')
    wind = float(int(wind_raw)) if wind_state == 'VALID' else None
    venue_raw, venue_state = _source_code(hogaku_code, r'(0[1-9]|1[0-6])')
    direction_raw, direction_state = _source_code(fuko_code, r'(0[1-9]|1[0-6])')
    relative_d = None
    if wind_state != 'VALID':
        wind_category = wind_state
    elif wind == 0:
        wind_category = 'CALM'
    elif venue_state != 'VALID' or direction_state != 'VALID':
        wind_category = 'UNRESOLVED' if 'UNRESOLVED' in (venue_state, direction_state) else 'MISSING'
    else:
        relative_d = (int(direction_raw) - int(venue_raw)) % 16
        if relative_d in (15, 0, 1):
            wind_category = 'LEFT_CROSSWIND'
        elif 2 <= relative_d <= 6:
            wind_category = 'HEADWIND'
        elif 7 <= relative_d <= 9:
            wind_category = 'RIGHT_CROSSWIND'
        else:
            wind_category = 'TAILWIND'
    weather_raw, weather_state = _source_code(tenki_code, r'[1-6]')
    weather = weather_raw if weather_state == 'VALID' else weather_state
    air_raw, air_state = _source_code(kion, r'([0-9]{3}|-[0-9]{2})')
    air = int(air_raw) / 10.0 if air_state == 'VALID' else None
    return relative_d, wind_category, wind, weather, air


def target_races():
    conn = target_connection()
    try:
        conn.commit()
        conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
        with conn.cursor() as cur:
            cur.execute(RACE_SQL)
            rows = cur.fetchall()
        result = {}
        for race_id, day, venue, race_no in rows:
            key = _key(day.year, day.strftime('%m%d'), venue, race_no)
            if key in result:
                raise RuntimeError('duplicate target race key')
            result[key] = (int(race_id), day, int(venue), int(race_no))
        return result
    finally:
        conn.close()


def source_extrema(conn):
    stations = defaultdict(list)
    digest = hashlib.sha256()
    with conn.cursor(name='natural_environment_tide_pre2025') as cur:
        cur.itersize = 10000
        cur.execute(TIDE_SQL)
        for values in cur:
            row = dict(zip(('data_kubun', 'chiten_code', 'kaisai_nen',
                            'kaisai_tsukihi', 'jikoku', 'choi'), values))
            digest.update((_json(row) + '\n').encode())
            if row['chiten_code'] not in set(VENUE_TO_CHITEN_CODE.values()):
                continue
            stamp = datetime.strptime(str(row['kaisai_nen']) +
                                      str(row['kaisai_tsukihi']).zfill(4) +
                                      str(row['jikoku']).zfill(4), '%Y%m%d%H%M')
            stations[row['chiten_code']].append((stamp, row))
    for code, items in stations.items():
        items.sort(key=lambda pair: pair[0])
        if len({stamp for stamp, _ in items}) != len(items):
            raise RuntimeError(f'duplicate tide extremum timestamp: {code}')
        stations[code] = ([stamp for stamp, _ in items], [row for _, row in items])
    return stations, digest.hexdigest()


def tide_for_race(venue, deadline, stations):
    code = tide_chiten_code(venue)
    if code is None:
        return derive_tide_feature(venue, deadline, ())
    stamps, rows = stations.get(code, ((), ()))
    pos = bisect_left(stamps, deadline)
    selected = [rows[pos - 1]] if pos else []
    if pos < len(rows):
        selected.append(rows[pos])
    return derive_tide_feature(venue, deadline, selected)


def _copy_rows(cur, rows):
    buffer = StringIO()
    writer = csv.writer(buffer, lineterminator='\n')
    writer.writerows(rows)
    buffer.seek(0)
    cur.copy_expert('COPY core.natural_environment_feature_v1 (' +
                    ','.join(COLUMNS) + ") FROM STDIN WITH (FORMAT csv, NULL '\\N')",
                    buffer)


def build():
    race_map = target_races()
    source = source_connection()
    target = target_connection()
    try:
        with source.cursor() as cur:
            cur.execute('SET LOCAL statement_timeout = 0')
        stations, tide_source_hash = source_extrema(source)
        with target.cursor() as cur:
            cur.execute("SELECT to_regclass('core.natural_environment_feature_v1')")
            if cur.fetchone()[0] is not None:
                raise RuntimeError('natural environment table already exists; refusing overwrite')
            cur.execute('SET LOCAL statement_timeout = 0')
            cur.execute(MIGRATION.read_text(encoding='utf-8'))
        digest = hashlib.sha256()
        counts = Counter()
        seen = set()
        buffer = []
        with source.cursor(name='natural_environment_c2_l2_pre2025') as src:
            src.itersize = 10000
            src.execute(SOURCE_SQL)
            with target.cursor() as dst:
                for values in src:
                    (l2_id, year, md, venue_raw, race_raw, cutoff,
                     c2_id, hogaku, fuko, fusoku, weather_raw, kion) = values
                    key = _key(year, md, venue_raw, race_raw)
                    identity = race_map.get(key)
                    if identity is None:
                        raise RuntimeError(f'source race not in target: {key}')
                    race_id, day, venue, race_no = identity
                    if race_id in seen:
                        raise RuntimeError('duplicate source race key')
                    seen.add(race_id)
                    digest.update((_json(values) + '\n').encode())
                    try:
                        deadline = race_deadline_timestamp(year, md, cutoff)
                        tide = tide_for_race(venue, deadline, stations)
                    except (TypeError, ValueError):
                        tide = dict(tide_source_available=tide_chiten_code(venue) is not None,
                            tide_height=None, tide_direction=None, tide_change_speed=None,
                            tide_status='UNRESOLVED' if tide_chiten_code(venue) else 'NOT_APPLICABLE',
                            tide_unresolved_reason='INVALID_DEADLINE', tide_extrema_lineage=[])
                    relative, wind_category, wind, weather, air = c2_features(
                        hogaku, fuko, fusoku, weather_raw, kion)
                    provenance = dict(c2_source=SOURCE_C2 if c2_id is not None else None,
                        c2_record_id_raw=c2_id, l2_source=SOURCE_L2,
                        l2_record_id_raw=l2_id, tide_source=SOURCE_TIDE,
                        source_class='pre_race_environment; historical exact publication time unverified')
                    output = (race_id, day.isoformat(), venue, race_no, cutoff,
                        c2_id, hogaku, fuko, fusoku, weather_raw, kion,
                        relative, wind_category, wind, weather, air,
                        tide['tide_source_available'], tide_chiten_code(venue),
                        tide['tide_height'], tide['tide_direction'],
                        tide['tide_change_speed'], tide['tide_status'],
                        tide['tide_unresolved_reason'], _json(tide['tide_extrema_lineage']),
                        _json(provenance))
                    buffer.append(['\\N' if v is None else v for v in output])
                    counts['races'] += 1
                    counts['c2_present' if c2_id is not None else 'c2_missing'] += 1
                    counts['wind_' + wind_category] += 1
                    counts['weather_' + weather] += 1
                    counts['air_available' if air is not None else 'air_missing'] += 1
                    counts['tide_' + tide['tide_status']] += 1
                    if len(buffer) >= 2000:
                        _copy_rows(dst, buffer)
                        buffer.clear()
                if buffer:
                    _copy_rows(dst, buffer)
        if len(seen) != len(race_map):
            raise RuntimeError(f'source/target race mismatch: {len(seen)} != {len(race_map)}')
        with target.cursor() as cur:
            cur.execute("SELECT count(*) FROM core.natural_environment_feature_v1")
            if cur.fetchone()[0] != len(seen):
                raise RuntimeError('inserted race count mismatch')
        target.commit()
        report = dict(version='NATURAL_ENVIRONMENT_FEATURE_V1',
            scope='2017-01-01 <= race_date < 2025-01-01',
            source_tables=[SOURCE_C2, SOURCE_L2, SOURCE_TIDE],
            source_sha256=digest.hexdigest(), tide_source_sha256=tide_source_hash,
            counts=dict(sorted(counts.items())), tide_mapping=VENUE_TO_CHITEN_CODE)
        SOURCE_REPORT.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n',
                                 encoding='utf-8')
        print(json.dumps(report, sort_keys=True), flush=True)
    except Exception:
        target.rollback()
        raise
    finally:
        target.close()
        source.close()


def export_cache():
    """Make a race-aligned environment cache for the frozen baseline cohort."""
    baseline = load_cache()
    conn = target_connection()
    try:
        conn.commit()
        conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
        with conn.cursor() as cur:
            cur.execute("""SELECT f.race_id,EXTRACT(YEAR FROM f.race_date)::integer,
                f.wind_speed_m,f.air_temperature_c,f.tide_height,
                f.tide_change_speed,f.wind_category,f.weather,
                COALESCE(f.tide_direction,f.tide_status),
                f.tide_source_available,f.tide_status
                FROM core.natural_environment_feature_v1 f
                JOIN (SELECT DISTINCT race_id FROM core.prediction_dataset_v1
                      WHERE label_eligible = TRUE
                        AND race_date >= DATE '2017-01-01'
                        AND race_date < DATE '2025-01-01') p USING(race_id)
                WHERE f.race_date >= DATE '2017-01-01'
                  AND f.race_date < DATE '2025-01-01'
                ORDER BY f.race_date,f.race_id""")
            rows = cur.fetchall()
        ids = np.asarray([r[0] for r in rows], dtype=np.int64)
        years = np.asarray([r[1] for r in rows], dtype=np.int16)
        if not np.array_equal(ids, baseline['race_ids']) or not np.array_equal(years, baseline['years']):
            raise RuntimeError('environment cache not aligned to frozen baseline cohort')
        numeric = np.asarray([[float(v) if v is not None else np.nan for v in r[2:6]]
                              for r in rows], dtype=np.float32)
        strings = [np.asarray([r[i] for r in rows], dtype='<U32') for i in (6, 7, 8, 10)]
        available = np.asarray([r[9] for r in rows], dtype=np.bool_)
        arrays = dict(race_ids=ids, years=years,
            wind_speed=numeric[:, 0], air_temperature=numeric[:, 1],
            tide_height=numeric[:, 2], tide_change_speed=numeric[:, 3],
            wind_category=strings[0], weather=strings[1],
            tide_direction=strings[2], tide_source_available=available,
            tide_status=strings[3])
        from scripts.natural_environment_model_v1 import ENV_FIELDS, _array_digest
        source_hash = _array_digest(arrays, ENV_FIELDS)
        CACHE.parent.mkdir(exist_ok=True)
        np.savez(CACHE, **arrays, source_sha256=source_hash,
            baseline_source_sha256=baseline['source_sha256'])
        print(json.dumps(dict(phase='export_cache', races=len(ids),
                              cache_sha256=hashlib.sha256(CACHE.read_bytes()).hexdigest(),
                              source_sha256=source_hash)), flush=True)
    finally:
        conn.close()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=('build', 'export_cache'))
    args = parser.parse_args()
    {'build': build, 'export_cache': export_cache}[args.phase]()
