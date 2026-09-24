"""2024 development diagnostic for frozen sequential P1/P2/P2 trifecta.

The only result query is for eligible 2024 races' K3 third-place labels.
No 2025 race, label, feature, or probability is queried.
"""
from __future__ import annotations

import hashlib
import itertools
import json
from pathlib import Path

import numpy as np

from scripts.db import target_connection
from scripts.p1_p2_baseline_v1 import load_cache


ROOT = Path(__file__).resolve().parents[1]
PREDICTIONS = ROOT / 'artifacts/natural_environment_v1_development_predictions.npz'
FREEZE = ROOT / 'artifacts/natural_environment_v1_freeze.json'
OUTPUT = ROOT / 'artifacts/natural_environment_v1_trifecta_2024.json'
COMBINATIONS = np.asarray(list(itertools.permutations(range(6), 3)), dtype=np.uint8)
FIRST, SECOND, THIRD = (COMBINATIONS[:, i] for i in range(3))
THIRD_SQL = """
SELECT z.race_id,z.boat_no,b.source_table
FROM core.race_result z
JOIN core.race r USING(race_id)
JOIN core.prediction_dataset_v1 d
  ON d.race_id=z.race_id AND d.boat_no=z.boat_no
JOIN raw.source_record sr ON sr.source_record_id=z.source_record_id
JOIN raw.source_batch b ON b.source_batch_id=sr.source_batch_id
WHERE r.race_date >= DATE '2024-01-01'
  AND r.race_date < DATE '2025-01-01'
  AND d.label_eligible=TRUE
  AND z.finish_position=3
ORDER BY r.race_date,z.race_id
"""


def sequential_probabilities(p1, p2):
    """Apply the existing sequential_p1_p2_p2_v1 formula to six-boat arrays."""
    if p1.shape != p2.shape or p1.ndim != 2 or p1.shape[1] != 6:
        raise ValueError('P1/P2 must have race x 6 shape')
    # Stored development probabilities are float32. Restore exact row sums
    # after serialization before applying the sequential conditional formula.
    p1, p2 = np.asarray(p1, dtype=np.float64), np.asarray(p2, dtype=np.float64)
    if (not np.isfinite(p1).all() or not np.isfinite(p2).all()
            or np.any(p1 < 0) or np.any(p2 < 0)
            or np.any(p1.sum(axis=1) <= 0) or np.any(p2.sum(axis=1) <= 0)):
        raise RuntimeError('invalid P1/P2 probabilities')
    p1 = p1 / p1.sum(axis=1, keepdims=True)
    p2 = p2 / p2.sum(axis=1, keepdims=True)
    output = np.empty((len(p1), 120), dtype=np.float64)
    for start in range(0, len(p1), 1024):
        stop = min(start + 1024, len(p1))
        first = p1[start:stop]
        second = p2[start:stop]
        denom2 = second.sum(axis=1, keepdims=True) - second[:, FIRST]
        denom3 = denom2 - second[:, SECOND]
        if (np.any(denom2 <= 0) or np.any(denom3 <= 0)
                or not np.isfinite(denom2).all() or not np.isfinite(denom3).all()):
            raise RuntimeError('invalid conditional P2 denominator')
        output[start:stop] = (first[:, FIRST] * (second[:, SECOND] / denom2)
                              * (second[:, THIRD] / denom3))
    if (not np.isfinite(output).all() or np.any(output <= 0)
            or not np.allclose(output.sum(axis=1), 1.0, atol=2e-10)):
        raise RuntimeError('trifecta probabilities are not coherent')
    return output


def third_places(expected_ids):
    conn = target_connection()
    try:
        conn.commit()
        conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
        with conn.cursor() as cur:
            cur.execute(THIRD_SQL)
            rows = cur.fetchall()
        third = {}
        for race_id, boat_no, source in rows:
            if source != 'brd_k3':
                raise RuntimeError('third-place label has non-K3 lineage')
            if race_id in third:
                raise RuntimeError('duplicate third-place label')
            third[race_id] = boat_no - 1
        expected = set(int(x) for x in expected_ids)
        if set(third) != expected:
            raise RuntimeError(f'K3 third-place race set mismatch: missing={len(expected - set(third))}, extra={len(set(third) - expected)}')
        return np.asarray([third[int(x)] for x in expected_ids], dtype=np.uint8)
    finally:
        conn.close()


def evaluate():
    base = load_cache()
    mask = base['years'] == 2024
    with np.load(PREDICTIONS, allow_pickle=False) as z:
        ids = z['race_ids']
        years = z['years']
        p1, p2 = z['P1_2024_post'], z['P2_2024_post']
    if (not np.array_equal(ids, base['race_ids'][mask])
            or not np.all(years == 2024)
            or len(ids) != len(p1) or len(ids) != len(p2)):
        raise RuntimeError('2024 prediction and baseline race identity mismatch')
    third = third_places(ids)
    first, second = base['winners'][mask], base['seconds'][mask]
    actual = np.column_stack((first, second, third))
    if (np.any(actual > 5) or np.any(first == second)
            or np.any(first == third) or np.any(second == third)):
        raise RuntimeError('invalid actual 2024 trifecta')
    matches = np.all(actual[:, None, :] == COMBINATIONS[None, :, :], axis=2)
    if np.any(matches.sum(axis=1) != 1):
        raise RuntimeError('actual trifecta mapping failed')
    actual_index = matches.argmax(axis=1)
    probabilities = sequential_probabilities(p1, p2)
    actual_p = probabilities[np.arange(len(ids)), actual_index]
    rank = np.argsort(-probabilities, axis=1, kind='stable')
    positions = np.argmax(rank == actual_index[:, None], axis=1) + 1
    result = {'method': 'sequential_p1_p2_p2_v1', 'year': 2024,
        'races': len(ids), 'result_source': 'brd_k3',
        'trifecta_log_loss': float(np.mean(-np.log(actual_p))),
        'brier_120_class': float(np.mean(np.sum(probabilities ** 2, axis=1) - 2 * actual_p + 1)),
        'actual_probability_mean': float(np.mean(actual_p)),
        'actual_probability_median': float(np.median(actual_p)),
        **{f'top{k}_hit_rate': float(np.mean(positions <= k)) for k in (1, 3, 5, 10)},
        'input_prediction_sha256': hashlib.sha256(PREDICTIONS.read_bytes()).hexdigest(),
        'code_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + '\n',
                      encoding='utf-8')
    freeze = json.loads(FREEZE.read_text(encoding='utf-8'))
    if freeze['verdict'] != 'NATURAL_ENVIRONMENT_V1_PREHOLDOUT_FROZEN':
        raise RuntimeError('unexpected Natural Environment freeze verdict')
    freeze['diagnostics_2024'] = {'trifecta_path': str(OUTPUT.relative_to(ROOT)),
        'trifecta_sha256': hashlib.sha256(OUTPUT.read_bytes()).hexdigest()}
    FREEZE.write_text(json.dumps(freeze, indent=2, sort_keys=True, allow_nan=False) + '\n',
                      encoding='utf-8')
    print(json.dumps(result, sort_keys=True), flush=True)
    return result


if __name__ == '__main__':
    evaluate()
