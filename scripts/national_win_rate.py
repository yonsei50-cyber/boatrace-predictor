"""Phase 3A additive upgrade and independent audit of adopted L3 national rates.

No source DB reads/writes, result joins, KI fallback, or prediction calculations.
"""
import argparse
import json
from pathlib import Path
from scripts.db import target_connection

MIGRATION = Path(__file__).resolve().parents[1] / 'sql/migrations/0003_l3_national_win_rate.sql'


def protected_state(cur):
    cur.execute('SELECT dataset_version_id,canonical_content_hash,manifest_hash,effective_date,'
                'results_cutoff_date FROM core.dataset_version ORDER BY dataset_version_id')
    datasets = cur.fetchall()
    cur.execute('SELECT count(*),sum(row_count),max(source_batch_id) FROM raw.source_batch')
    return {'datasets': datasets, 'raw_batches': cur.fetchone()}


def upgrade(cur, progress=False):
    cur.execute(MIGRATION.read_text(encoding='utf-8'))
    # Avoid a wide Raw JOIN for already populated installations. The independent
    # full audit still checks every existing non-NULL value and blocks divergence.
    cur.execute('''SELECT EXISTS (SELECT 1 FROM core.race_entry e
        JOIN core.race r USING(race_id) WHERE r.race_date >= DATE '2017-01-01'
        AND e.national_win_rate_raw IS NULL)''')
    if not cur.fetchone()[0]:
        if progress:
            print(json.dumps({'updated': 0}), flush=True)
        return 0
    cur.execute('''UPDATE core.race_entry e SET national_win_rate_raw=s.raw_payload->>'zenkoku_ritsu_1'
        FROM core.race r,raw.source_record s
        WHERE e.race_id=r.race_id AND e.source_record_id=s.source_record_id
          AND r.race_date >= DATE '2017-01-01'
          AND e.national_win_rate_raw IS DISTINCT FROM s.raw_payload->>'zenkoku_ritsu_1' ''')
    changed = cur.rowcount
    if progress:
        print(json.dumps({'updated': changed}), flush=True)
    return changed


def rows(cur, query):
    cur.execute(query)
    return [dict(zip([d.name for d in cur.description], row)) for row in cur.fetchall()]


def raw_coverage(cur):
    """Compare all stored 2017+ L3 observations, including repeated sample batches.

    Identical observations across batches are not duplicate Canonical entries.
    Distinct conflicting registration/rate observations are blocking.
    """
    cur.execute('''CREATE TEMP TABLE national_rate_raw ON COMMIT DROP AS
        SELECT p.kaisai_nen || p.kaisai_tsukihi AS day,
          p.kyoteijo_code AS venue,p.race_no AS race,p.teiban AS boat,
          p.toroku_bango AS player,p.zenkoku_ritsu_1 AS raw
        FROM raw.source_record s JOIN raw.source_batch b USING(source_batch_id)
        CROSS JOIN LATERAL jsonb_to_record(s.raw_payload) AS p(kaisai_nen text,
          kaisai_tsukihi text,kyoteijo_code text,race_no text,teiban text,
          toroku_bango text,zenkoku_ritsu_1 text)
        WHERE b.source_table='brd_l3' AND p.kaisai_nen>='2017' ''')
    result = rows(cur, '''SELECT count(*) AS raw_observations,
        count(DISTINCT (day,venue,race,boat)) AS distinct_entry_keys,
        count(DISTINCT (day,venue,race,boat,player,raw)) AS distinct_input_observations
        FROM national_rate_raw''')[0]
    canonical = '''SELECT to_char(race_date,'YYYYMMDD'),lpad(venue_code::text,2,'0'),
        lpad(race_no::text,2,'0'),boat_no::text,lpad(player_id::text,4,'0'),raw FROM national_rate_audit'''
    for label, query in (
        ('raw_without_matching_canonical', 'SELECT * FROM national_rate_raw EXCEPT '+canonical),
        ('canonical_without_matching_raw', canonical+' EXCEPT SELECT * FROM national_rate_raw')):
        cur.execute('SELECT count(*) FROM ('+query+') differences')
        result[label] = cur.fetchone()[0]
    result['repeated_identical_observations'] = result['raw_observations']-result['distinct_input_observations']
    result['conflicting_input_observations'] = result['distinct_input_observations']-result['distinct_entry_keys']
    if any(result[k] for k in ('raw_without_matching_canonical','canonical_without_matching_raw','conflicting_input_observations')):
        raise RuntimeError('BLOCKING: stored L3 coverage or revision conflict')
    return result


