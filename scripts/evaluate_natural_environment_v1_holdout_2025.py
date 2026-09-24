"""One-shot 2025 evaluation of the frozen Natural Environment v1 method."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

import numpy as np

from scripts.db import target_connection
from scripts import natural_environment_model_v1 as natural
from scripts import p1_p2_baseline_v1 as baseline
from scripts import evaluate_p1_p2_baseline_v1_holdout_2025 as base_holdout
from scripts import evaluate_trifecta_probability_v1_2025 as trifecta
from scripts.build_natural_environment_v1_2025 import REPORT as FEATURE_REPORT


ROOT = Path(__file__).resolve().parents[1]
FREEZE = ROOT / 'artifacts/natural_environment_v1_freeze.json'
MODEL = ROOT / 'artifacts/natural_environment_v1_model.json'
GATE = ROOT / 'artifacts/natural_environment_v1_2025_holdout_gate.json'
PREDICTIONS = ROOT / 'artifacts/natural_environment_v1_2025_holdout_predictions.npz'
TRIFECTA = ROOT / 'artifacts/natural_environment_v1_2025_trifecta_probabilities.npz'
METRICS = ROOT / 'artifacts/natural_environment_v1_2025_holdout_metrics.json'
REPORT = ROOT / 'docs/natural_environment_v1_2025_holdout.md'
FREEZE_SHA256 = '78c24d7c97d07678684045ee3b4ef2a1b8f25871a8549cbfe959efd6a29eebf7'
HEAD = 'afbd8845722a972a3d20035a34e0648813ae32f5'
VERDICT = 'NATURAL_ENVIRONMENT_V1_2025_INDEPENDENT_HOLDOUT_COMPLETE'
EXPECTED_RACES = 51311
EXPECTED_ROWS = 307866
BASELINE_PREDICTIONS_SHA256 = 'b05869f2df22477c17851014f8a9b4aca7dfb006acdf433b5a6cc1df7bf7915a'
WIND_CATEGORIES = frozenset(('CALM', 'LEFT_CROSSWIND', 'HEADWIND',
                             'RIGHT_CROSSWIND', 'TAILWIND'))
OUTPUTS = (GATE, PREDICTIONS, TRIFECTA, METRICS, REPORT)


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def write_json_new(path: Path, value: dict) -> None:
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def write_npz_new(path: Path, arrays: dict) -> None:
    temporary = path.with_suffix(path.suffix + '.tmp')
    with temporary.open('xb') as stream:
        np.savez_compressed(stream, **arrays)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def preflight() -> tuple[dict, dict, dict, dict]:
    head = subprocess.check_output(
        ['git', '-c', f'safe.directory={ROOT.as_posix()}', 'rev-parse', 'HEAD'],
        cwd=ROOT, text=True).strip()
    if head != HEAD:
        raise RuntimeError(f'HEAD mismatch: {head}')
    if any(path.exists() for path in OUTPUTS):
        raise RuntimeError('holdout already started or completed; refusing rerun')
    if sha(FREEZE) != FREEZE_SHA256:
        raise RuntimeError('natural environment freeze hash mismatch')
    freeze = json.loads(FREEZE.read_text(encoding='utf-8'))
    for path, expected in (
        (MODEL, freeze['artifacts']['model_sha256']),
        (ROOT / freeze['artifacts']['development_predictions_path'],
         freeze['artifacts']['development_predictions_sha256']),
        (ROOT / freeze['baseline_freeze_path'], freeze['baseline_freeze_sha256']),
        (ROOT / freeze['source_lineage']['source_report_path'],
         freeze['source_lineage']['source_report_sha256']),
        (ROOT / freeze['diagnostics_2024']['trifecta_path'],
         freeze['diagnostics_2024']['trifecta_sha256']),
    ):
        if sha(path) != expected:
            raise RuntimeError(f'frozen artifact hash mismatch: {path.name}')
    for name, path in (
        ('builder', ROOT / 'scripts/build_natural_environment_v1.py'),
        ('tide', ROOT / 'scripts/natural_environment_tide_v1.py'),
        ('model', ROOT / 'scripts/natural_environment_model_v1.py'),
        ('sql_migration', ROOT / 'sql/migrations/0010_natural_environment_feature_v1.sql'),
    ):
        if sha(path) != freeze['code_sha256'][name]:
            raise RuntimeError(f'frozen code hash mismatch: {name}')
    if not FEATURE_REPORT.exists():
        raise RuntimeError('2025 environment feature report missing')
    feature_report = json.loads(FEATURE_REPORT.read_text(encoding='utf-8'))
    if (feature_report['freeze_sha256'] != FREEZE_SHA256
            or feature_report['counts']['races'] != 55908):
        raise RuntimeError('2025 environment feature report mismatch')
    if sha(base_holdout.PREDICTIONS) != BASELINE_PREDICTIONS_SHA256:
        raise RuntimeError('formal baseline prediction hash mismatch')
    if sha(base_holdout.MODEL) != base_holdout.MODEL_SHA256:
        raise RuntimeError('formal baseline model hash mismatch')
    base_metrics = json.loads(base_holdout.RESULT.read_text(encoding='utf-8'))
    tri_metrics = json.loads(trifecta.METRICS.read_text(encoding='utf-8'))
    if (base_metrics['eligible_races'] != EXPECTED_RACES
            or base_metrics['rows'] != EXPECTED_ROWS
            or tri_metrics['eligible_races'] != EXPECTED_RACES
            or tri_metrics['evaluable_races'] != EXPECTED_RACES
            or tri_metrics['method'] != trifecta.METHOD):
        raise RuntimeError('formal baseline comparator identity mismatch')
    expected_comparator = {
        'P1': dict(log_loss=1.199922972, brier=0.587272358,
                   ece_10bin=0.002652481, top1=0.569215178),
        'P2': dict(log_loss=1.672845340, brier=0.798877450,
                   ece_10bin=0.008953478, top1=0.278127497),
        'trifecta': dict(trifecta_log_loss=3.908322294,
            brier_120_class=0.964284042, actual_probability_mean=0.033668253,
            actual_probability_median=0.024841355, top1_hit_rate=0.090760,
            top3_hit_rate=0.225819, top5_hit_rate=0.323108,
            top10_hit_rate=0.484087),
    }
    for target, observed in (('P1', base_metrics['P1']['metrics']),
                             ('P2', base_metrics['P2']['metrics']),
                             ('trifecta', tri_metrics['metrics'])):
        for key, expected in expected_comparator[target].items():
            if abs(observed[key] - expected) > 5e-7:
                raise RuntimeError(f'formal {target} comparator mismatch: {key}')
    model = json.loads(MODEL.read_text(encoding='utf-8'))
    for target, temp in (('P1', 1.0149487987174035),
                         ('P2', 1.0068924602159712)):
        fixed = model[target]
        prep = fixed['preprocessor']
        if (freeze['selected'][target]['bundle'] != 'E2'
                or freeze['selected'][target]['penalty'] != 0.01
                or fixed['bundle'] != 'E2' or fixed['penalty'] != 0.01
                or fixed['temperature'] != temp
                or freeze['calibration_2024'][target]['temperature'] != temp
                or prep['bundle'] != 'E2' or prep['target'] != target
                or prep['baseline']['fitted_years'] != list(range(2017, 2025))
                or prep['environment']['fitted_years'] != list(range(2017, 2025))
                or len(fixed['coefficients']) != len(prep['baseline']['feature_order'])
                   + len(prep['environment']['feature_order'])):
            raise RuntimeError(f'unexpected frozen {target} method')
    conn = target_connection()
    try:
        conn.commit()
        conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
        with conn.cursor() as cur:
            cur.execute("""SELECT count(*),count(DISTINCT race_id)
                FROM core.prediction_dataset_v1 WHERE label_eligible = TRUE
                AND race_date >= DATE '2025-01-01' AND race_date < DATE '2026-01-01'""")
            if tuple(cur.fetchone()) != (EXPECTED_ROWS, EXPECTED_RACES):
                raise RuntimeError('2025 eligible cohort differs from formal baseline')
            cur.execute("""SELECT count(*) FROM core.natural_environment_feature_v1
                WHERE race_date >= DATE '2025-01-01' AND race_date < DATE '2026-01-01'""")
            if cur.fetchone()[0] != 55908:
                raise RuntimeError('2025 environment feature inventory mismatch')
    finally:
        conn.close()
    return model, freeze, base_metrics, tri_metrics


def environment_for_cohort(base_data: dict) -> tuple[dict, dict]:
    conn = target_connection()
    try:
        conn.commit()
        conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
        with conn.cursor() as cur:
            cur.execute("""SELECT f.race_id,f.race_date,f.wind_speed_m,
                f.air_temperature_c,f.tide_height,f.tide_change_speed,
                f.wind_category,f.weather,COALESCE(f.tide_direction,f.tide_status),
                f.tide_source_available,f.tide_status,f.c2_record_id_raw
                FROM core.natural_environment_feature_v1 f
                JOIN (SELECT DISTINCT race_id FROM core.prediction_dataset_v1
                      WHERE label_eligible = TRUE AND race_date >= DATE '2025-01-01'
                        AND race_date < DATE '2026-01-01') p USING(race_id)
                WHERE f.race_date >= DATE '2025-01-01'
                  AND f.race_date < DATE '2026-01-01'
                ORDER BY f.race_date,f.race_id""")
            rows = cur.fetchall()
    finally:
        conn.close()
    n = len(base_data['race_ids'])
    if len(rows) != EXPECTED_RACES or n != EXPECTED_RACES:
        raise RuntimeError('environment and baseline cohort count mismatch')
    ids = np.asarray([row[0] for row in rows], dtype=np.int64)
    dates = np.asarray([int(row[1].strftime('%Y%m%d')) for row in rows], dtype=np.int32)
    if (not np.array_equal(ids, base_data['race_ids'])
            or not np.array_equal(dates, base_data['race_dates'])):
        raise RuntimeError('environment race identity/order differs from formal baseline')
    numeric = np.asarray([[float(value) if value is not None else np.nan
                           for value in row[2:6]] for row in rows], dtype=np.float32)
    env = dict(race_ids=ids, years=np.full(n, 2025, dtype=np.int16),
        wind_speed=numeric[:, 0].astype(np.float64),
        air_temperature=numeric[:, 1].astype(np.float64),
        tide_height=numeric[:, 2].astype(np.float64),
        tide_change_speed=numeric[:, 3].astype(np.float64),
        wind_category=np.asarray([row[6] for row in rows], dtype='<U32'),
        weather=np.asarray([row[7] for row in rows], dtype='<U32'),
        tide_direction=np.asarray([row[8] for row in rows], dtype='<U32'),
        tide_source_available=np.asarray([row[9] for row in rows], dtype=bool),
        tide_status=np.asarray([row[10] for row in rows], dtype='<U32'))
    if (np.isinf(numeric).any() or any(np.any(env[key] == '') for key in
            ('wind_category', 'weather', 'tide_direction', 'tide_status'))):
        raise RuntimeError('invalid environment source value')
    coverage = dict(scope='2025 eligible races only', eligible_races=n,
        c2_available_races=sum(row[11] is not None for row in rows),
        wind_category_available_races=int(np.isin(env['wind_category'],
                                                  tuple(WIND_CATEGORIES)).sum()),
        air_temperature_available_races=int(np.isfinite(env['air_temperature']).sum()),
        tide_source_target_races=int(env['tide_source_available'].sum()),
        tide_valid_races=int((env['tide_status'] == 'AVAILABLE').sum()),
        tide_not_applicable_races=int((env['tide_status'] == 'NOT_APPLICABLE').sum()),
        tide_unresolved_races=int((env['tide_status'] == 'UNRESOLVED').sum()))
    if (coverage['tide_valid_races'] + coverage['tide_not_applicable_races']
            + coverage['tide_unresolved_races'] != n
            or coverage['tide_valid_races'] + coverage['tide_unresolved_races']
               != coverage['tide_source_target_races']):
        raise RuntimeError('tide coverage status inconsistency')
    return env, coverage


def evaluate_predictions(data: dict, env: dict, model: dict) -> tuple[dict, dict]:
    races = len(data['race_ids'])
    arrays = dict(race_id=data['race_ids'], race_date_yyyymmdd=data['race_dates'],
                  boat_no=np.broadcast_to(np.arange(1, 7, dtype=np.uint8),
                                          (races, 6)).copy(),
                  label_p1=data['label_p1'], label_p2=data['label_p2'])
    scores = {}
    for target, label in (('P1', 'label_p1'), ('P2', 'label_p2')):
        fixed = model[target]
        x = natural.transform(data, env, fixed['preprocessor'],
                              np.ones(races, dtype=bool))
        linear = (x.reshape(-1, x.shape[-1])
                  @ np.asarray(fixed['coefficients'], dtype=np.float64)).reshape(-1, 6)
        p = baseline.probabilities(linear, fixed['temperature'])
        violations = dict(nonfinite=int(np.count_nonzero(~np.isfinite(p))),
            out_of_range=int(np.count_nonzero((p < 0) | (p > 1))),
            race_sum=int(np.count_nonzero(np.abs(p.sum(axis=1) - 1) > 2e-7)))
        if any(violations.values()):
            raise RuntimeError(f'{target} probability violations: {violations}')
        winner = np.argmax(data[label], axis=1)
        scores[target] = dict(bundle=fixed['bundle'], l2=fixed['penalty'],
            temperature=fixed['temperature'],
            metrics=baseline.metrics(linear, winner, fixed['temperature']),
            validation=violations)
        arrays['pred_' + target.lower()] = p
    return scores, arrays


def metric_deltas(current: dict, comparator: dict) -> dict:
    return {key: current[key] - comparator[key] for key in current
            if key in comparator and isinstance(current[key], (int, float))
            and key != 'races'}


def report_text(result: dict) -> str:
    def value(number):
        return f'{number:.9f}'
    lines = [
        '# Natural Environment v1 — 2025 Independent Holdout', '',
        '## A. Verdict', '', f"`{VERDICT}`。正常な一回評価の完了を示し、性能のPASS/FAILではない。", '',
        '## B. Holdout identity', '',
        f"2025-01-01～2025-12-31、`core.prediction_dataset_v1` の `label_eligible = TRUE`。{EXPECTED_RACES:,} race / {EXPECTED_ROWS:,} rows、各race 6艇。Baseline正式artifactとrace ID・日付・P1/P2 labelが完全一致。", '',
        '## C. Natural Environment frozen method', '',
        f"freeze SHA-256 `{FREEZE_SHA256}`。P1/P2ともE2、L2=0.01。P1 temperature={result['P1']['temperature']:.16f}、P2 temperature={result['P2']['temperature']:.16f}。Baseline + Entry Course probability × C2 Environment + Tide。波は使用しない。", '',
        '## D/E. 2025 P1/P2 metrics and Baseline difference', '',
        '差はNatural Environment − Baseline。Log Loss、Brier、ECEは負が改善。', '',
        '| Target | Metric | Natural | Baseline | 差 |', '| --- | --- | ---: | ---: | ---: |',
    ]
    for target in ('P1', 'P2'):
        for key, label in (('log_loss', 'Log Loss'), ('brier', 'Brier'),
                           ('ece_10bin', 'ECE 10-bin'), ('top1', 'Top1')):
            lines.append(f"| {target} | {label} | {value(result[target]['metrics'][key])} | "
                f"{value(result['baseline'][target][key])} | {result['delta'][target][key]:+.9f} |")
    lines += ['', '## F/G. 2025 trifecta metrics and Baseline difference', '',
              '差はNatural Environment − Baseline。', '',
              '| Metric | Natural | Baseline | 差 |', '| --- | ---: | ---: | ---: |']
    for key, label in (('trifecta_log_loss', 'Trifecta Log Loss'),
                       ('brier_120_class', '120-class Brier'),
                       ('actual_probability_mean', 'Actual probability mean'),
                       ('actual_probability_median', 'Actual probability median'),
                       ('top1_hit_rate', 'Top1'), ('top3_hit_rate', 'Top3'),
                       ('top5_hit_rate', 'Top5'), ('top10_hit_rate', 'Top10')):
        lines.append(f"| {label} | {value(result['trifecta']['metrics'][key])} | "
            f"{value(result['baseline']['trifecta'][key])} | "
            f"{result['delta']['trifecta'][key]:+.9f} |")
    c = result['coverage']
    lines += ['', '## H. Coverage', '', '対象は51,311 eligible race。', '',
        '| Item | Race |', '| --- | ---: |',
        f"| C2 available | {c['c2_available_races']:,} |",
        f"| Wind category available | {c['wind_category_available_races']:,} |",
        f"| Air temperature available | {c['air_temperature_available_races']:,} |",
        f"| Tide source target | {c['tide_source_target_races']:,} |",
        f"| Tide valid | {c['tide_valid_races']:,} |",
        f"| Tide NOT_APPLICABLE | {c['tide_not_applicable_races']:,} |",
        f"| Tide UNRESOLVED | {c['tide_unresolved_races']:,} |", '',
        '## I. Validation / leakage', '',
        f"各race 6艇、P1/P2 finite・範囲内・sum=1、3連単120通り/race・sum=1、全{EXPECTED_RACES:,} race evaluable。凍結済みpreprocessorと係数をtransformのみで適用し、この評価でfitなし。3着結果はK3 lineageを検証した評価用labelで、予測featureには使用していない。新規コードにR3参照はない。C2/L2のhistorical exact publication timestampは未検証であり、厳密な時点再現は主張しない。", '',
        '## J. Artifact hashes', '',
        f"- 2025 feature report: `{result['artifacts']['feature_report_sha256']}`",
        f"- P1/P2 predictions: `{result['artifacts']['predictions_sha256']}`",
        f"- Trifecta probabilities: `{result['artifacts']['trifecta_sha256']}`",
        f"- Metrics JSON: `{sha(METRICS)}`", '',
        '## K. Git', '', '通常commitとpushの実績は最終報告で示す。', '',
    ]
    return '\n'.join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--preflight', action='store_true')
    args = parser.parse_args()
    model, _freeze, base_metrics, tri_metrics = preflight()
    if args.preflight:
        print(json.dumps(dict(status='READY', head=HEAD,
            freeze_sha256=FREEZE_SHA256, eligible_races=EXPECTED_RACES,
            rows=EXPECTED_ROWS, feature_report_sha256=sha(FEATURE_REPORT)),
            sort_keys=True))
        return
    write_json_new(GATE, dict(status='STARTED', head=HEAD,
                             freeze_sha256=FREEZE_SHA256))
    data = base_holdout.extract(json.loads(base_holdout.MODEL.read_text(encoding='utf-8')))
    if len(data['race_ids']) != EXPECTED_RACES or len(data['numeric']) != EXPECTED_ROWS:
        raise RuntimeError('2025 extract count mismatch')
    with np.load(base_holdout.PREDICTIONS, allow_pickle=False) as reference:
        for left, right in (('race_ids', 'race_id'), ('race_dates', 'race_date_yyyymmdd'),
                            ('label_p1', 'label_p1'), ('label_p2', 'label_p2')):
            if not np.array_equal(data[left], reference[right]):
                raise RuntimeError(f'formal baseline cohort/labels mismatch: {left}')
    env, coverage = environment_for_cohort(data)
    environment_input_sha256 = natural._array_digest(env, natural.ENV_FIELDS)
    target_scores, arrays = evaluate_predictions(data, env, model)
    third = trifecta.third_boats_from_k3(arrays)
    tri_scores, p120, valid = trifecta.evaluate(arrays, third)
    if not valid.all():
        raise RuntimeError(f'trifecta not evaluable for {int((~valid).sum())} races')
    actual = trifecta.actual_indices(arrays, third)
    tri_arrays = trifecta.output_arrays(arrays, p120, valid, actual)
    if (len(tri_arrays['race_id']) != EXPECTED_RACES * 120
            or int(tri_arrays['is_actual'].sum()) != EXPECTED_RACES):
        raise RuntimeError('trifecta output shape mismatch')
    write_npz_new(PREDICTIONS, arrays)
    write_npz_new(TRIFECTA, tri_arrays)
    result = dict(verdict=VERDICT, head_at_start=HEAD,
        period='2025-01-01 through 2025-12-31',
        filter="label_eligible = TRUE AND race_date >= DATE '2025-01-01' AND race_date < DATE '2026-01-01'",
        eligible_races=EXPECTED_RACES, rows=EXPECTED_ROWS, boats_per_race=6,
        freeze_sha256=FREEZE_SHA256, model_sha256=sha(MODEL),
        environment_input_sha256=environment_input_sha256,
        method=dict(P1='E2 L2=0.01', P2='E2 L2=0.01',
                    trifecta=trifecta.METHOD, fit_during_holdout=False),
        P1=target_scores['P1'], P2=target_scores['P2'],
        trifecta=dict(metrics=tri_scores, evaluable_races=int(valid.sum()),
                      probabilities_per_race=120, rows=len(tri_arrays['race_id']),
                      probability_sum_violations=0), coverage=coverage,
        baseline=dict(P1=base_metrics['P1']['metrics'],
                      P2=base_metrics['P2']['metrics'],
                      trifecta=tri_metrics['metrics']),
        delta=dict(P1=metric_deltas(target_scores['P1']['metrics'],
                                    base_metrics['P1']['metrics']),
                   P2=metric_deltas(target_scores['P2']['metrics'],
                                    base_metrics['P2']['metrics']),
                   trifecta=metric_deltas(tri_scores, tri_metrics['metrics'])),
        artifacts=dict(feature_report=str(FEATURE_REPORT.relative_to(ROOT)),
                       feature_report_sha256=sha(FEATURE_REPORT),
                       predictions=str(PREDICTIONS.relative_to(ROOT)),
                       predictions_sha256=sha(PREDICTIONS),
                       trifecta=str(TRIFECTA.relative_to(ROOT)),
                       trifecta_sha256=sha(TRIFECTA)))
    write_json_new(METRICS, result)
    with REPORT.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(report_text(result))
        stream.flush()
        os.fsync(stream.fileno())
    write_json_new(GATE.with_suffix('.json.complete.tmp'), dict(
        status='COMPLETED', verdict=VERDICT, freeze_sha256=FREEZE_SHA256,
        feature_report_sha256=sha(FEATURE_REPORT),
        predictions_sha256=sha(PREDICTIONS), trifecta_sha256=sha(TRIFECTA),
        metrics_sha256=sha(METRICS), report_sha256=sha(REPORT)))
    os.replace(GATE.with_suffix('.json.complete.tmp'), GATE)
    print(json.dumps(result, sort_keys=True, allow_nan=False), flush=True)


if __name__ == '__main__':
    main()
