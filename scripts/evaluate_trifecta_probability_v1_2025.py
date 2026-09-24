"""Evaluate frozen 2025 P1/P2 predictions as 120 trifecta probabilities."""
from __future__ import annotations

import hashlib
import itertools
import json
import os
from pathlib import Path

import numpy as np

from scripts.db import target_connection


ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / 'artifacts/p1_p2_baseline_v1_2025_holdout_predictions.npz'
OUTPUT = ROOT / 'artifacts/trifecta_probability_v1_2025.npz'
METRICS = ROOT / 'artifacts/trifecta_probability_v1_2025_metrics.json'
INPUT_SHA256 = 'b05869f2df22477c17851014f8a9b4aca7dfb006acdf433b5a6cc1df7bf7915a'
METHOD = 'sequential_p1_p2_p2_v1'
VERDICT = 'TRIFECTA_PROBABILITY_V1_2025_EVALUATION_COMPLETE'
COMBINATIONS = np.asarray(list(itertools.permutations(range(1, 7), 3)), dtype=np.uint8)
FIRST, SECOND, THIRD = (COMBINATIONS[:, i].astype(np.intp) - 1 for i in range(3))
REMAINING_2 = np.asarray([[i for i in range(6) if i != a] for a in FIRST], dtype=np.intp)
REMAINING_3 = np.asarray([[i for i in range(6) if i not in (a, b)]
                          for a, b in zip(FIRST, SECOND)], dtype=np.intp)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def load_input() -> dict[str, np.ndarray]:
    if sha256(INPUT) != INPUT_SHA256:
        raise RuntimeError('frozen 2025 prediction artifact hash mismatch')
    with np.load(INPUT, allow_pickle=False) as source:
        expected = {'race_id', 'race_date_yyyymmdd', 'boat_no', 'label_p1',
                    'label_p2', 'pred_p1', 'pred_p2'}
        if set(source.files) != expected:
            raise RuntimeError('unexpected input arrays')
        data = {key: source[key] for key in expected}
    n = len(data['race_id'])
    if (n != 51311 or data['race_date_yyyymmdd'].shape != (n,)
            or any(data[key].shape != (n, 6) for key in expected - {'race_id', 'race_date_yyyymmdd'})
            or len(np.unique(data['race_id'])) != n
            or np.any((data['race_date_yyyymmdd'] < 20250101)
                      | (data['race_date_yyyymmdd'] > 20251231))
            or not np.all(data['boat_no'] == np.arange(1, 7))):
        raise RuntimeError('unexpected 2025 race identity or shape')
    for label in ('label_p1', 'label_p2'):
        y = data[label]
        if np.any((y != 0) & (y != 1)) or np.any(y.sum(axis=1) != 1):
            raise RuntimeError(f'invalid {label}')
    if np.any((data['label_p1'] & data['label_p2']) != 0):
        raise RuntimeError('first and second labels overlap')
    for target in ('pred_p1', 'pred_p2'):
        p = data[target]
        if (not np.isfinite(p).all() or np.any((p < 0) | (p > 1))
                or np.any(np.abs(p.sum(axis=1) - 1) > 2e-7)):
            raise RuntimeError(f'invalid frozen {target}')
    return data


