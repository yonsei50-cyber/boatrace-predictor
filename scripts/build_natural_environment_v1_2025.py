"""Append 2025 race-grain environment observations using the frozen v1 rules.

This prepares inputs only. It does not read labels, fit a model, or evaluate
the independent holdout. The frozen pre-2025 modules remain byte-for-byte intact.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path

from scripts import natural_environment_tide_v1 as tide
from scripts import build_natural_environment_v1 as frozen
from scripts.db import source_connection, target_connection


ROOT = Path(__file__).resolve().parents[1]
FREEZE = ROOT / 'artifacts/natural_environment_v1_freeze.json'
REPORT = ROOT / 'artifacts/natural_environment_v1_2025_feature_report.json'
FREEZE_SHA256 = '78c24d7c97d07678684045ee3b4ef2a1b8f25871a8549cbfe959efd6a29eebf7'
RACE_SQL = """SELECT race_id,race_date,venue_code,race_no FROM core.race
WHERE race_date >= DATE '2025-01-01' AND race_date < DATE '2026-01-01'
ORDER BY race_date,race_id"""
TIDE_SQL = """SELECT data_kubun,chiten_code,kaisai_nen,kaisai_tsukihi,jikoku,choi
FROM public.apd_choihyo WHERE data_kubun IN ('1','2')
AND ((kaisai_nen='2024' AND kaisai_tsukihi='1231') OR kaisai_nen='2025')
ORDER BY chiten_code,kaisai_nen,kaisai_tsukihi,jikoku,data_kubun"""
SOURCE_SQL = """SELECT l.record_id,l.kaisai_nen,l.kaisai_tsukihi,l.kyoteijo_code,
       l.race_no,l.shimekiri_yotei_jikoku,
       c.record_id,c.hogaku_code,c.fuko_code,c.fusoku,c.tenki_code,c.kion
FROM public.brd_l2 l LEFT JOIN public.brd_c2 c USING
    (kaisai_nen,kaisai_tsukihi,kyoteijo_code,race_no)
