"""Pre-2025 P1 / exact-P2 race-wise linear softmax development and freeze.

Only eligible 2017-2024 rows are queried. The date bound is deliberately literal.
The extract cache is local and is never a substitute for the recorded source hash.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.optimize import minimize, minimize_scalar
from scipy.special import logsumexp

from scripts.db import target_connection


ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / '.local/p1_p2_baseline_v1_development.npz'
FREEZE = ROOT / 'artifacts/p1_p2_baseline_v1_freeze.json'
MODEL = ROOT / 'artifacts/p1_p2_baseline_v1_model.json'
PREDICTIONS = ROOT / 'artifacts/p1_p2_baseline_v1_development_predictions.npz'
YEARS = tuple(range(2017, 2025))
PENALTIES = (0.01, 0.1, 1.0, 10.0, 100.0)
BUNDLES = ('CORE', 'CORE_SHORT', 'CORE_MOTOR', 'FULL')
NUMERIC = (
    'national_win_rate',
    *(f'rating_first_course_{i}' for i in range(1, 7)),
    *(f'rating_exact_second_course_{i}' for i in range(1, 7)),
    'rating_overall',
    *(f'entry_course_prob_{i}' for i in range(1, 7)),
    'current_term_f_count', 'rating_short_50',
    'motor_a_base3', 'base_n_meetings', 'base_n_uses',
    'base_residual_sum', 'motor_a_current', 'current_n_uses',
)
CATEGORICAL = (
    'boat_no', 'national_win_rate_status', 'rating_player_status',
    'entry_course_status', 'f_suspension_state',
    'has_unserved_f_suspension', 'current_term_f_count_status',
    'motor_a_base3_status', 'motor_a_current_status',
)
CORE_NUMERIC = NUMERIC[:21]
SHORT_NUMERIC = NUMERIC[21:22]
MOTOR_NUMERIC = NUMERIC[22:]
CORE_CATEGORICAL = CATEGORICAL[:7]
MOTOR_CATEGORICAL = CATEGORICAL[7:]

# No reference to a result source is needed: the dataset's K3-only labels are used.
EXTRACT_SQL = """
SELECT race_id,EXTRACT(YEAR FROM race_date)::integer AS year,boat_no,
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
  AND race_date >= DATE '2017-01-01'
  AND race_date < DATE '2025-01-01'