def audit(cur):
    # Independently compute expectations, rather than calling the normalization functions.
    cur.execute('''CREATE TEMP TABLE national_rate_audit ON COMMIT DROP AS
        SELECT r.race_date,r.venue_code,r.race_no,e.boat_no,e.player_id,
          e.national_win_rate_raw AS raw,e.national_win_rate AS value,
          e.national_win_rate_status AS status,s.source_record_id,s.source_batch_id,
          b.retrieved_at,
          (e.national_win_rate_raw IS DISTINCT FROM p.zenkoku_ritsu_1) AS raw_mismatch,
          (e.national_win_rate IS DISTINCT FROM CASE
             WHEN p.zenkoku_ritsu_1 ~ '^[0-9]{4}$' AND p.zenkoku_ritsu_1 <> '0000'
             THEN p.zenkoku_ritsu_1::numeric/100 END) AS value_mismatch,
          (e.national_win_rate_status IS DISTINCT FROM CASE
             WHEN p.zenkoku_ritsu_1 IS NULL OR btrim(p.zenkoku_ritsu_1)='' THEN 'MISSING'
             WHEN p.zenkoku_ritsu_1='0000' THEN 'UNRESOLVED'
             WHEN p.zenkoku_ritsu_1 ~ '^[0-9]{4}$' THEN 'VALID' ELSE 'INVALID' END) AS status_mismatch,
          (b.source_table IS DISTINCT FROM 'brd_l3'
           OR p.kaisai_nen IS DISTINCT FROM to_char(r.race_date,'YYYY')
           OR p.kaisai_tsukihi IS DISTINCT FROM to_char(r.race_date,'MMDD')
           OR p.kyoteijo_code IS DISTINCT FROM lpad(r.venue_code::text,2,'0')
           OR p.race_no IS DISTINCT FROM lpad(r.race_no::text,2,'0')
           OR p.teiban IS DISTINCT FROM e.boat_no::text) AS key_mismatch,
          (p.toroku_bango IS DISTINCT FROM lpad(e.player_id::text,4,'0')) AS registration_mismatch,
          (s.source_record_key IS DISTINCT FROM jsonb_build_object(
              'kaisai_nen',p.kaisai_nen,'kaisai_tsukihi',p.kaisai_tsukihi,
              'kyoteijo_code',p.kyoteijo_code,'race_no',p.race_no,
              'teiban',p.teiban)) AS record_key_mismatch
        FROM core.race_entry e JOIN core.race r USING(race_id)
        LEFT JOIN raw.source_record s ON s.source_record_id=e.source_record_id
        LEFT JOIN raw.source_batch b USING(source_batch_id)
        CROSS JOIN LATERAL jsonb_to_record(s.raw_payload) AS p(kaisai_nen text,
          kaisai_tsukihi text,kyoteijo_code text,race_no text,teiban text,
          toroku_bango text,zenkoku_ritsu_1 text)
        WHERE r.race_date >= DATE '2017-01-01' ''')
    measures = '''count(*) AS total_entries,
        count(*) FILTER (WHERE status='VALID') AS valid,
        count(*) FILTER (WHERE raw='0000') AS raw_0000,
        count(*) FILTER (WHERE status='INVALID') AS invalid,
        count(*) FILTER (WHERE status='UNRESOLVED') AS unresolved,
        count(*) FILTER (WHERE status='MISSING') AS missing,
        min(value) AS min_value,max(value) AS max_value'''
    out = {'overall': rows(cur, 'SELECT '+measures+" FROM national_rate_audit")[0]}
    for name, group in [('year','extract(year FROM race_date)::int'),('venue','venue_code'),('player','player_id')]:
        out[name] = rows(cur, f'SELECT {group} AS {name}, {measures} FROM national_rate_audit GROUP BY 1 ORDER BY 1')
    out['lineage'] = rows(cur, '''SELECT min(race_date) AS min_date,max(race_date) AS max_date,
        count(DISTINCT venue_code) AS venues,count(DISTINCT player_id) AS players,
        count(*) FILTER (WHERE raw_mismatch) AS raw_mismatch,
        count(*) FILTER (WHERE value_mismatch) AS value_mismatch,
        count(*) FILTER (WHERE status_mismatch) AS status_mismatch,
        count(*) FILTER (WHERE key_mismatch) AS key_mismatch,
        count(*) FILTER (WHERE registration_mismatch) AS registration_mismatch,
        count(*) FILTER (WHERE record_key_mismatch) AS record_key_mismatch,
        count(*) FILTER (WHERE source_record_id IS NULL OR source_batch_id IS NULL) AS missing_lineage,
        count(*) FILTER (WHERE retrieved_at IS NULL) AS unknown_retrieved_at,
        count(*)-count(DISTINCT (race_date,venue_code,race_no,boat_no)) AS duplicates
        FROM national_rate_audit''')[0]
    out['player_anomalies'] = {
        'players_with_invalid': sum(p['invalid'] > 0 for p in out['player']),
        'players_with_unresolved': sum(p['unresolved'] > 0 for p in out['player']),
        'top_0000': sorted(out['player'], key=lambda p: (-p['raw_0000'],p['player']))[:20],
        'note': 'Distributions only; no statistical outlier threshold or player exclusion inferred.'}
    for key in ('raw_mismatch','value_mismatch','status_mismatch','key_mismatch','record_key_mismatch',
                'registration_mismatch','missing_lineage','duplicates'):
        if out['lineage'][key]:
            raise RuntimeError('BLOCKING: '+key)
    return out


def run(apply=False, expected_entries=None):
    conn = target_connection()
    try:
        conn.commit()  # Complete the connection identity check before setting isolation.
        conn.set_session(isolation_level='REPEATABLE READ')
        with conn.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout='0'")
            # Prevent concurrent import/correction during the atomic upgrade and audit.
            if apply:
                cur.execute('LOCK TABLE core.race,core.race_entry IN SHARE ROW EXCLUSIVE MODE')
            before = protected_state(cur)
            changed = upgrade(cur, progress=True) if apply else 0
            out = audit(cur)
            out['raw_coverage'] = raw_coverage(cur)
            if expected_entries is not None and out['overall']['total_entries'] != expected_entries:
                raise RuntimeError('BLOCKING: entry coverage differs from expected count')
            if protected_state(cur) != before:
                raise RuntimeError('BLOCKING: protected state changed')
            out.update(updated_entries=changed, protected_state_unchanged=True,
                       expected_entries=expected_entries, applied=apply)
        conn.commit()
        return out
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--expected-entries', type=int)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    result = run(args.apply, args.expected_entries)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str)+'\n', encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('player','year','venue','player_anomalies')}, default=str))