def third_boats_from_k3(data: dict[str, np.ndarray]) -> np.ndarray:
    """Read only the K3-lineaged finish ranks for exactly the artifact cohort."""
    n = len(data['race_id'])
    third = np.empty(n, dtype=np.uint8)
    conn = target_connection()
    try:
        conn.commit()
        conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
        with conn.cursor() as check:
            check.execute("SELECT current_setting('transaction_read_only')")
            if check.fetchone()[0] != 'on':
                raise RuntimeError('K3 label read must be read-only')
        with conn.cursor(name='trifecta_2025_k3_labels') as cur:
            cur.itersize = 10000
            cur.execute("""
                SELECT z.race_id,d.race_date,z.boat_no,z.finish_position,b.source_table
                FROM core.prediction_dataset_v1 d
                JOIN core.race_result z USING(race_id,boat_no)
                JOIN raw.source_record s ON s.source_record_id=z.source_record_id
                JOIN raw.source_batch b ON b.source_batch_id=s.source_batch_id
                WHERE d.label_eligible = TRUE
                  AND d.race_date >= DATE '2025-01-01'
                  AND d.race_date < DATE '2026-01-01'
                ORDER BY d.race_date,d.race_id,d.boat_no
            """)
            ranks = []
            count = 0
            for race_id, race_date, boat, finish, source in cur:
                if count >= n * 6:
                    raise RuntimeError('K3 label rows exceed frozen cohort')
                r, j = divmod(count, 6)
                date_code = race_date.year * 10000 + race_date.month * 100 + race_date.day
                if (race_id != int(data['race_id'][r])
                        or date_code != int(data['race_date_yyyymmdd'][r])
                        or boat != j + 1 or source != 'brd_k3'
                        or finish not in range(1, 7)):
                    raise RuntimeError(f'K3 label identity or lineage mismatch at row {count}')
                ranks.append(finish)
                if j == 5:
                    if (sorted(ranks) != list(range(1, 7))
                            or ranks.index(1) != int(np.argmax(data['label_p1'][r]))
                            or ranks.index(2) != int(np.argmax(data['label_p2'][r]))):
                        raise RuntimeError(f'K3 finish ranks differ from frozen labels at race {race_id}')
                    third[r] = ranks.index(3) + 1
                    ranks.clear()
                count += 1
            if count != n * 6:
                raise RuntimeError(f'K3 label row count mismatch: {count} != {n * 6}')
    finally:
        conn.close()
    return third


