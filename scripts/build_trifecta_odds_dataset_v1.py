"""Build 2025 trifecta odds at the frozen probability artifact's exact grain.

Both odds sources are read only. The output is an NPZ interface: a NaN in an
odds array is SQL NULL, as specified by its independent status array. Consumers
must use ``odds_or_none`` when materializing individual rows.
"""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
from itertools import permutations
import json
import os
from pathlib import Path
import re
import subprocess

import numpy as np

from scripts.db import source_connection, target_connection


ROOT = Path(__file__).resolve().parents[1]
PROBABILITY = ROOT / 'artifacts/trifecta_probability_v1_2025.npz'
OUTPUT = ROOT / 'artifacts/trifecta_odds_dataset_v1_2025.npz'
REPORT = ROOT / 'artifacts/trifecta_odds_dataset_v1_2025_report.json'
PROBABILITY_SHA256 = '1be7f4338693c0f1a4984f06b89c0ae5a3c08c03f7b6a7e94778800d848f068d'
DUMP = Path(r'C:\Users\knkzh\boatrace-source-preserve\boatrace_nonreproducible_source.dump')
DUMP_SHA256 = 'c709a9ca54f1a793f0d4cdeb7d1a63a889ceeacc979deacb3793e31e102d3d56'
PG_RESTORE = Path(r'C:\Program Files\PostgreSQL\16\bin\pg_restore.exe')
COMBINATIONS = [''.join(p) for p in permutations('123456', 3)]
COMBO_INDEX = {code: i for i, code in enumerate(COMBINATIONS)}
STATUS = {'MISSING_SOURCE': 0, 'VALID': 1, 'NO_VOTES': 2,
          'SCRATCHED': 3, 'CAPPED': 4, 'INVALID_RAW': 5,
          'SOURCE_NONPOSITIVE': 6, 'SOURCE_MISSING': 7}
STATUS_NAME = {value: key for key, value in STATUS.items()}
COPY_HEADER = ('COPY br_model.kyoteibiyori_odds_5min (race_id, race_date, '
               'kyoteijo_code, race_no, bet_type, kumiawase, combination, '
               'odds_5min, odds_missing_reason, source_endpoint, '
               'source_shimekiri, response_sha256, retrieved_at) FROM stdin;')
NULL = '\\N'


def file_hash(path: Path) -> str:
    digest = sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def odds_or_none(value: float, status_code: int) -> float | None:
    """The public row interface gives actual NULL/None for non-valid odds."""
    return float(value) if status_code == STATUS['VALID'] else None


def o6_value(token: str) -> tuple[float, int]:
    if token == '000000':
        return np.nan, STATUS['NO_VOTES']
    if token == '******':
        return np.nan, STATUS['SCRATCHED']
    if token == '099999':
        return np.nan, STATUS['CAPPED']  # >=9999.9, not an exact price
    if not re.fullmatch(r'[0-9]{6}', token, flags=re.ASCII):
        return np.nan, STATUS['INVALID_RAW']
    value = int(token) / 10
    return (value, STATUS['VALID']) if value > 0 else (np.nan, STATUS['INVALID_RAW'])


def dump_value(token: str, reason: str) -> tuple[float, int]:
    if token == NULL:
        return np.nan, (STATUS['SOURCE_NONPOSITIVE'] if reason == 'source_nonpositive'
                        else STATUS['SOURCE_MISSING'])
    if not re.fullmatch(r'[0-9]+\.[0-9]', token, flags=re.ASCII):
        return np.nan, STATUS['INVALID_RAW']
    value = float(token)
    return (value, STATUS['VALID']) if np.isfinite(value) and value > 0 else (
        np.nan, STATUS['INVALID_RAW'])


