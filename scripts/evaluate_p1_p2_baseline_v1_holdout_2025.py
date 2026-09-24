"""Run the frozen P1 / exact-P2 baseline on the 2025 holdout exactly once."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import numpy as np

from scripts.db import target_connection
from scripts.p1_p2_baseline_v1 import (
    CATEGORICAL, NUMERIC, ROOT, metrics, probabilities, transform,
)


FREEZE = ROOT / 'artifacts/p1_p2_baseline_v1_freeze.json'
MODEL = ROOT / 'artifacts/p1_p2_baseline_v1_model.json'
GATE = ROOT / 'artifacts/p1_p2_baseline_v1_2025_holdout_gate.json'
PREDICTIONS = ROOT / 'artifacts/p1_p2_baseline_v1_2025_holdout_predictions.npz'
RESULT = ROOT / 'artifacts/p1_p2_baseline_v1_2025_holdout_metrics.json'
FREEZE_SHA256 = 'f7dcb2f64fbc345de64767dcf9723a52b4db972121f30320c85ee48ea606a9f4'
MODEL_SHA256 = '3954fbecb97dae5816b45e00735ab4ec31f13dbdb13d21c2c4022fca9d37f54e'
VERDICT = 'P1_P2_BASELINE_V1_2025_INDEPENDENT_HOLDOUT_COMPLETE'

# Same source columns and order as the frozen development extract. Only the
# date predicate changes; the pre-existing K3-only labels are read directly.
HOLDOUT_SQL = """
SELECT race_id,race_date,boat_no,
       national_win_rate,rating_first_course_1_to_6,
       rating_exact_second_course_1_to_6,rating_overall,
       entry_course_prob_1_to_6,current_term_f_count,rating_short_50,
       motor_a_base3,base_n_meetings,base_n_uses,base_residual_sum,
       motor_a_current,current_n_uses,
       national_win_rate_status,rating_player_status,entry_course_status,
       f_suspension_state,has_unserved_f_suspension,
       current_term_f_count_status,motor_a_base3_status,motor_a_current_status,
       label_p1,label_p2
FROM core.prediction_dataset_v1
WHERE label_eligible = TRUE
  AND race_date >= DATE '2025-01-01'
  AND race_date < DATE '2026-01-01'
