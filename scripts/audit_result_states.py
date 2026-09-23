"""Reproducible Phase 3B coverage over preserved Raw; no model eligibility."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from scripts.db import target_connection
from scripts.foundation import canonical_json, digest
from scripts.national_win_rate import rows


def protected_state(cur):
    out={}
    for table in ('race','race_entry','race_result','dataset_version'):
        cur.execute('SELECT count(*),sum(hashtextextended(to_jsonb(x)::text,0)::numeric) FROM core.'+table+' x')
        out[table]=list(cur.fetchone())
    cur.execute("SELECT source_batch_id,content_hash,row_count FROM raw.source_batch "
                "WHERE source_table IN ('brd_l1','brd_l2','brd_l3','brd_k3','brd_ki') ORDER BY 1")
    out['prior_raw_batches']=digest(cur.fetchall())
    return json.loads(json.dumps(out,default=str))


def audit(cur):
    print('materialize race states', flush=True)
    cur.execute('CREATE TEMP TABLE rs ON COMMIT DROP AS SELECT * FROM core.race_result_state')
    cur.execute('CREATE UNIQUE INDEX ON rs(race_id)')
    print('materialize boat states', flush=True)
    cur.execute('CREATE TEMP TABLE bs ON COMMIT DROP AS SELECT * FROM core.boat_finish_state')
    cur.execute('CREATE UNIQUE INDEX ON bs(race_id,boat_no)')
    cur.execute('ANALYZE rs');cur.execute('ANALYZE bs')
    out={'race_states':rows(cur,'SELECT result_state,count(*) AS races FROM rs GROUP BY 1 ORDER BY 1'),
         'finish_states':rows(cur,'SELECT finish_state,count(*) AS boats FROM bs GROUP BY 1 ORDER BY 1')}
    out['totals']=rows(cur,"""SELECT (SELECT count(*) FROM rs) AS races,
        (SELECT count(*) FROM bs) AS entries,
        (SELECT count(*) FROM core.race_result) AS canonical_results,
        (SELECT count(*) FROM rs WHERE k3_distinct_boats=6 AND k3_meaningful_boats=0) AS blank_k3_races,
        (SELECT count(DISTINCT race_id) FROM bs WHERE finish_state='NUMERIC_DUPLICATE_UNRESOLVED') AS duplicate_numeric_races""")[0]
    out['blank_k3']=rows(cur,"""SELECT result_state,count(*) AS races FROM rs
        WHERE k3_distinct_boats=6 AND k3_meaningful_boats=0 GROUP BY 1 ORDER BY 1""")
    out['r2_evidence']=rows(cur,"""SELECT r2_data_kubun_raw_values,
        has_valid_r2_trifecta_payout,count(*) AS races FROM rs GROUP BY 1,2 ORDER BY 1,2""")
    out['special_symbols']=rows(cur,"""SELECT finish_raw,count(*) AS boats,
        count(DISTINCT race_id) AS races FROM bs WHERE finish_state='UNRESOLVED_SPECIAL'
        GROUP BY 1 ORDER BY 1""")
    for dimension,expr in [('year','extract(year FROM race_date)::int'),('venue','venue_code')]:
        out[dimension]={
            'race_states':rows(cur,f'SELECT {expr} AS {dimension},result_state,count(*) AS races FROM rs GROUP BY 1,2 ORDER BY 1,2'),
            'finish_states':rows(cur,f'SELECT {expr} AS {dimension},finish_state,count(*) AS boats FROM bs GROUP BY 1,2 ORDER BY 1,2'),
            'symbols':rows(cur,f"SELECT {expr} AS {dimension},finish_raw,count(*) AS boats FROM bs WHERE finish_state='UNRESOLVED_SPECIAL' GROUP BY 1,2 ORDER BY 1,2"),
            'fl':rows(cur,f"SELECT {expr} AS {dimension},start_timing_status,count(*) AS boats FROM bs WHERE start_timing_status IN ('F','L') GROUP BY 1,2 ORDER BY 1,2")}
    out['fl_combinations']=rows(cur,"""SELECT start_timing_status,finish_raw,finish_state,
        result_state,actual_course IS NOT NULL AS actual_course_present,count(*) AS boats
        FROM bs JOIN rs USING(race_id) WHERE start_timing_status IN ('F','L')
        GROUP BY 1,2,3,4,5 ORDER BY 1,2,3,4,5""")
    out['lineage']=rows(cur,"""SELECT
        count(*) FILTER (WHERE b.finish_raw IS DISTINCT FROM z.finish_raw) AS finish_mismatch,
        count(*) FILTER (WHERE b.finish_position IS DISTINCT FROM z.finish_position) AS numeric_mismatch,
        count(*) FILTER (WHERE b.start_timing_raw IS DISTINCT FROM z.start_timing_raw) AS st_raw_mismatch,
        count(*) FILTER (WHERE b.start_timing IS DISTINCT FROM z.start_timing) AS st_mismatch,
        count(*) FILTER (WHERE b.start_timing_status IS DISTINCT FROM z.start_timing_status) AS st_status_mismatch,
        count(*) FILTER (WHERE b.k3_source_record_ids IS NULL
                          OR NOT z.source_record_id=ANY(b.k3_source_record_ids)) AS missing_adopted_source,
        count(*) FILTER (WHERE b.start_timing_status IN ('F','L') AND b.start_timing IS NOT NULL) AS numeric_fl
        FROM bs b JOIN core.race_result z USING(race_id,boat_no)""")[0]
    out['unresolved_races']=rows(cur,"""SELECT race_date,venue_code,race_no,k3_distinct_boats,
        k3_meaningful_boats,r2_data_kubun_raw_values,r2_source_record_ids,k3_source_record_ids
        FROM rs WHERE result_state='UNRESOLVED' ORDER BY 1,2,3""")
    out['duplicates']=rows(cur,"""SELECT r.race_date,r.venue_code,r.race_no,r.result_state,
        array_agg(b.finish_raw ORDER BY b.boat_no) AS finish_by_boat,
        r.r2_source_record_ids,r.k3_source_record_ids FROM rs r JOIN bs b USING(race_id)
        WHERE r.race_id IN (SELECT race_id FROM bs WHERE finish_state='NUMERIC_DUPLICATE_UNRESOLVED')
        GROUP BY r.race_id,r.race_date,r.venue_code,r.race_no,r.result_state,
          r.r2_source_record_ids,r.k3_source_record_ids ORDER BY 1,2,3""")
    cur.execute('SELECT count(*) FROM rs WHERE r2_revision_conflict OR k3_revision_conflict')
    out['source_conflict_races']=cur.fetchone()[0]
    if any(out['lineage'].values()) or out['source_conflict_races']:
        raise RuntimeError('BLOCKING: lineage/conflict audit')
    if (out['totals']['entries'] != out['totals']['races'] * 6
            or out['totals']['canonical_results'] > out['totals']['entries']
            or out['totals']['blank_k3_races'] > out['totals']['races']):
        raise RuntimeError('BLOCKING: inconsistent K3 result totals '+str(out['totals']))
    out['duplicate_canonical_rows']=0  # Both existing PK and temporary unique indexes enforced.
    out['independent_numeric_check']=rows(cur,"""WITH duplicate_races AS (
        SELECT DISTINCT race_id FROM core.race_result WHERE finish_position IS NOT NULL
        GROUP BY race_id,finish_position HAVING count(*)>1)
        SELECT count(*) FILTER (WHERE b.finish_state='NUMERIC_VALID' AND
            (z.finish_position IS NULL OR d.race_id IS NOT NULL)) AS invalid_valid,
          count(*) FILTER (WHERE z.finish_position IS NOT NULL AND d.race_id IS NULL
            AND b.finish_state<>'NUMERIC_VALID') AS missing_valid
        FROM bs b LEFT JOIN core.race_result z USING(race_id,boat_no)
        LEFT JOIN duplicate_races d ON d.race_id=b.race_id""")[0]
    if any(out['independent_numeric_check'].values()):
        raise RuntimeError('BLOCKING: independent numeric classification')
    return out


def r2_hashes(conn):
    result={'rows':0,'batches':0,'lineage_mismatch':0}
    with conn.cursor() as cur:
        cur.execute("SELECT source_batch_id,row_count,content_hash FROM raw.source_batch WHERE source_table='brd_r2' ORDER BY 1")
        batches=cur.fetchall()
    for batch,count,expected in batches:
        h=hashlib.sha256(b'[');n=0
        with conn.cursor(name='r2hash') as cur:
            cur.execute('SELECT raw_payload,record_hash,source_record_key,source_position FROM raw.source_record WHERE source_batch_id=%s ORDER BY source_position',(batch,))
            for payload,row_hash,key,position in cur:
                encoded=canonical_json(payload).encode('utf-8')
                if digest(payload)!=row_hash or key!={k:payload[k] for k in ('kaisai_nen','kaisai_tsukihi','kyoteijo_code','race_no')} or position!=n+1:
                    raise RuntimeError('R2 raw lineage/hash mismatch')
                if n:h.update(b',')
                h.update(encoded);n+=1
        h.update(b']')
        if n!=count or h.hexdigest()!=expected:raise RuntimeError('R2 batch hash mismatch')
        result['rows']+=n;result['batches']+=1
    return result


def run(protected_before=None):
    conn=target_connection()
    try:
        conn.commit();conn.set_session(isolation_level='REPEATABLE READ')
        with conn.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout='0'")
            result=audit(cur)
            if protected_before:
                result['protected_state']=protected_state(cur)
                if result['protected_state']!=json.loads(protected_before.read_text(encoding='utf-8')):
                    raise RuntimeError('BLOCKING: existing Canonical/frozen state changed')
                result['protected_state_unchanged']=True
        result['r2_raw']=r2_hashes(conn)
        return result
    finally:
        conn.rollback();conn.close()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--report',type=Path,required=True)
    p.add_argument('--protected-before',type=Path)
    a=p.parse_args();result=run(a.protected_before);a.report.parent.mkdir(parents=True,exist_ok=True)
    a.report.write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
    print(json.dumps(result['totals']))