def load_cohort() -> tuple[dict[str, np.ndarray], dict[str, int]]:
    if file_hash(PROBABILITY) != PROBABILITY_SHA256:
        raise RuntimeError('probability artifact SHA-256 mismatch')
    with np.load(PROBABILITY, allow_pickle=False) as source:
        names = ('race_id', 'race_date_yyyymmdd', 'first_boat', 'second_boat', 'third_boat')
        data = {key: source[key] for key in names}
    rows = len(data['race_id'])
    if rows != 51311 * 120 or any(len(v) != rows for v in data.values()):
        raise RuntimeError('unexpected probability identity shape')
    expected = np.asarray([[int(x) for x in code] for code in COMBINATIONS], dtype=np.uint8)
    for column, values in zip(('first_boat', 'second_boat', 'third_boat'), expected.T):
        if not np.array_equal(data[column].reshape(-1, 120), np.broadcast_to(values, (51311, 120))):
            raise RuntimeError(f'probability {column} is not 120 unique ordered combinations')
    race_ids = data['race_id'].reshape(-1, 120)
    dates = data['race_date_yyyymmdd'].reshape(-1, 120)
    if (np.any(race_ids != race_ids[:, :1]) or np.any(dates != dates[:, :1])
            or len(np.unique(race_ids[:, 0])) != 51311
            or np.any((dates[:, 0] < 20250101) | (dates[:, 0] > 20251231))):
        raise RuntimeError('probability race identity, date, or grain invalid')
    return data, {str(int(race_id)): i for i, race_id in enumerate(race_ids[:, 0])}


def core_identity(data: dict[str, np.ndarray], positions: dict[str, int]) -> tuple[np.ndarray, np.ndarray, dict[str, int]]:
    venue = np.zeros(len(positions), dtype=np.uint8)
    race_no = np.zeros(len(positions), dtype=np.uint8)
    natural_positions: dict[str, int] = {}
    conn = target_connection()
    try:
        conn.commit()
        conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
        with conn.cursor() as cur:
            cur.execute("SELECT current_setting('transaction_read_only')")
            if cur.fetchone()[0] != 'on':
                raise RuntimeError('core identity query must be read only')
            cur.execute("SELECT race_id,race_date,venue_code,race_no FROM core.race "
                        "WHERE race_date >= DATE '2025-01-01' AND race_date < DATE '2026-01-01'")
            for race_id, race_date, v, no in cur:
                position = positions.get(str(race_id))
                if position is None:
                    continue
                day = int(race_date.strftime('%Y%m%d'))
                if day != int(data['race_date_yyyymmdd'][position * 120]):
                    raise RuntimeError(f'core/probability date mismatch at race {race_id}')
                key = f'{day:08d}{v:02d}{no:02d}'
                if key in natural_positions:
                    raise RuntimeError(f'duplicate core natural race key {key}')
                natural_positions[key] = position
                venue[position], race_no[position] = v, no
    finally:
        conn.close()
    if len(natural_positions) != len(positions):
        raise RuntimeError(f'core/probability race join incomplete: {len(natural_positions)}')
    return venue, race_no, natural_positions


def confirmed_source(natural_positions: dict[str, int], numeric: np.ndarray,
                     statuses: np.ndarray, raw: np.ndarray) -> dict:
    seen = np.zeros(len(natural_positions), dtype=bool)
    source_rows = 0
    states = Counter()
    conn = source_connection()
    try:
        with conn.cursor(name='odds_dataset_o6_2025') as cur:
            cur.itersize = 1000
            cur.execute("SELECT kaisai_nen,kaisai_tsukihi,kyoteijo_code,race_no,"
                        "record_id,data_kubun,odds_koshinjikan,odds_sanrentan "
                        "FROM public.brd_o6 WHERE kaisai_nen='2025'")
            for year, md, v, no, record, kind, update_time, payload in cur:
                key = year + md + v + no
                position = natural_positions.get(key)
                if position is None:
                    continue
                source_rows += 1
                if seen[position]:
                    raise RuntimeError(f'UNRESOLVED_DUPLICATE confirmed O6 race {key}')
                seen[position] = True
                states[(record, kind, update_time)] += 1
                if (record, kind, update_time) != ('O6', '3', '    '):
                    raise RuntimeError(f'unexpected O6 source state at {key}')
                if payload is None or len(payload) != 1080:
                    raise RuntimeError(f'invalid O6 payload length at {key}')
                start = position * 120
                for j in range(120):
                    block = payload[j * 9:(j + 1) * 9]
                    if block[:3] != COMBINATIONS[j]:
                        raise RuntimeError(f'invalid O6 combination or order at {key}')
                    token = block[3:]
                    numeric[start + j], statuses[start + j] = o6_value(token)
                    raw[start + j] = token.encode('ascii')
    finally:
        conn.close()
    return {'source_races_joined': int(seen.sum()), 'source_rows_joined': source_rows,
            'source_states': [{'record_id': k[0], 'data_kubun': k[1],
                               'odds_koshinjikan': k[2], 'races': count}
                              for k, count in states.items()]}


