"""Read-only stored-source investigation; payout comparisons never create finishes."""
import argparse
from collections import Counter
import json
from itertools import permutations
from pathlib import Path
from psycopg2.extras import RealDictCursor, execute_values
from scripts.db import source_connection, target_connection
from scripts.foundation import digest
from scripts.import_sample import RACE_KEY


def selected(conn, table, keys):
    fields = RACE_KEY[:3] if table == 'brd_l1' else RACE_KEY
    keys = sorted({tuple(k[:len(fields)]) for k in keys})
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        query = ('SELECT s.* FROM public.'+table+' s JOIN (VALUES %s) k('+','.join(fields)+
                 ') USING ('+','.join(fields)+') ORDER BY '+','.join('s.'+f for f in fields))
        return [dict(r) for r in execute_values(cur, query, keys, fetch=True)] if keys else []


def verify_preserved_r2(report):
    expected=[(*r['natural_key'],r['r2_hash']) for r in report['duplicate_details']]
    expected += [(*r['natural_key'],r['record_hashes']['brd_r2'][0]) for r in report['five_unresolved']]
    conn=target_connection()
    try:
        conn.commit();conn.set_session(readonly=True)
        with conn.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout='180s'")
            result=execute_values(cur,"""WITH wanted(y,md,v,r,h) AS (VALUES %s)
                SELECT count(*),count(*) FILTER
                  (WHERE s.source_record_id IS NULL OR s.record_hash<>w.h)
                FROM wanted w LEFT JOIN (raw.source_record s JOIN raw.source_batch b USING(source_batch_id))
                ON b.source_table='brd_r2' AND s.raw_payload->>'kaisai_nen'=w.y
                AND s.raw_payload->>'kaisai_tsukihi'=w.md AND s.raw_payload->>'kyoteijo_code'=w.v
                AND s.raw_payload->>'race_no'=w.r""",expected,page_size=1000,fetch=True)
        if sum(r[0] for r in result)!=len(expected) or any(r[1] for r in result):
            raise RuntimeError('BLOCKING: investigated R2 differs from preserved evidence')
        return {'investigated_races':len(expected),'r2_raw_hash_mismatch':0}
    finally:
        conn.rollback();conn.close()


def run():
    conn = source_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout='180s'")
            cur.execute("""SELECT kaisai_nen,kaisai_tsukihi,kyoteijo_code,race_no
                FROM public.brd_r3 WHERE kaisai_nen >= '2017'
                AND chakujun ~ '^0?[1-6]$' GROUP BY 1,2,3,4,chakujun
                HAVING count(*)>1 ORDER BY 1,2,3,4""")
            duplicate_keys = cur.fetchall()
            cur.execute("""SELECT z.kaisai_nen,z.kaisai_tsukihi,z.kyoteijo_code,z.race_no
                FROM public.brd_r3 z JOIN public.brd_r2 r USING
                  (kaisai_nen,kaisai_tsukihi,kyoteijo_code,race_no)
                WHERE z.kaisai_nen >= '2017' AND r.data_kubun='0'
                  AND nullif(btrim(r.haraimodoshi_sanrentan_1a),'') IS NULL
                GROUP BY 1,2,3,4 HAVING count(*)=6
                  AND bool_and(nullif(btrim(z.chakujun),'') IS NULL)
                ORDER BY 1,2,3,4""")
            unresolved_keys = cur.fetchall()
        r2 = {tuple(r[k] for k in RACE_KEY):r for r in selected(conn,'brd_r2',duplicate_keys)}
        r3 = {}
        for row in selected(conn,'brd_r3',duplicate_keys):
            r3.setdefault(tuple(row[k] for k in RACE_KEY),[]).append(row)
        details=[]
        for key in duplicate_keys:
            boats=sorted(r3[key],key=lambda r:r['teiban'])
            payout = r2.get(key,{})
            slots={k:v for k,v in payout.items() if k.startswith('haraimodoshi_sanrentan_')}
            combinations=[v for k,v in slots.items() if k.endswith('a') and v and
                          len(v)==3 and all(c in '123456' for c in v) and len(set(v))==3]
            numeric=Counter(r['chakujun'] for r in boats if r['chakujun'].isdigit())
            ranks={r['teiban']:int(r['chakujun']) for r in boats
                   if r['chakujun'].isdigit() and 1<=int(r['chakujun'])<=6}
            top=sorted(ranks.values())[:3]
            # Comparison hypothesis only; no tie/finish normalization is inferred.
            expected={''.join(p) for p in permutations(ranks,3)
                      if [ranks[b] for b in p]==top}
            details.append({'natural_key':key,'r3':boats,'r2':payout,
                'r2_hash':digest(payout) if payout else None,
                'finish_by_boat':[r['chakujun'] for r in boats],
                'duplicate_positions':[p for p,n in numeric.items() if n>1],
                'trifecta_payout_slots':slots,'valid_trifecta_combinations':combinations,
                'equal_rank_order_hypothesis_combinations':sorted(expected),
                'payout_matches_equal_rank_order_hypothesis':set(combinations)==expected,
                'interpretation':'NUMERIC_DUPLICATE_UNRESOLVED',
                'reason':'Payout repetition supports source comparison, not universal tie certification.'})
        unresolved=[]
        for key in unresolved_keys:
            sources={t:selected(conn,t,[key]) for t in ('brd_l1','brd_l2','brd_l3','brd_r2','brd_r3')}
            unresolved.append({'natural_key':key,'sources':sources,
                'source_locations':{t:'pckyotei.public.'+t for t in sources},
                'record_hashes':{t:[digest(r) for r in rows] for t,rows in sources.items()},
                'interpretation':'UNRESOLVED'})
        return {'source_read_only':True,'duplicate_races':len(details),
            'duplicate_details':details,'five_unresolved':unresolved,
            'duplicate_payout_combination_counts':dict(Counter(len(d['valid_trifecta_combinations']) for d in details)),
            'equal_rank_order_hypothesis_matches':sum(d['payout_matches_equal_rank_order_hypothesis'] for d in details),
            'policy':'Stored R2 payout/results only; no odds, inferred finish, or eligibility.'}
    finally:
        conn.rollback();conn.close()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--report',type=Path,required=True)
    args=p.parse_args();result=run()
    result['preserved_r2_lineage']=verify_preserved_r2(result)
    args.report.parent.mkdir(parents=True,exist_ok=True)
    args.report.write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('duplicate_details','five_unresolved')}))
