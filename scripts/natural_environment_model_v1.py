"""Pre-holdout Natural Environment Feature v1 model development.

This module consumes the pre-2025 baseline and environment caches.  It never
queries a result table.  E0 is the already-frozen baseline; E1/E2 add only
entry-course-probability by race-environment interactions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.optimize import minimize_scalar
from scipy.special import logsumexp

from scripts import p1_p2_baseline_v1 as baseline


ROOT = Path(__file__).resolve().parents[1]
ENV_CACHE = ROOT / '.local/natural_environment_v1_development.npz'
BASELINE_FREEZE = ROOT / 'artifacts/p1_p2_baseline_v1_freeze.json'
BASELINE_MODEL = ROOT / 'artifacts/p1_p2_baseline_v1_model.json'
BASELINE_PREDICTIONS = ROOT / 'artifacts/p1_p2_baseline_v1_development_predictions.npz'
FREEZE = ROOT / 'artifacts/natural_environment_v1_freeze.json'
MODEL = ROOT / 'artifacts/natural_environment_v1_model.json'
PREDICTIONS = ROOT / 'artifacts/natural_environment_v1_development_predictions.npz'
SOURCE_REPORT = ROOT / 'artifacts/natural_environment_v1_source_report.json'
BUILD_CODE = ROOT / 'scripts/build_natural_environment_v1.py'
TIDE_CODE = ROOT / 'scripts/natural_environment_tide_v1.py'
MIGRATION = ROOT / 'sql/migrations/0010_natural_environment_feature_v1.sql'

BUNDLES = ('E0', 'E1', 'E2')
PENALTIES = (0.01, 0.1, 1.0, 10.0, 100.0)
BASELINE_BUNDLES = {'P1': 'CORE_MOTOR', 'P2': 'FULL'}
COURSE_NAMES = tuple(f'entry_course_prob_{i}' for i in range(1, 7))
ENV_NUMERIC = {
    'E1': ('wind_speed', 'air_temperature'),
    'E2': ('wind_speed', 'air_temperature', 'tide_height', 'tide_change_speed'),
}
ENV_CATEGORICAL = {
    'E1': ('wind_category', 'weather'),
    'E2': ('wind_category', 'weather', 'tide_direction'),
}
PHYSICAL_TIDE_DIRECTIONS = frozenset(
    ('RISING', 'FALLING', 'HIGH_TIDE', 'LOW_TIDE'))
ENV_FIELDS = (
    'race_ids', 'years', 'wind_speed', 'air_temperature', 'tide_height',
    'tide_change_speed', 'wind_category', 'weather', 'tide_direction',
    'tide_source_available', 'tide_status',
)


def _array_digest(data, keys):
    digest = hashlib.sha256()
    for key in keys:
        value = np.ascontiguousarray(data[key])
        digest.update(key.encode('utf-8'))
        digest.update(value.dtype.str.encode('ascii'))
        digest.update(np.asarray(value.shape, dtype=np.int64).tobytes())
        digest.update(value.tobytes())
    return digest.hexdigest()


def load_environment_cache(base_data, path=ENV_CACHE):
    """Load and strictly align the race-grain environment cache to baseline."""
    with np.load(path, allow_pickle=False) as z:
        missing = [key for key in ENV_FIELDS if key not in z.files]
        if missing:
            raise RuntimeError(f'environment cache fields missing: {missing}')
        env = {key: z[key] for key in ENV_FIELDS}
        expected_hash = str(z['source_sha256']) if 'source_sha256' in z.files else None
        expected_baseline = str(z['baseline_source_sha256']) if 'baseline_source_sha256' in z.files else None
    raw_hash = _array_digest(env, ENV_FIELDS)
    if expected_hash is not None and raw_hash != expected_hash:
        raise RuntimeError('environment cache source hash mismatch')
    if expected_baseline is not None and expected_baseline != base_data['source_sha256']:
        raise RuntimeError('environment cache baseline source hash mismatch')
    n = len(base_data['race_ids'])
    if any(np.asarray(env[key]).ndim != 1 or len(env[key]) != n for key in ENV_FIELDS):
        raise RuntimeError('environment cache must contain one value per baseline race')
    if not np.array_equal(env['race_ids'], base_data['race_ids']):
        raise RuntimeError('environment race_ids are not exactly baseline-aligned')
    if not np.array_equal(env['years'], base_data['years']):
        raise RuntimeError('environment years are not exactly baseline-aligned')
    for key in ('wind_speed', 'air_temperature', 'tide_height', 'tide_change_speed'):
        values = np.asarray(env[key], dtype=np.float64)
        if np.isinf(values).any():
            raise RuntimeError(f'infinite environment numeric: {key}')
        env[key] = values
    for key in ('wind_category', 'weather', 'tide_direction', 'tide_status'):
        env[key] = np.asarray(env[key]).astype(str)
        if np.any(env[key] == ''):
            raise RuntimeError(f'empty environment category: {key}')
    env['tide_source_available'] = np.asarray(env['tide_source_available'], dtype=bool)
    env['source_sha256'] = raw_hash
    return env


def _race_rows(races):
    return baseline.race_rows(np.asarray(races, dtype=bool))


def _course_raw(base_data, races):
    indices = [baseline.NUMERIC.index(name) for name in COURSE_NAMES]
    return base_data['numeric'][_race_rows(races)][:, indices].astype(np.float64)


def fit_environment_preprocessor(base_data, env, bundle, train_races):
    """Fit every environment preprocessing value from training races only."""
    if bundle not in ('E1', 'E2'):
        raise ValueError(f'no environment preprocessor for {bundle}')
    train_races = np.asarray(train_races, dtype=bool)
    course = _course_raw(base_data, train_races)
    course_medians = np.nanmedian(course, axis=0)
    course_medians = np.where(np.isnan(course_medians), 0.0, course_medians)
    course = np.where(np.isnan(course), course_medians, course)

    raw_numeric = []
    numeric_names = []
    race_index = np.repeat(np.flatnonzero(train_races), 6)
    for env_name in ENV_NUMERIC[bundle]:
        values = env[env_name][race_index]
        for course_index in range(6):
            raw_numeric.append(course[:, course_index] * values)
            numeric_names.append(f'{COURSE_NAMES[course_index]}*{env_name}')
    raw_numeric = np.column_stack(raw_numeric)
    medians = np.nanmedian(raw_numeric, axis=0)
    medians = np.where(np.isnan(medians), 0.0, medians)
    filled = np.where(np.isnan(raw_numeric), medians, raw_numeric)
    means = filled.mean(axis=0, dtype=np.float64)
    scales = filled.std(axis=0, dtype=np.float64)
    scales = np.where(scales > 1e-12, scales, 1.0)

    levels = {}
    for name in ENV_CATEGORICAL[bundle]:
        observed = (str(x) for x in np.unique(env[name][train_races]))
        levels[name] = sorted(x for x in observed
                              if name != 'tide_direction'
                              or x in PHYSICAL_TIDE_DIRECTIONS)
    feature_order = ([f'{name}:z' for name in numeric_names]
                     + [f'{name}:missing' for name in numeric_names])
    for env_name in ENV_CATEGORICAL[bundle]:
        for level in levels[env_name]:
            feature_order.extend(
                f'{course_name}*I({env_name}={level})' for course_name in COURSE_NAMES
            )
    return {
        'bundle': bundle,
        'course_medians': course_medians.tolist(),
        'numeric_names': numeric_names,
        'medians': medians.tolist(),
        'means': means.tolist(),
        'scales': scales.tolist(),
        'levels': levels,
        'feature_order': feature_order,
        'fitted_years': sorted(int(x) for x in np.unique(base_data['years'][train_races])),
    }


def transform_environment(base_data, env, prep, races):
    """Build and race-center course-probability by environment interactions."""
    races = np.asarray(races, dtype=bool)
    course = _course_raw(base_data, races)
    course = np.where(np.isnan(course), prep['course_medians'], course)
    race_index = np.repeat(np.flatnonzero(races), 6)
    raw_numeric = []
    for env_name in ENV_NUMERIC[prep['bundle']]:
        values = env[env_name][race_index]
        raw_numeric.extend(course[:, i] * values for i in range(6))
    raw_numeric = np.column_stack(raw_numeric)
    missing = np.isnan(raw_numeric)
    filled = np.where(missing, prep['medians'], raw_numeric)
    n_numeric = len(prep['numeric_names'])
    x = np.empty((len(course), len(prep['feature_order'])), dtype=np.float32)
    x[:, :n_numeric] = (filled - prep['means']) / prep['scales']
    x[:, n_numeric:2 * n_numeric] = missing
    offset = 2 * n_numeric
    for env_name in ENV_CATEGORICAL[prep['bundle']]:
        values = env[env_name][race_index]
        for level in prep['levels'][env_name]:
            indicator = values == level
            x[:, offset:offset + 6] = course * indicator[:, None]
            offset += 6
    if offset != x.shape[1] or not np.isfinite(x).all():
        raise RuntimeError('invalid environment interaction matrix')
    x = x.reshape(-1, 6, x.shape[1])
    x -= x.mean(axis=1, keepdims=True)
    return np.ascontiguousarray(x)


def fit_preprocessor(base_data, env, target, bundle, train_races):
    base_bundle = BASELINE_BUNDLES[target]
    result = {'target': target, 'bundle': bundle,
              'baseline': baseline.fit_preprocessor(base_data, base_bundle, train_races)}
    if bundle != 'E0':
        result['environment'] = fit_environment_preprocessor(
            base_data, env, bundle, train_races)
    return result


def transform(base_data, env, prep, races):
    base_x = baseline.transform(base_data, prep['baseline'], races)
    if prep['bundle'] == 'E0':
        return base_x
    env_x = transform_environment(base_data, env, prep['environment'], races)
    return np.ascontiguousarray(np.concatenate((base_x, env_x), axis=2))


def select(candidates):
    """Select by annual-mean Log Loss, Brier, then simpler environment bundle."""
    best_log = min(x['mean_log_loss'] for x in candidates)
    tied = [x for x in candidates if x['mean_log_loss'] <= best_log + 1e-5]
    best_brier = min(x['mean_brier'] for x in tied)
    tied = [x for x in tied if x['mean_brier'] <= best_brier + 1e-5]
    return min(tied, key=lambda x: (BUNDLES.index(x['bundle']), x['penalty']))


def _read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_baseline_artifacts(base_data):
    freeze = _read_json(BASELINE_FREEZE)
    model = _read_json(BASELINE_MODEL)
    if freeze.get('verdict') != 'P1_P2_BASELINE_V1_PREHOLDOUT_FROZEN':
        raise RuntimeError('baseline freeze verdict mismatch')
    if freeze.get('source_sha256') != base_data['source_sha256']:
        raise RuntimeError('baseline cache/freeze source mismatch')
    for key, path in (('model_sha256', BASELINE_MODEL),
                      ('development_predictions_sha256', BASELINE_PREDICTIONS)):
        if freeze['artifacts'][key] != _sha(path):
            raise RuntimeError(f'baseline artifact hash mismatch: {key}')
    return freeze, model


def _e0_folds(freeze, target):
    selected = freeze['selected'][target]
    if selected['bundle'] != BASELINE_BUNDLES[target]:
        raise RuntimeError(f'unexpected frozen {target} baseline bundle')
    items = [x for x in freeze['selection_folds'][target]
             if x['year'] in (2022, 2023)
             and x['bundle'] == selected['bundle']
             and x['penalty'] == selected['penalty']]
    if sorted(x['year'] for x in items) != [2022, 2023]:
        raise RuntimeError(f'incomplete frozen E0 folds for {target}')
    return [{**x, 'bundle': 'E0', 'source_bundle': x['bundle']} for x in items]


def _scores(x, coefficients):
    return (x.reshape(-1, x.shape[-1]) @ coefficients).reshape(-1, 6)


def _fit_temperature(scores, labels):
    def loss(log_t):
        scaled = scores * np.exp(-log_t)
        return float(np.mean(logsumexp(scaled, axis=1)
                             - scaled[np.arange(len(labels)), labels]))
    result = minimize_scalar(loss, bounds=(-4.0, 4.0), method='bounded',
                             options={'xatol': 1e-12})
    if not result.success:
        raise RuntimeError('temperature optimizer failed')
    return float(np.exp(result.x))


def _write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n',
                    encoding='utf-8')


def develop():
    base_data = baseline.load_cache()
    env = load_environment_cache(base_data)
    baseline_freeze, baseline_model = _load_baseline_artifacts(base_data)
    source_report = _read_json(SOURCE_REPORT)
    from scripts.natural_environment_tide_v1 import VENUE_TO_CHITEN_CODE
    if (source_report['version'] != 'NATURAL_ENVIRONMENT_FEATURE_V1'
            or source_report['tide_mapping'] != VENUE_TO_CHITEN_CODE
            or source_report['counts']['races'] < len(base_data['race_ids'])):
        raise RuntimeError('natural environment source report mismatch')
    years = base_data['years']
    if set(np.unique(years)) != set(range(2017, 2025)):
        raise RuntimeError('development years must be exactly 2017-2024')

    selections = {'P1': _e0_folds(baseline_freeze, 'P1'),
                  'P2': _e0_folds(baseline_freeze, 'P2')}
    for validation_year in (2022, 2023):
        train, valid = years < validation_year, years == validation_year
        for bundle in ('E1', 'E2'):
            for target, labels in (('P1', base_data['winners']), ('P2', base_data['seconds'])):
                prep = fit_preprocessor(base_data, env, target, bundle, train)
                if max(prep['environment']['fitted_years']) >= validation_year:
                    raise RuntimeError('environment preprocessor saw validation year')
                xtrain = transform(base_data, env, prep, train)
                xvalid = transform(base_data, env, prep, valid)
                previous = None
                for penalty in reversed(PENALTIES):
                    coef, solver = baseline.fit_model(xtrain, labels[train], penalty, previous)
                    previous = coef
                    result = baseline.metrics(_scores(xvalid, coef), labels[valid])
                    selections[target].append({
                        'year': validation_year, 'bundle': bundle, 'penalty': penalty,
                        'metrics': result, 'solver': solver,
                        'fitted_years': prep['environment']['fitted_years'],
                    })
                    print(json.dumps({'phase': 'selection', 'target': target,
                        'year': validation_year, 'bundle': bundle, 'penalty': penalty,
                        'log_loss': result['log_loss']}), flush=True)

    selected = {}
    for target, items in selections.items():
        candidates = []
        for bundle in BUNDLES:
            penalties = [baseline_freeze['selected'][target]['penalty']] if bundle == 'E0' else PENALTIES
            for penalty in penalties:
                pair = [x for x in items if x['bundle'] == bundle and x['penalty'] == penalty]
                if len(pair) != 2:
                    raise RuntimeError(f'incomplete selection pair: {target}/{bundle}/{penalty}')
                candidates.append({'bundle': bundle, 'penalty': penalty,
                    'mean_log_loss': float(np.mean([x['metrics']['log_loss'] for x in pair])),
                    'mean_brier': float(np.mean([x['metrics']['brier'] for x in pair]))})
        selected[target] = select(candidates)

    calibration = {}
    final_models = {}
    predictions = {}
    with np.load(BASELINE_PREDICTIONS, allow_pickle=False) as z:
        baseline_predictions = {key: z[key] for key in z.files}
    for target, labels in (('P1', base_data['winners']), ('P2', base_data['seconds'])):
        choice = selected[target]
        if choice['bundle'] == 'E0':
            calibration[target] = baseline_freeze['calibration_2024'][target]
            final_models[target] = {'bundle': 'E0', 'source_bundle': BASELINE_BUNDLES[target],
                                    'baseline_model': baseline_model[target]}
            for suffix in ('2024_pre', '2024_post', 'final_2024'):
                predictions[f'{target}_{suffix}'] = baseline_predictions[f'{target}_{suffix}']
            continue
        train, valid = years <= 2023, years == 2024
        prep = fit_preprocessor(base_data, env, target, choice['bundle'], train)
        xtrain, xvalid = transform(base_data, env, prep, train), transform(base_data, env, prep, valid)
        coef, solver = baseline.fit_model(xtrain, labels[train], choice['penalty'])
        scores = _scores(xvalid, coef)
        temperature = _fit_temperature(scores, labels[valid])
        calibration[target] = {'temperature': temperature,
            'pre': baseline.metrics(scores, labels[valid]),
            'post': baseline.metrics(scores, labels[valid], temperature),
            'fitted_years': prep['environment']['fitted_years'], 'solver': solver}
        predictions[f'{target}_2024_pre'] = baseline.probabilities(scores).astype(np.float32)
        predictions[f'{target}_2024_post'] = baseline.probabilities(scores, temperature).astype(np.float32)

        final = years <= 2024
        final_prep = fit_preprocessor(base_data, env, target, choice['bundle'], final)
        final_x = transform(base_data, env, final_prep, final)
        final_coef, final_solver = baseline.fit_model(final_x, labels[final], choice['penalty'])
        final_prob = baseline.probabilities(_scores(final_x, final_coef), temperature)
        if not np.allclose(final_prob.sum(axis=1), 1.0, atol=2e-7):
            raise RuntimeError('final probability coherence failed')
        predictions[f'{target}_final_2024'] = final_prob[valid].astype(np.float32)
        final_models[target] = {'bundle': choice['bundle'], 'penalty': choice['penalty'],
            'temperature': temperature, 'preprocessor': final_prep,
            'coefficients': final_coef.tolist(), 'solver': final_solver}

    model_artifact = {'version': 'NATURAL_ENVIRONMENT_V1',
        'baseline_source_sha256': base_data['source_sha256'],
        'environment_source_sha256': env['source_sha256'],
        'interaction': 'entry_course_prob_1_to_6 by environment only',
        'P1': final_models['P1'], 'P2': final_models['P2']}
    _write_json(MODEL, model_artifact)
    np.savez(PREDICTIONS, race_ids=base_data['race_ids'][years == 2024],
             years=years[years == 2024], **predictions)
    freeze = {'verdict': 'NATURAL_ENVIRONMENT_V1_PREHOLDOUT_FROZEN',
        'baseline_freeze_path': str(BASELINE_FREEZE.relative_to(ROOT)),
        'baseline_freeze_sha256': _sha(BASELINE_FREEZE),
        'baseline_source_sha256': base_data['source_sha256'],
        'environment_source_sha256': env['source_sha256'],
        'source_lineage': {'feature_interface': 'core.natural_environment_feature_v1',
            'c2': 'pckyotei.public.brd_c2', 'deadline': 'pckyotei.public.brd_l2',
            'tide': 'pckyotei.public.apd_choihyo',
            'source_report_path': str(SOURCE_REPORT.relative_to(ROOT)),
            'source_report_sha256': _sha(SOURCE_REPORT),
            'c2_l2_source_sha256': source_report['source_sha256'],
            'tide_source_sha256': source_report['tide_source_sha256']},
        'scope': {'development_years': list(range(2017, 2025)),
                  'selection_validation': [2022, 2023], 'calibration_year': 2024,
                  'holdout_2025': 'UNTOUCHED', 'year_2026': 'UNUSED'},
        'method': {'model': 'separate six-boat linear softmax for P1 and exact P2',
            'baseline_bundles': BASELINE_BUNDLES, 'bundles': list(BUNDLES),
            'penalties': list(PENALTIES),
            'selection': 'equal-weight annual mean Log Loss; 1e-5 tie then Brier 1e-5 tie then E0/E1/E2 simplicity',
            'environment_main_effects': 'excluded',
            'tide_status': 'NOT_APPLICABLE and UNRESOLVED are retained for applicability and missingness only; only physical tide directions have interaction coefficients',
            'interaction_preprocessing': 'raw entry-course probability times raw numeric environment, then training-only median imputation, missing indicator, mean/std; categorical training-only level indicator times training-median-imputed entry-course probability; unseen levels all zero; race-center',
            'interactions': {'E1': {'numeric': list(ENV_NUMERIC['E1']), 'categorical': list(ENV_CATEGORICAL['E1'])},
                             'E2': {'numeric': list(ENV_NUMERIC['E2']), 'categorical': list(ENV_CATEGORICAL['E2'])}},
            'wind': {'relative_d': '(fuko_code - hogaku_code) mod 16',
                'calm': 'fusoku 00 has priority regardless of fuko_code',
                'categories': {'15,0,1': 'LEFT_CROSSWIND', '2-6': 'HEADWIND',
                    '7-9': 'RIGHT_CROSSWIND', '10-14': 'TAILWIND'},
                'speed_source': 'brd_c2.fusoku', 'speed_unit_user_specified': 'm',
                'wave': 'excluded'},
            'tide': {'venue_to_chiten_code': VENUE_TO_CHITEN_CODE,
                'height': 'linear interpolation of adjacent low/high extrema at brd_l2 scheduled deadline',
                'direction': 'LOW->HIGH RISING; HIGH->LOW FALLING; exact HIGH_TIDE/LOW_TIDE',
                'change_speed': 'absolute endpoint height difference / elapsed hours; exact extremum 0; source choi unit per hour',
                'invalid': 'UNRESOLVED with numeric NULL; non-tide venue NOT_APPLICABLE',
                'preholdout_boundary': 'no 2025 tide source rows read'},
            'calibration': '2024 positive scalar temperature per target',
            'final_fit': 'eligible 2017-2024 only'},
        'selection_folds': selections, 'selected': selected,
        'calibration_2024': calibration,
        'artifacts': {'model_path': str(MODEL.relative_to(ROOT)), 'model_sha256': _sha(MODEL),
                      'development_predictions_path': str(PREDICTIONS.relative_to(ROOT)),
                      'development_predictions_sha256': _sha(PREDICTIONS)},
        'code_sha256': {'model': _sha(Path(__file__)), 'builder': _sha(BUILD_CODE),
                        'tide': _sha(TIDE_CODE), 'sql_migration': _sha(MIGRATION)}}
    _write_json(FREEZE, freeze)
    print(json.dumps({'phase': 'freeze', 'verdict': freeze['verdict'],
                      'freeze_sha256': _sha(FREEZE)}), flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=('develop',))
    parser.parse_args()
    develop()


if __name__ == '__main__':
    main()