def five_minute_source(natural_positions: dict[str, int], numeric: np.ndarray,
                       statuses: np.ndarray, raw: np.ndarray) -> dict:
    if file_hash(DUMP) != DUMP_SHA256:
        raise RuntimeError('preserved dump SHA-256 mismatch')
    args = [str(PG_RESTORE), '--data-only', '--schema=br_model',
            '--table=kyoteibiyori_odds_5min', '-f', '-', str(DUMP)]
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding='utf-8', errors='strict')
    copy_seen = copy_ended = False
    selected_rows = 0
    selected_races: set[str] = set()
    reason_counts = Counter()
    response_hashes: dict[str, str] = {}
    retrieved_times: dict[str, str] = {}
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip('\r\n')
            if not copy_seen:
                if line.startswith('COPY br_model.kyoteibiyori_odds_5min '):
                    if line != COPY_HEADER:
                        raise RuntimeError('5-minute COPY column order changed')
                    copy_seen = True
                continue
            if line == '\\.':
                copy_ended = True
                break
            fields = line.split('\t')
            if len(fields) != 13:
                raise RuntimeError('5-minute COPY field count changed')
            (race_key, race_date, venue, no, bet_type, kumiawase, combination,
             token, reason, endpoint, shimekiri, response_hash, retrieved_at) = fields
            position = natural_positions.get(race_key)
            if position is None:
                continue
            if (race_key != race_date.replace('-', '') + f'{int(venue):02d}{int(no):02d}'
                    or bet_type != '3t' or shimekiri != '5'
                    or endpoint != 'https://kyoteibiyori.com/request_odds_shousai.php'):
                raise RuntimeError(f'5-minute race identity/source classification mismatch: {race_key}')
            if (not re.fullmatch(r'[0-9a-f]{64}', response_hash)
                    or race_key in response_hashes and response_hashes[race_key] != response_hash):
                raise RuntimeError(f'5-minute response provenance mismatch: {race_key}')
            response_hashes[race_key] = response_hash
            if race_key in retrieved_times and retrieved_times[race_key] != retrieved_at:
                raise RuntimeError(f'5-minute retrieval provenance mismatch: {race_key}')
            retrieved_times[race_key] = retrieved_at
            j = COMBO_INDEX.get(kumiawase)
            if j is None or combination != '-'.join(kumiawase):
                raise RuntimeError(f'invalid 5-minute combination at {race_key}')
            offset = position * 120 + j
            if statuses[offset] != STATUS['MISSING_SOURCE']:
                raise RuntimeError(f'UNRESOLVED_DUPLICATE 5-minute race/combination {race_key}/{kumiawase}')
            numeric[offset], statuses[offset] = dump_value(token, reason)
            raw[offset] = b'' if token == NULL else token.encode('ascii')
            reason_counts[reason] += 1
            selected_rows += 1
            selected_races.add(race_key)
        assert proc.stderr is not None
        stderr = proc.stderr.read()
        return_code = proc.wait()
        if return_code != 0 or not copy_seen or not copy_ended:
            raise RuntimeError(f'5-minute dump decode failed: rc={return_code}, '
                               f'copy={copy_seen}/{copy_ended}, stderr={stderr[:300]}')
    except BaseException:
        proc.kill()
        proc.wait()
        raise
    return {'source_races_joined': len(selected_races), 'source_rows_joined': selected_rows,
            'missing_reasons': dict(reason_counts),
            'response_sha256_by_race': response_hashes,
            'retrieved_at_by_race': retrieved_times}