WHERE l.kaisai_nen='2025'
ORDER BY l.kaisai_nen,l.kaisai_tsukihi,l.kyoteijo_code,l.race_no"""


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def preflight() -> dict:
    if sha(FREEZE) != FREEZE_SHA256:
        raise RuntimeError('natural environment freeze hash mismatch')
    freeze = json.loads(FREEZE.read_text(encoding='utf-8'))
    for name, expected in freeze['code_sha256'].items():
        path = {'builder': frozen.__file__, 'tide': tide.__file__,
                'model': ROOT / 'scripts/natural_environment_model_v1.py',
                'sql_migration': frozen.MIGRATION}[name]
        if sha(Path(path)) != expected:
            raise RuntimeError(f'frozen {name} code hash mismatch')
    if REPORT.exists():
        raise RuntimeError('2025 feature report exists; refusing rebuild')
    conn = target_connection()
    try:
        conn.commit()
        conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM core.natural_environment_feature_v1 "
                        "WHERE race_date >= DATE '2025-01-01' AND race_date < DATE '2026-01-01'")
            if cur.fetchone()[0]:
                raise RuntimeError('2025 environment feature rows already exist')
            cur.execute(RACE_SQL)
            rows = cur.fetchall()
    finally:
        conn.close()
    result = {}
    for race_id, day, venue, race_no in rows:
        key = frozen._key(day.year, day.strftime('%m%d'), venue, race_no)
        if key in result:
            raise RuntimeError(f'duplicate target race key: {key}')
        result[key] = (int(race_id), day, int(venue), int(race_no))
    if len(result) != 55908:
        raise RuntimeError(f'2025 race inventory changed: {len(result)} != 55908')
    return result


def source_extrema(conn):
    stations = defaultdict(list)
    digest = hashlib.sha256()
    with conn.cursor(name='natural_environment_tide_2025') as cur:
        cur.itersize = 10000
        cur.execute(TIDE_SQL)
        for values in cur:
            row = dict(zip(('data_kubun', 'chiten_code', 'kaisai_nen',
                            'kaisai_tsukihi', 'jikoku', 'choi'), values))
            digest.update((frozen._json(row) + '\n').encode())
            if row['chiten_code'] not in set(tide.VENUE_TO_CHITEN_CODE.values()):
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


def build() -> None:
    race_map = preflight()
    source = source_connection()
    target = target_connection()
    try:
        with source.cursor() as cur:
            cur.execute('SET LOCAL statement_timeout = 0')
        stations, tide_source_hash = source_extrema(source)
        with target.cursor() as cur:
            cur.execute('SET LOCAL statement_timeout = 0')
        digest = hashlib.sha256()
        counts = Counter()
        seen = set()
        buffer = []
        # Only the date boundary is extended. All parsing, tide interpolation,
        # status logic, and C2 interpretation run in the frozen modules.
        original_end = tide.PREHOLDOUT_END
        tide.PREHOLDOUT_END = datetime(2026, 1, 1)
        try:
            with source.cursor(name='natural_environment_c2_l2_2025') as src:
                src.itersize = 10000
                src.execute(SOURCE_SQL)
                with target.cursor() as dst:
                    for values in src:
                        (l2_id, year, md, venue_raw, race_raw, cutoff,
                         c2_id, hogaku, fuko, fusoku, weather_raw, kion) = values
                        key = frozen._key(year, md, venue_raw, race_raw)
                        identity = race_map.get(key)
                        if identity is None:
                            raise RuntimeError(f'source race not in target: {key}')
                        race_id, day, venue, race_no = identity
                        if race_id in seen:
                            raise RuntimeError(f'duplicate source race key: {key}')
                        seen.add(race_id)
                        digest.update((frozen._json(values) + '\n').encode())
                        try:
                            deadline = tide.race_deadline_timestamp(year, md, cutoff)
                            feature = frozen.tide_for_race(venue, deadline, stations)
                        except (TypeError, ValueError):
                            applicable = tide.tide_chiten_code(venue) is not None
                            feature = dict(tide_source_available=applicable,
                                tide_height=None, tide_direction=None,
                                tide_change_speed=None,
                                tide_status='UNRESOLVED' if applicable else 'NOT_APPLICABLE',
                                tide_unresolved_reason='INVALID_DEADLINE',
                                tide_extrema_lineage=[])
                        relative, wind_category, wind, weather, air = frozen.c2_features(
                            hogaku, fuko, fusoku, weather_raw, kion)
                        provenance = dict(c2_source=frozen.SOURCE_C2 if c2_id is not None else None,
                            c2_record_id_raw=c2_id, l2_source=frozen.SOURCE_L2,
                            l2_record_id_raw=l2_id, tide_source=frozen.SOURCE_TIDE,
                            source_class='pre_race_environment; historical exact publication time unverified')
                        output = (race_id, day.isoformat(), venue, race_no, cutoff,
                            c2_id, hogaku, fuko, fusoku, weather_raw, kion,
                            relative, wind_category, wind, weather, air,
                            feature['tide_source_available'], tide.tide_chiten_code(venue),
                            feature['tide_height'], feature['tide_direction'],
                            feature['tide_change_speed'], feature['tide_status'],
                            feature['tide_unresolved_reason'], frozen._json(feature['tide_extrema_lineage']),
                            frozen._json(provenance))
                        buffer.append(['\\N' if value is None else value for value in output])
                        counts['races'] += 1
                        counts['c2_present' if c2_id is not None else 'c2_missing'] += 1
                        counts['wind_' + wind_category] += 1
                        counts['air_available' if air is not None else 'air_missing'] += 1
                        counts['tide_' + feature['tide_status']] += 1
                        if len(buffer) >= 2000:
                            frozen._copy_rows(dst, buffer)
                            buffer.clear()
                    if buffer:
                        frozen._copy_rows(dst, buffer)
        finally:
            tide.PREHOLDOUT_END = original_end
        if len(seen) != len(race_map):
            raise RuntimeError(f'source/target race mismatch: {len(seen)} != {len(race_map)}')
        with target.cursor() as cur:
            cur.execute("SELECT count(*) FROM core.natural_environment_feature_v1 "
                        "WHERE race_date >= DATE '2025-01-01' AND race_date < DATE '2026-01-01'")
            if cur.fetchone()[0] != len(seen):
                raise RuntimeError('inserted race count mismatch')
        target.commit()
        report = dict(scope='2025-01-01 <= race_date < 2026-01-01',
            source_tables=[frozen.SOURCE_C2, frozen.SOURCE_L2, frozen.SOURCE_TIDE],
            freeze_sha256=FREEZE_SHA256, source_sha256=digest.hexdigest(),
            tide_source_sha256=tide_source_hash, counts=dict(sorted(counts.items())),
            tide_mapping=tide.VENUE_TO_CHITEN_CODE,
            tide_calculation='frozen natural_environment_tide_v1 with date guard extended to 2026-01-01')
        with REPORT.open('x', encoding='utf-8', newline='\n') as stream:
            json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        print(json.dumps(report, sort_keys=True), flush=True)
    except Exception:
        target.rollback()
        raise
    finally:
        target.close()
        source.close()


if __name__ == '__main__':
    build()