ORDER BY race_date,race_id,boat_no
"""


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: dict) -> None:
    temporary = path.with_suffix(path.suffix + '.tmp')
    with temporary.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def preflight() -> dict:
    if sha(FREEZE) != FREEZE_SHA256 or sha(MODEL) != MODEL_SHA256:
        raise RuntimeError('frozen artifact hash mismatch; holdout not started')
    if any(path.exists() for path in (GATE, PREDICTIONS, RESULT)):
        raise RuntimeError('holdout already started or completed; refusing rerun')
    model = json.loads(MODEL.read_text(encoding='utf-8'))
    expected = {'P1': ('CORE_MOTOR', 1.0143334057206692, 78),
                'P2': ('FULL', 1.0066548794380772, 80)}
    for target, (bundle, temperature, features) in expected.items():
        fixed = model[target]
        prep = fixed['preprocessor']
        if (fixed['bundle'] != bundle or fixed['penalty'] != 0.01
                or fixed['temperature'] != temperature
                or len(fixed['coefficients']) != features
                or len(prep['feature_order']) != features
                or prep['fitted_years'] != list(range(2017, 2025))):
            raise RuntimeError(f'unexpected frozen {target} method')
    return model


def extract(model: dict) -> dict:
    conn = target_connection()
    try:
        conn.commit()
        conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
        with conn.cursor() as cur:
            cur.execute("SELECT current_setting('transaction_read_only')")
            if cur.fetchone()[0] != 'on':
                raise RuntimeError('holdout extract must be read-only')
            cur.execute("""SELECT count(*) FROM core.prediction_dataset_v1
                WHERE label_eligible = TRUE AND race_date >= DATE '2025-01-01'
                  AND race_date < DATE '2026-01-01'""")
            n = cur.fetchone()[0]
        if n == 0 or n % 6:
            raise RuntimeError(f'unexpected holdout row count: {n}')
        races = n // 6
        numeric = np.empty((n, len(NUMERIC)), dtype=np.float32)
        categories = np.empty((n, len(CATEGORICAL)), dtype=np.uint8)
        race_ids = np.empty(races, dtype=np.int64)
        race_dates = np.empty(races, dtype=np.int32)
        label_p1 = np.zeros((races, 6), dtype=np.uint8)
        label_p2 = np.zeros((races, 6), dtype=np.uint8)
        vocabulary = model['categorical_vocabulary']
        with conn.cursor(name='p1_p2_holdout_2025') as cur:
            cur.itersize = 10000
            cur.execute(HOLDOUT_SQL)
            i = 0
            for row in cur:
                (race_id, race_date, boat, national, first, second, overall,
                 entry, f_count, short, motor_base, base_meetings, base_uses,
                 base_sum, motor_current, current_uses, national_status,
                 player_status, entry_status, f_state, f_bool, f_count_status,
                 motor_base_status, motor_current_status, y1, y2) = row
                if i >= n or boat != i % 6 + 1 or race_date.year != 2025:
                    raise RuntimeError('unexpected holdout year, count or boat order')
                r = i // 6
                date_code = race_date.year * 10000 + race_date.month * 100 + race_date.day
                if boat == 1:
                    race_ids[r], race_dates[r] = race_id, date_code
                elif race_id != race_ids[r] or date_code != race_dates[r]:
                    raise RuntimeError('holdout race does not contain six contiguous boats')
                values = (national, *(first or [None] * 6),
                          *(second or [None] * 6), overall,
                          *(entry or [None] * 6), f_count, short, motor_base,
                          base_meetings, base_uses, base_sum, motor_current,
                          current_uses)
                numeric[i] = [float(v) if v is not None else np.nan for v in values]
                cat_values = (str(boat), national_status, player_status,
                              entry_status, f_state,
                              'MISSING' if f_bool is None else str(f_bool),
                              f_count_status, motor_base_status,
                              motor_current_status)
                for j, value in enumerate(cat_values):
                    key = str(value) if value is not None else 'MISSING'
                    categories[i, j] = vocabulary[j].get(key, 255)
                if y1 not in (0, 1) or y2 not in (0, 1):
                    raise RuntimeError('invalid eligible holdout label')
                label_p1[r, boat - 1] = y1
                label_p2[r, boat - 1] = y2
                i += 1
        if (i != n or np.any(label_p1.sum(axis=1) != 1)
                or np.any(label_p2.sum(axis=1) != 1)
                or np.any((label_p1 & label_p2) != 0)):
            raise RuntimeError('invalid holdout rows or race labels')
        if not np.isfinite(numeric[~np.isnan(numeric)]).all():
            raise RuntimeError('non-finite source numeric')
        return dict(numeric=numeric, categories=categories,
                    race_ids=race_ids, race_dates=race_dates,
                    label_p1=label_p1, label_p2=label_p2)
    finally:
        conn.close()


def evaluate(data: dict, model: dict) -> tuple[dict, dict]:
    races = len(data['race_ids'])
    result = {}
    arrays = dict(race_id=data['race_ids'], race_date_yyyymmdd=data['race_dates'],
                  boat_no=np.broadcast_to(np.arange(1, 7, dtype=np.uint8),
                                          (races, 6)).copy(),
                  label_p1=data['label_p1'], label_p2=data['label_p2'])
    for target, label in (('P1', 'label_p1'), ('P2', 'label_p2')):
        fixed = model[target]
        x = transform(data, fixed['preprocessor'], np.ones(races, dtype=bool))
        scores = (x.reshape(-1, x.shape[-1])
                  @ np.asarray(fixed['coefficients'], dtype=np.float64)).reshape(-1, 6)
        p = probabilities(scores, fixed['temperature'])
        violations = {
            'probability_nonfinite': int(np.count_nonzero(~np.isfinite(p))),
            'probability_out_of_range': int(np.count_nonzero((p < 0) | (p > 1))),
            'race_probability_sum': int(np.count_nonzero(
                ~np.isfinite(p.sum(axis=1)) | (np.abs(p.sum(axis=1) - 1) > 2e-7))),
        }
        if any(violations.values()):
            raise RuntimeError(f'{target} probability violations: {violations}')
        winner = np.argmax(data[label], axis=1)
        result[target] = {'bundle': fixed['bundle'], 'l2': fixed['penalty'],
                          'temperature': fixed['temperature'],
                          'metrics': metrics(scores, winner, fixed['temperature']),
                          'validation': violations}
        arrays[f'pred_{target.lower()}'] = p
    return result, arrays


def main() -> None:
    model = preflight()
    # Exclusive creation is the one-shot boundary. A failed run stays STARTED;
    # it must not silently evaluate the same holdout again.
    with GATE.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump({'status': 'STARTED', 'freeze_sha256': FREEZE_SHA256,
                   'model_sha256': MODEL_SHA256}, stream, sort_keys=True)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    data = extract(model)
    target_results, arrays = evaluate(data, model)
    temporary = PREDICTIONS.with_suffix('.npz.tmp')
    with temporary.open('xb') as stream:
        np.savez_compressed(stream, **arrays)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, PREDICTIONS)
    result = {
        'verdict': VERDICT, 'source_table': 'core.prediction_dataset_v1',
        'filter': "label_eligible = TRUE AND race_date >= DATE '2025-01-01' AND race_date < DATE '2026-01-01'",
        'label_source': 'existing K3-only prediction_dataset_v1 labels',
        'eligible_races': len(data['race_ids']), 'rows': len(data['numeric']),
        'freeze_sha256': FREEZE_SHA256, 'model_sha256': MODEL_SHA256,
        'prediction_artifact': str(PREDICTIONS.relative_to(ROOT)),
        'prediction_sha256': sha(PREDICTIONS),
        'prediction_shape': 'race_id and race_date_yyyymmdd: (races,); boat_no, label_p1, label_p2, pred_p1, pred_p2: (races, 6)',
        'P1': target_results['P1'], 'P2': target_results['P2'],
    }
    write_json(RESULT, result)
    write_json(GATE, {'status': 'COMPLETED', 'verdict': VERDICT,
                      'freeze_sha256': FREEZE_SHA256, 'model_sha256': MODEL_SHA256,
                      'metrics_sha256': sha(RESULT),
                      'prediction_sha256': sha(PREDICTIONS)})
    print(json.dumps(result, sort_keys=True, allow_nan=False), flush=True)


if __name__ == '__main__':
    main()