def coverage(statuses: np.ndarray) -> dict:
    valid = statuses.reshape(-1, 120) == STATUS['VALID']
    counts = valid.sum(axis=1)
    return {'target_races': len(counts), 'complete_races': int(np.count_nonzero(counts == 120)),
            'partial_races': int(np.count_nonzero((counts > 0) & (counts < 120))),
            'all_missing_races': int(np.count_nonzero(counts == 0)),
            'valid_rows': int(valid.sum()), 'missing_rows': int(valid.size - valid.sum()),
            'races_with_any_valid_odds': int(np.count_nonzero(counts > 0))}


def status_counts(statuses: np.ndarray) -> dict[str, int]:
    codes, counts = np.unique(statuses, return_counts=True)
    return {STATUS_NAME[int(code)]: int(count) for code, count in zip(codes, counts)}


def validate(data: dict[str, np.ndarray], c: np.ndarray, cs: np.ndarray,
             five: np.ndarray, fs: np.ndarray, c_raw: np.ndarray,
             five_raw: np.ndarray, confirmed_info: dict, five_info: dict) -> dict:
    n = len(data['race_id'])
    if (n != 6157320 or confirmed_info['source_rows_joined'] != confirmed_info['source_races_joined']
            or five_info['source_rows_joined'] != five_info['source_races_joined'] * 120):
        raise RuntimeError('source or probability grain mismatch')
    if (np.count_nonzero(cs != STATUS['MISSING_SOURCE'])
            != confirmed_info['source_rows_joined'] * 120
            or np.count_nonzero(fs != STATUS['MISSING_SOURCE'])
            != five_info['source_rows_joined']):
        raise RuntimeError('cross-series fill or missing-source classification detected')
    if np.any((cs == STATUS['VALID']) & (c_raw == b'')) or np.any(
            (fs == STATUS['VALID']) & (five_raw == b'')):
        raise RuntimeError('numeric odds lacks its own source raw value')
    for name, values, states, raw in (('confirmed', c, cs, c_raw),
                                     ('five_minute', five, fs, five_raw)):
        valid = states == STATUS['VALID']
        if (np.any(~np.isfinite(values[valid])) or np.any(values[valid] <= 0)
                or np.any(~np.isnan(values[~valid]))
                or np.any(raw[states == STATUS['MISSING_SOURCE']] != b'')):
            raise RuntimeError(f'{name} numeric NULL/status or raw source validation failed')
    if file_hash(PROBABILITY) != PROBABILITY_SHA256:
        raise RuntimeError('probability artifact changed during build')
    return {'grain_duplicate_rows': 0, 'duplicate_boat_rows': 0,
            'duplicate_probability_join_rows': 0, 'probability_rows_without_odds_row': 0,
            'cross_series_source_violations': 0,
            'rows_with_both_series_valid': int(np.count_nonzero(
                (cs == STATUS['VALID']) & (fs == STATUS['VALID']))),
            'confirmed_to_five_minute_fill_rows': 0,
            'five_minute_to_confirmed_fill_rows': 0,
            'nonpositive_numeric_rows': 0, 'missing_numeric_not_null_rows': 0,
            'probability_race_join_rows': 51311, 'probability_combination_join_rows': n}