ORDER BY race_date,race_id,boat_no
"""


def bundle_columns(bundle):
    nums = list(CORE_NUMERIC)
    cats = list(CORE_CATEGORICAL)
    if bundle in ('CORE_SHORT', 'FULL'):
        nums += SHORT_NUMERIC
    if bundle in ('CORE_MOTOR', 'FULL'):
        nums += MOTOR_NUMERIC
        cats += MOTOR_CATEGORICAL
    return nums, cats


def extract():
    """Read an eligible, strictly pre-2025 snapshot and save a local numeric cache."""
    conn = target_connection()
    try:
        conn.commit()  # target_connection verifies the role before read-only mode.
        conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
        with conn.cursor() as cur:
            cur.execute("SELECT current_setting('transaction_read_only')")
            if cur.fetchone()[0] != 'on':
                raise RuntimeError('development extract must be read-only')
            cur.execute("""SELECT EXTRACT(YEAR FROM race_date)::integer, count(*)
                FROM core.prediction_dataset_v1 WHERE label_eligible = TRUE
                  AND race_date >= DATE '2017-01-01'
                  AND race_date < DATE '2025-01-01'
                GROUP BY 1 ORDER BY 1""")
            counts = dict(cur.fetchall())
        if tuple(counts) != YEARS or any(n % 6 for n in counts.values()):
            raise RuntimeError(f'unexpected development year or six-boat count: {counts}')
        n = sum(counts.values())
        numeric = np.empty((n, len(NUMERIC)), dtype=np.float32)
        categories = np.empty((n, len(CATEGORICAL)), dtype=np.uint8)
        race_ids = np.empty(n // 6, dtype=np.int64)
        years = np.empty(n // 6, dtype=np.int16)
        winners = np.empty(n // 6, dtype=np.uint8)
        seconds = np.empty(n // 6, dtype=np.uint8)
        dictionaries = [dict() for _ in CATEGORICAL]
        with conn.cursor(name='p1_p2_development_only') as cur:
            cur.itersize = 10000
            cur.execute(EXTRACT_SQL)
            i = 0
            for row in cur:
                (race_id, year, boat, national, first, second, overall, entry,
                 f_count, short, motor_base, base_meetings,
                 base_uses, base_sum, motor_current, current_uses,
                 national_status, player_status, entry_status, f_state, f_bool,
                 f_count_status, motor_base_status, motor_current_status,
                 y1, y2) = row
                if i >= n or year not in YEARS or boat != i % 6 + 1:
                    raise RuntimeError('unexpected extract row count, year or boat order')
                if i % 6 == 0:
                    race_ids[i // 6], years[i // 6] = race_id, year
                    winners[i // 6], seconds[i // 6] = 255, 255
                elif race_id != race_ids[i // 6] or year != years[i // 6]:
                    raise RuntimeError('race grain is not six contiguous boats')
                values = (national, *(first or [None] * 6),
                          *(second or [None] * 6), overall,
                          *(entry or [None] * 6), f_count,
                          short, motor_base, base_meetings,
                          base_uses, base_sum, motor_current, current_uses)
                numeric[i] = [float(v) if v is not None else np.nan for v in values]
                cat_values = (str(boat), national_status, player_status,
                              entry_status, f_state,
                              'MISSING' if f_bool is None else str(f_bool),
                              f_count_status, motor_base_status,
                              motor_current_status)
                for j, value in enumerate(cat_values):
                    key = str(value) if value is not None else 'MISSING'
                    vocabulary = dictionaries[j]
                    if key not in vocabulary:
                        if len(vocabulary) >= 255:
                            raise RuntimeError('categorical vocabulary exceeds uint8')
                        vocabulary[key] = len(vocabulary)
                    categories[i, j] = vocabulary[key]
                if y1 == 1:
                    if winners[i // 6] != 255:
                        raise RuntimeError('multiple P1 labels')
                    winners[i // 6] = boat - 1
                if y2 == 1:
                    if seconds[i // 6] != 255:
                        raise RuntimeError('multiple P2 labels')
                    seconds[i // 6] = boat - 1
                if y1 not in (0, 1) or y2 not in (0, 1):
                    raise RuntimeError('invalid eligible label')
                i += 1
        if i != n or np.any(winners > 5) or np.any(seconds > 5) or np.any(winners == seconds):
            raise RuntimeError('invalid row or race labels')
        if not np.isfinite(numeric[~np.isnan(numeric)]).all():
            raise RuntimeError('non-finite source numeric')
        vocab = [{str(k): int(v) for k, v in d.items()} for d in dictionaries]
        digest = hashlib.sha256()
        for array in (numeric, categories, race_ids, years, winners, seconds):
            digest.update(array.tobytes())
        digest.update(json.dumps(vocab, sort_keys=True).encode())
        CACHE.parent.mkdir(exist_ok=True)
        np.savez(CACHE, numeric=numeric, categories=categories,
                 race_ids=race_ids, years=years, winners=winners,
                 seconds=seconds, vocabulary=json.dumps(vocab, sort_keys=True),
                 source_sha256=digest.hexdigest())
        print(json.dumps({'phase': 'extract', 'rows': n, 'races': n // 6,
                          'years': counts, 'source_sha256': digest.hexdigest()}), flush=True)
    finally:
        conn.close()


def load_cache():
    with np.load(CACHE, allow_pickle=False) as z:
        data = {key: z[key] for key in ('numeric', 'categories', 'race_ids',
                'years', 'winners', 'seconds')}
        data['vocabulary'] = json.loads(str(z['vocabulary']))
        expected = str(z['source_sha256'])
    digest = hashlib.sha256()
    for key in ('numeric', 'categories', 'race_ids', 'years', 'winners', 'seconds'):
        digest.update(data[key].tobytes())
    digest.update(json.dumps(data['vocabulary'], sort_keys=True).encode())
    if digest.hexdigest() != expected or data['years'].min() != 2017 or data['years'].max() != 2024:
        raise RuntimeError('development cache identity/year mismatch')
    data['source_sha256'] = expected
    return data


def fit_preprocessor(data, bundle, train_races):
    """Every median, scale, and categorical level comes from train_races only."""
    num_names, cat_names = bundle_columns(bundle)
    num_idx = [NUMERIC.index(name) for name in num_names]
    cat_idx = [CATEGORICAL.index(name) for name in cat_names]
    rows = race_rows(train_races)
    raw = data['numeric'][rows][:, num_idx]
    medians = np.nanmedian(raw, axis=0)
    medians = np.where(np.isnan(medians), 0.0, medians)
    filled = np.where(np.isnan(raw), medians, raw)
    means = filled.mean(axis=0, dtype=np.float64)
    scales = filled.std(axis=0, dtype=np.float64)
    scales = np.where(scales > 1e-12, scales, 1.0)
    levels = []
    for idx in cat_idx:
        levels.append(sorted(int(v) for v in np.unique(data['categories'][rows, idx])))
    feature_order = ([f'{name}:z' for name in num_names]
                     + [f'{name}:missing' for name in num_names]
                     + [f'{name}={next(k for k, v in data["vocabulary"][CATEGORICAL.index(name)].items() if v == level)}'
                        for name, lev in zip(cat_names, levels) for level in lev])
    return dict(bundle=bundle, numeric_names=num_names, categorical_names=cat_names,
                medians=medians.tolist(), means=means.tolist(), scales=scales.tolist(),
                levels=levels, feature_order=feature_order,
                fitted_years=sorted(int(y) for y in np.unique(data['years'][train_races])))


def transform(data, prep, races):
    rows = race_rows(races)
    raw = data['numeric'][rows][:, [NUMERIC.index(x) for x in prep['numeric_names']]]
    missing = np.isnan(raw)
    filled = np.where(missing, prep['medians'], raw)
    dim = len(prep['feature_order'])
    x = np.empty((len(rows), dim), dtype=np.float32)
    p = len(prep['numeric_names'])
    x[:, :p] = (filled - prep['means']) / prep['scales']
    x[:, p:2 * p] = missing
    offset = 2 * p
    for name, levels in zip(prep['categorical_names'], prep['levels']):
        values = data['categories'][rows, CATEGORICAL.index(name)]
        for level in levels:
            x[:, offset] = values == level
            offset += 1
    if offset != dim or not np.isfinite(x).all():
        raise RuntimeError('invalid transformed matrix')
    # Softmax is invariant to adding the same score to all six boats.
    x = x.reshape(-1, 6, dim)
    x -= x.mean(axis=1, keepdims=True)
    return np.ascontiguousarray(x)


def race_rows(races):
    return (np.flatnonzero(races)[:, None] * 6 + np.arange(6)).reshape(-1)


def probabilities(scores, temperature=1.0):
    scaled = scores / temperature
    return np.exp(scaled - logsumexp(scaled, axis=1, keepdims=True))


def fit_model(x, target, penalty, initial=None):
    n, _, d = x.shape
    flat = x.reshape(-1, d)
    indices = np.arange(n)
    def objective(coef):
        scores = (flat @ coef).reshape(-1, 6)
        log_norm = logsumexp(scores, axis=1)
        p = np.exp(scores - log_norm[:, None])
        loss = (log_norm - scores[indices, target]).mean()
        p[indices, target] -= 1.0
        grad = (flat.T @ p.reshape(-1)).astype(np.float64) / n
        loss += 0.5 * penalty * np.dot(coef, coef)
        grad += penalty * coef
        return float(loss), grad
    result = minimize(objective, np.zeros(d) if initial is None else initial,
                      method='L-BFGS-B', jac=True,
                      options={'maxiter': 150, 'ftol': 1e-10, 'gtol': 1e-7})
    if not result.success and np.max(np.abs(result.jac)) > 2e-5:
        raise RuntimeError(f'optimizer failed: {result.message}; gradient={np.max(np.abs(result.jac))}')
    return result.x, {'iterations': int(result.nit),
                      'gradient_max': float(np.max(np.abs(result.jac)))}


def metrics(scores, target, temperature=1.0):
    p = probabilities(scores, temperature)
    n = len(target)
    if (not np.isfinite(p).all() or np.any(p < 0) or np.any(p > 1)
            or not np.allclose(p.sum(axis=1), 1.0, atol=2e-7)):
        raise RuntimeError('probability coherence failed')
    truth = np.zeros_like(p)
    truth[np.arange(n), target] = 1.0
    bins = np.minimum((p * 10).astype(np.int8), 9)
    ece = 0.0
    for b in range(10):
        mask = bins == b
        if np.any(mask):
            ece += abs(float(p[mask].sum() - truth[mask].sum())) / (6 * n)
    return {'races': int(n), 'log_loss': float(-np.log(p[np.arange(n), target]).mean()),
            'brier': float(np.sum((p - truth) ** 2, axis=1).mean()),
            'ece_10bin': ece,
            'top1': float(np.mean(np.argmax(p, axis=1) == target))}


def select(candidates):
    """10^-5 is the predeclared numerical tie band for both metrics."""
    best_log = min(c['mean_log_loss'] for c in candidates)
    tied = [c for c in candidates if c['mean_log_loss'] <= best_log + 1e-5]
    best_brier = min(c['mean_brier'] for c in tied)
    tied = [c for c in tied if c['mean_brier'] <= best_brier + 1e-5]
    return min(tied, key=lambda c: (BUNDLES.index(c['bundle']), c['penalty']))


def develop():
    data = load_cache()
    years = data['years']
    if set(np.unique(years)) != set(YEARS):
        raise RuntimeError('development years incomplete')
    selections = {'P1': [], 'P2': []}
    for validation_year in (2022, 2023):
        train = years < validation_year
        valid = years == validation_year
        if np.any(years[train] >= validation_year) or np.any(years[valid] != validation_year):
            raise RuntimeError('time split failed')
        for bundle in BUNDLES:
            prep = fit_preprocessor(data, bundle, train)
            if max(prep['fitted_years']) >= validation_year:
                raise RuntimeError('preprocessor looked at validation year')
            xtrain, xvalid = transform(data, prep, train), transform(data, prep, valid)
            for target_name, labels in (('P1', data['winners']), ('P2', data['seconds'])):
                previous = None
                for penalty in reversed(PENALTIES):
                    coef, solver = fit_model(xtrain, labels[train], penalty, previous)
                    previous = coef
                    score = (xvalid.reshape(-1, xvalid.shape[-1]) @ coef).reshape(-1, 6)
                    result = metrics(score, labels[valid])
                    selections[target_name].append(dict(year=validation_year, bundle=bundle,
                        penalty=penalty, metrics=result, solver=solver,
                        fitted_years=prep['fitted_years']))
                    print(json.dumps({'phase': 'selection', 'target': target_name,
                        'year': validation_year, 'bundle': bundle, 'penalty': penalty,
                        'log_loss': result['log_loss']}), flush=True)
    selected = {}
    for target_name, items in selections.items():
        candidates = []
        for bundle in BUNDLES:
            for penalty in PENALTIES:
                pair = [item for item in items if item['bundle'] == bundle and item['penalty'] == penalty]
                candidates.append(dict(bundle=bundle, penalty=penalty,
                    mean_log_loss=float(np.mean([x['metrics']['log_loss'] for x in pair])),
                    mean_brier=float(np.mean([x['metrics']['brier'] for x in pair]))))
        selected[target_name] = select(candidates)
        print(json.dumps({'phase': 'selected', 'target': target_name,
                          **selected[target_name]}), flush=True)
    # 2024 is used once for the chosen methods' scalar temperature.
    calibration = {}
    final_models = {}
    development_predictions = {}
    for target_name, labels in (('P1', data['winners']), ('P2', data['seconds'])):
        choice = selected[target_name]
        train = years <= 2023
        valid = years == 2024
        prep = fit_preprocessor(data, choice['bundle'], train)
        xtrain, xvalid = transform(data, prep, train), transform(data, prep, valid)
        coef, solver = fit_model(xtrain, labels[train], choice['penalty'])
        scores = (xvalid.reshape(-1, xvalid.shape[-1]) @ coef).reshape(-1, 6)
        y = labels[valid]
        def temp_loss(log_t):
            scaled = scores * np.exp(-log_t)
            return float(np.mean(logsumexp(scaled, axis=1) - scaled[np.arange(len(y)), y]))
        opt = minimize_scalar(temp_loss, bounds=(-4.0, 4.0), method='bounded',
                              options={'xatol': 1e-12})
        if not opt.success:
            raise RuntimeError('temperature optimizer failed')
        temperature = float(np.exp(opt.x))
        calibration[target_name] = {'temperature': temperature,
            'pre': metrics(scores, y), 'post': metrics(scores, y, temperature),
            'fitted_years': prep['fitted_years'], 'solver': solver}
        development_predictions[f'{target_name}_2024_pre'] = probabilities(scores).astype(np.float32)
        development_predictions[f'{target_name}_2024_post'] = probabilities(scores, temperature).astype(np.float32)
        print(json.dumps({'phase': 'calibration', 'target': target_name,
            'temperature': temperature, 'pre_log_loss': calibration[target_name]['pre']['log_loss'],
            'post_log_loss': calibration[target_name]['post']['log_loss']}), flush=True)
        final_train = years <= 2024
        final_prep = fit_preprocessor(data, choice['bundle'], final_train)
        final_x = transform(data, final_prep, final_train)
        final_coef, final_solver = fit_model(final_x, labels[final_train], choice['penalty'])
        final_scores = (final_x.reshape(-1, final_x.shape[-1]) @ final_coef).reshape(-1, 6)
        final_probs = probabilities(final_scores, temperature)
        if not np.isfinite(final_probs).all() or not np.allclose(final_probs.sum(axis=1), 1, atol=2e-7):
            raise RuntimeError('final fit probability coherence failed')
        # These are development predictions only, with no metrics computed here.
        development_predictions[f'{target_name}_final_2024'] = final_probs[valid].astype(np.float32)
        final_models[target_name] = {'bundle': choice['bundle'], 'penalty': choice['penalty'],
            'temperature': temperature, 'preprocessor': final_prep,
            'coefficients': final_coef.tolist(), 'solver': final_solver}
        print(json.dumps({'phase': 'final_fit', 'target': target_name,
            'features': len(final_coef), 'races': len(final_x)}), flush=True)
    model_artifact = {'version': 'P1_P2_BASELINE_V1', 'source_sha256': data['source_sha256'],
        'categorical_vocabulary': data['vocabulary'],
        'score': 'linear per boat; independently normalized six-boat softmax',
        'P1': final_models['P1'], 'P2': final_models['P2']}
    write_json(MODEL, model_artifact)
    np.savez(PREDICTIONS, race_ids=data['race_ids'][years == 2024],
             years=years[years == 2024],
             **development_predictions)
    freeze = {'verdict': 'P1_P2_BASELINE_V1_PREHOLDOUT_FROZEN',
        'source_table': 'core.prediction_dataset_v1', 'source_sha256': data['source_sha256'],
        'sql_sha256': hashlib.sha256(EXTRACT_SQL.encode()).hexdigest(),
        'code_sha256': sha(Path(__file__)),
        'scope': {'development_years': list(YEARS), 'selection_validation': [2022, 2023],
                  'calibration_year': 2024, 'holdout_2025': 'UNTOUCHED',
                  'year_2026': 'UNUSED', 'eligible_only': True},
        'method': {'model': 'separate six-boat linear softmax for P1 and exact P2',
                   'objective': 'mean race negative log likelihood + 0.5 * L2 * squared coefficient norm',
                   'penalties': list(PENALTIES), 'bundles': list(BUNDLES),
                   'selection': 'equal-weight mean of 2022 and 2023 annual log loss; 1e-5 tie band, then Brier with 1e-5 tie band, then simpler bundle',
                   'preprocessing': 'train-only numeric median, missing indicator, train-only mean/std with zero scale replaced by 1; train-only categorical levels and unseen all-zero; race-center transformed features',
                   'calibration': 'one positive scalar T per target, 2024 log loss minimum with log T in [-4,4]',
                   'final_fit': 'all eligible 2017-2024; selected bundle and L2; frozen T'},
        'selection_folds': selections, 'selected': selected, 'calibration_2024': calibration,
        'artifacts': {'model_path': str(MODEL.relative_to(ROOT)),
                      'model_sha256': sha(MODEL),
                      'development_predictions_path': str(PREDICTIONS.relative_to(ROOT)),
                      'development_predictions_sha256': sha(PREDICTIONS)}}
    write_json(FREEZE, freeze)
    print(json.dumps({'phase': 'freeze', 'verdict': freeze['verdict'],
        'freeze_sha256': sha(FREEZE), 'model_sha256': sha(MODEL),
        'predictions_sha256': sha(PREDICTIONS)}), flush=True)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, obj):
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, allow_nan=False) + '\n',
                    encoding='utf-8')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=('extract', 'develop'))
    args = parser.parse_args()
    if args.phase == 'extract':
        extract()
    else:
        develop()


if __name__ == '__main__':
    main()