def probabilities(p1: np.ndarray, p2: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Return race x 120 probabilities and evaluability, without fallback."""
    if p1.shape != p2.shape or p1.ndim != 2 or p1.shape[1] != 6:
        raise ValueError('P1/P2 must be race x 6')
    n = len(p1)
    result = np.full((n, 120), np.nan, dtype=np.float64)
    evaluable = np.zeros(n, dtype=bool)
    for start in range(0, n, 1024):
        stop = min(start + 1024, n)
        a, b = p1[start:stop], p2[start:stop]
        denominator_2 = b[:, REMAINING_2].sum(axis=2)
        denominator_3 = b[:, REMAINING_3].sum(axis=2)
        good = ((denominator_2 > 0) & np.isfinite(denominator_2)
                & (denominator_3 > 0) & np.isfinite(denominator_3)).all(axis=1)
        if np.any(good):
            values = (a[good][:, FIRST] * (b[good][:, SECOND] / denominator_2[good])
                      * (b[good][:, THIRD] / denominator_3[good]))
            good_indices = np.flatnonzero(good)
            finite = np.isfinite(values).all(axis=1)
            if np.any(finite):
                result[start + good_indices[finite]] = values[finite]
                evaluable[start + good_indices[finite]] = True
    return result, evaluable


def actual_indices(data: dict[str, np.ndarray], third: np.ndarray) -> np.ndarray:
    first = np.argmax(data['label_p1'], axis=1) + 1
    second = np.argmax(data['label_p2'], axis=1) + 1
    actual = np.column_stack((first, second, third))
    matches = np.all(actual[:, None, :] == COMBINATIONS[None, :, :], axis=2)
    if np.any(matches.sum(axis=1) != 1):
        raise RuntimeError('actual trifecta must match exactly one combination')
    return np.argmax(matches, axis=1)


def evaluate(data: dict[str, np.ndarray], third: np.ndarray) -> tuple[dict, np.ndarray, np.ndarray]:
    p, valid = probabilities(data['pred_p1'], data['pred_p2'])
    if (len(COMBINATIONS) != 120 or np.any(COMBINATIONS[:, 0] == COMBINATIONS[:, 1])
            or np.any(COMBINATIONS[:, 0] == COMBINATIONS[:, 2])
            or np.any(COMBINATIONS[:, 1] == COMBINATIONS[:, 2])):
        raise RuntimeError('invalid trifecta combinations')
    if (not np.isfinite(p[valid]).all() or np.any(p[valid] < 0)
            or np.any(np.abs(p[valid].sum(axis=1) - 1) > 2e-10)):
        raise RuntimeError('trifecta probability validation failed')
    actual = actual_indices(data, third)
    if not np.any(valid):
        raise RuntimeError('no evaluable 2025 races')
    pv = p[valid]
    av = actual[valid]
    actual_p = pv[np.arange(len(pv)), av]
    if np.any(actual_p <= 0):
        raise RuntimeError('zero actual trifecta probability; log loss undefined')
    order = np.argsort(-pv, axis=1, kind='stable')
    ranks = np.argmax(order == av[:, None], axis=1) + 1
    scores = {
        'trifecta_log_loss': float(np.mean(-np.log(actual_p))),
        'brier_120_class': float(np.mean(np.sum(pv * pv, axis=1) - 2 * actual_p + 1)),
        'actual_probability_mean': float(np.mean(actual_p)),
        'actual_probability_median': float(np.median(actual_p)),
        **{f'top{k}_hit_rate': float(np.mean(ranks <= k)) for k in (1, 3, 5, 10)},
    }
    return scores, p, valid


def output_arrays(data: dict[str, np.ndarray], p: np.ndarray, valid: np.ndarray,
                  actual: np.ndarray) -> dict[str, np.ndarray]:
    n = int(valid.sum())
    return {
        'race_id': np.repeat(data['race_id'][valid], 120),
        'race_date_yyyymmdd': np.repeat(data['race_date_yyyymmdd'][valid], 120),
        'first_boat': np.tile(COMBINATIONS[:, 0], n),
        'second_boat': np.tile(COMBINATIONS[:, 1], n),
        'third_boat': np.tile(COMBINATIONS[:, 2], n),
        'trifecta_probability': p[valid].reshape(-1),
        'is_actual': (np.arange(120)[None, :] == actual[valid, None]).reshape(-1),
    }


def main() -> None:
    if OUTPUT.exists() or METRICS.exists():
        raise RuntimeError('trifecta output already exists; refusing overwrite')
    data = load_input()
    third = third_boats_from_k3(data)
    scores, p, valid = evaluate(data, third)
    actual = actual_indices(data, third)
    arrays = output_arrays(data, p, valid, actual)
    n = len(arrays['race_id'])
    if (n != int(valid.sum()) * 120 or sum(arrays['is_actual']) != int(valid.sum())
            or any(len(value) != n for value in arrays.values())):
        raise RuntimeError('output row validation failed')
    if sha256(INPUT) != INPUT_SHA256:
        raise RuntimeError('input artifact changed during evaluation')
    temporary = OUTPUT.with_suffix('.npz.tmp')
    with temporary.open('xb') as stream:
        np.savez_compressed(stream, **arrays)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, OUTPUT)
    with np.load(OUTPUT, allow_pickle=False) as check:
        if set(check.files) != set(arrays) or any(not np.array_equal(check[key], value)
                                                  for key, value in arrays.items()):
            raise RuntimeError('trifecta artifact read-back mismatch')
    uniform = float(np.log(120))
    result = {
        'verdict': VERDICT, 'method': METHOD,
        'period': '2025-01-01 through 2025-12-31',
        'input_artifact': str(INPUT.relative_to(ROOT)), 'input_sha256': INPUT_SHA256,
        'third_label_source': 'core.race_result.finish_position; raw.source_batch.source_table = brd_k3',
        'eligible_races': len(data['race_id']),
        'evaluable_races': int(valid.sum()),
        'not_evaluable_races': int((~valid).sum()),
        'not_evaluable_race_ids': data['race_id'][~valid].tolist(),
        'combinations_per_evaluable_race': 120, 'artifact_rows': n,
        'metrics': scores, 'uniform_log_loss_reference': uniform,
        'log_loss_minus_uniform': scores['trifecta_log_loss'] - uniform,
        'brier_definition': 'race mean of sum over 120 classes of (p - one_hot_actual)^2',
        'top_k_tie_rule': 'descending probability, stable lexicographic combination order',
        'validation': {'combination_count_violations': 0, 'duplicate_boat_violations': 0,
                       'nonfinite_probability_violations': 0, 'negative_probability_violations': 0,
                       'probability_sum_violations': 0, 'actual_match_violations': 0,
                       'input_hash_after': sha256(INPUT), 'probability_sum_absolute_tolerance': 2e-10},
        'artifact': str(OUTPUT.relative_to(ROOT)), 'artifact_sha256': sha256(OUTPUT),
        'artifact_columns': list(arrays),
    }
    temporary_json = METRICS.with_suffix('.json.tmp')
    with temporary_json.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary_json, METRICS)
    print(json.dumps(result, sort_keys=True, allow_nan=False), flush=True)


if __name__ == '__main__':
    main()