def main() -> None:
    if OUTPUT.exists() or REPORT.exists():
        raise RuntimeError('odds dataset output exists; refusing overwrite')
    data, positions = load_cohort()
    venue, race_no, natural_positions = core_identity(data, positions)
    rows = len(data['race_id'])
    c = np.full(rows, np.nan, dtype=np.float64)
    five = np.full(rows, np.nan, dtype=np.float64)
    cs = np.zeros(rows, dtype=np.uint8)
    fs = np.zeros(rows, dtype=np.uint8)
    c_raw = np.zeros(rows, dtype='S6')
    five_raw = np.zeros(rows, dtype='S16')
    confirmed_info = confirmed_source(natural_positions, c, cs, c_raw)
    five_info = five_minute_source(natural_positions, five, fs, five_raw)
    validation = validate(data, c, cs, five, fs, c_raw, five_raw,
                          confirmed_info, five_info)
    response_hashes = five_info.pop('response_sha256_by_race')
    retrieved_times = five_info.pop('retrieved_at_by_race')
    if len(response_hashes) != five_info['source_races_joined']:
        raise RuntimeError('5-minute response provenance count mismatch')
    if len(retrieved_times) != five_info['source_races_joined']:
        raise RuntimeError('5-minute retrieval provenance count mismatch')
    arrays = {**data, 'venue_code': np.repeat(venue, 120),
              'race_no': np.repeat(race_no, 120),
              'confirmed_odds': c, 'confirmed_odds_status': cs,
              'confirmed_odds_raw': c_raw,
              'odds_5min': five, 'odds_5min_status': fs,
              'odds_5min_raw': five_raw}
    temporary = OUTPUT.with_suffix('.npz.tmp')
    with temporary.open('xb') as stream:
        np.savez_compressed(stream, **arrays)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, OUTPUT)
    with np.load(OUTPUT, allow_pickle=False) as check:
        if set(check.files) != set(arrays) or any(
                not np.array_equal(check[k], v, equal_nan=k in ('confirmed_odds', 'odds_5min'))
                for k, v in arrays.items()):
            raise RuntimeError('odds artifact read-back mismatch')
    result = {
        'verdict': 'TRIFECTA_ODDS_DATASET_V1_READY',
        'period': '2025-01-01 through 2025-12-31',
        'target_probability_artifact': str(PROBABILITY.relative_to(ROOT)),
        'target_probability_sha256': PROBABILITY_SHA256,
        'grain': 'race_id x first_boat x second_boat x third_boat',
        'rows': rows, 'races': len(positions), 'columns': list(arrays),
        'null_encoding': 'numeric NaN with status != VALID; odds_or_none returns None',
        'status_codes': STATUS,
        'confirmed_source': {'table': 'pckyotei.public.brd_o6',
            'columns': ['kaisai_nen', 'kaisai_tsukihi', 'kyoteijo_code', 'race_no',
                        'record_id', 'data_kubun', 'odds_koshinjikan', 'odds_sanrentan'],
            'source_shimekiri': 'not a column; O6 data_kubun=3 is the confirmed series',
            **confirmed_info},
        'five_minute_source': {'table': 'preserved dump br_model.kyoteibiyori_odds_5min',
            'dump_sha256': DUMP_SHA256, 'source_shimekiri': 5,
            'historical_snapshot_timestamp': None,
            'columns': ['race_id', 'race_date', 'kyoteijo_code', 'race_no',
                        'bet_type', 'kumiawase', 'combination', 'odds_5min',
                        'odds_missing_reason', 'source_endpoint', 'source_shimekiri',
                        'response_sha256', 'retrieved_at'], **five_info,
            'response_sha256_by_race': response_hashes},
        'five_minute_retrieved_at_by_race': retrieved_times,
        'confirmed_coverage': coverage(cs),
        'five_minute_coverage': coverage(fs),
        'confirmed_status_counts': status_counts(cs),
        'five_minute_status_counts': status_counts(fs),
        'validation': validation,
        'artifact': str(OUTPUT.relative_to(ROOT)), 'artifact_sha256': file_hash(OUTPUT),
    }
    temporary_report = REPORT.with_suffix('.json.tmp')
    with temporary_report.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary_report, REPORT)
    print(json.dumps({k: result[k] for k in ('verdict', 'races', 'rows',
        'confirmed_coverage', 'five_minute_coverage', 'validation', 'artifact_sha256')},
        sort_keys=True, allow_nan=False), flush=True)


if __name__ == '__main__':
    main()
