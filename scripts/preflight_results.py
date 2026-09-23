"""Read-only 2017+ result inventory; no interpretation, scoring or adoption."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path

from scripts.db import source_connection, target_connection


def inventory():
    out = {'scope_start': '2017-01-01', 'observed_at': datetime.now(timezone.utc).isoformat(),
           'policy': 'inventory only; no inferred ranking, points or eligibility'}
    conn = target_connection()
    conn.commit()
    conn.set_session(readonly=True, isolation_level='REPEATABLE READ')
    try:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout='180s'")
            cur.execute("SHOW transaction_read_only")
            out['target_read_only'] = cur.fetchone()[0]
        symbols = defaultdict(lambda: {'rows': 0, 'races': 0, 'years': Counter(),
            'venues': Counter(), 'statuses': Counter(), 'numeric_coexist_rows': 0,
            'numeric_coexist_races': 0, 'combinations': Counter(), 'examples': []})
        duplicates = []
        with conn.cursor(name='preflight_results') as cur:
            cur.itersize = 2000
            cur.execute("""SELECT r.race_date,r.venue_code,r.race_no,r.race_status,
                jsonb_agg(jsonb_build_object('boat',z.boat_no,'raw',z.finish_raw,
                  'numeric',z.finish_position,'status',z.result_status,
                  'symbol',z.result_symbol_raw,'st_raw',z.start_timing_raw,
                  'st',z.start_timing,'st_status',z.start_timing_status,
                  'source_id',z.source_record_id) ORDER BY z.boat_no)
                FROM core.race r JOIN core.race_result z USING(race_id)
                WHERE r.race_date >= '2017-01-01'
                GROUP BY r.race_id ORDER BY r.race_id""")
            for day, venue, race, race_status, results in cur:
                numeric = Counter(x['numeric'] for x in results if x['numeric'] is not None)
                combo = '|'.join(x['raw'] if x['raw'] is not None else '<NULL>' for x in results)
                seen = set()
                for x in results:
                    if x['numeric'] is not None:
                        continue
                    s = symbols[x['raw']]
                    s['rows'] += 1
                    s['years'][str(day.year)] += 1
                    s['venues'][str(venue).zfill(2)] += 1
                    s['statuses'][x['status']] += 1
                    s['numeric_coexist_rows'] += bool(numeric)
                    s['combinations'][combo] += 1
                    if x['raw'] not in seen:
                        s['races'] += 1
                        s['numeric_coexist_races'] += bool(numeric)
                        seen.add(x['raw'])
                    if len(s['examples']) < 3:
                        s['examples'].append({'date': str(day), 'venue': venue, 'race': race,
                            'race_status': race_status, 'result': x, 'all_finish': combo})
                    if x['status'] in ('F', 'L') and x['st'] is not None:
                        raise RuntimeError('F/L numeric ST detected')
                for position, count in numeric.items():
                    if count > 1:
                        duplicates.append({'date': str(day), 'venue': venue, 'race': race,
                            'position': position, 'count': count, 'results': results,
                            'meaning': 'UNRESOLVED'})
        out['symbols'] = dict(symbols)
        out['duplicate_numeric_finish'] = {'groups': len(duplicates),
            'races': len({(x['date'], x['venue'], x['race']) for x in duplicates}),
            'years': dict(Counter(x['date'][:4] for x in duplicates)),
            'venues': dict(Counter(str(x['venue']).zfill(2) for x in duplicates)),
            'positions': dict(Counter(x['position'] for x in duplicates)), 'details': duplicates}
    finally:
        conn.rollback()
        conn.close()
    conn = source_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout='180s'")
            cur.execute('SHOW transaction_read_only')
            out['source_read_only'] = cur.fetchone()[0]
            query = """SELECT z.kaisai_nen,z.kaisai_tsukihi,z.kyoteijo_code,z.race_no,
                count(*) AS rows,array_agg(DISTINCT z.data_kubun),
                array_agg(DISTINCT r.data_kubun),
                count(*) FILTER (WHERE nullif(btrim(z.toroku_bango),'') IS NULL
                  AND nullif(btrim(z.shinnyu_course),'') IS NULL
                  AND nullif(btrim(z.st),'') IS NULL)
                FROM public.brd_k3 z LEFT JOIN public.brd_r2 r USING
                  (kaisai_nen,kaisai_tsukihi,kyoteijo_code,race_no)
                WHERE z.kaisai_nen >= '2017' AND nullif(btrim(z.chakujun),'') IS NULL
                GROUP BY 1,2,3,4 ORDER BY 1,2,3,4"""
            cur.execute(query)
            rows = cur.fetchall()
            out['blank_k3'] = {'query': query, 'rows': sum(x[4] for x in rows),
                'races': len(rows), 'years': dict(Counter()), 'venues': dict(Counter()),
                'race_state_groups': {}, 'details': rows}
            for key, index in [('years', 0), ('venues', 2)]:
                counts = Counter()
                for x in rows:
                    counts[x[index]] += x[4]
                out['blank_k3'][key] = dict(counts)
            out['blank_k3']['race_state_groups'] = dict(Counter(
                json.dumps({'rows': x[4], 'k3_data_kubun': x[5],
                            'r2_data_kubun': x[6], 'all_three_blank': x[7]}, ensure_ascii=False)
                for x in rows))
            cur.execute("""SELECT z.kaisai_nen,z.kaisai_tsukihi,z.kyoteijo_code,z.race_no,
                r.data_kubun,r.haraimodoshi_sanrentan_1a,
                array_agg(z.chakujun ORDER BY z.teiban)
                FROM public.brd_k3 z JOIN public.brd_r2 r USING
                  (kaisai_nen,kaisai_tsukihi,kyoteijo_code,race_no)
                WHERE z.kaisai_nen >= '2017' AND EXISTS (
                    SELECT 1 FROM public.brd_k3 u WHERE u.kaisai_nen=z.kaisai_nen
                    AND u.kaisai_tsukihi=z.kaisai_tsukihi AND u.kyoteijo_code=z.kyoteijo_code
                    AND u.race_no=z.race_no
                    AND btrim(u.chakujun) IN ('K','K0','K1','S','S0','S1','S2','00','＿'))
                GROUP BY 1,2,3,4,5,6 ORDER BY 1,2,3,4""")
            out['special_r2_evidence'] = cur.fetchall()
            cur.execute("""SELECT r.data_kubun,r.haraimodoshi_sanrentan_1a,count(*)
                FROM public.brd_r2 r WHERE r.kaisai_nen >= '2017' AND EXISTS (
                    SELECT 1 FROM public.brd_k3 z WHERE z.kaisai_nen=r.kaisai_nen
                    AND z.kaisai_tsukihi=r.kaisai_tsukihi AND z.kyoteijo_code=r.kyoteijo_code
                    AND z.race_no=r.race_no AND nullif(btrim(z.chakujun),'') IS NULL)
                GROUP BY 1,2 ORDER BY 1,2""")
            out['blank_r2_payout_states'] = cur.fetchall()
            cur.execute("""SELECT teiban,toroku_bango,chakujun,st FROM public.brd_k3
                WHERE kaisai_nen='2026' AND kaisai_tsukihi='0531'
                AND kyoteijo_code='06' AND race_no='07' ORDER BY teiban""")
            out['official_tie_sample'] = {
                'url': 'https://www.boatrace.jp/owpc/pc/race/resultlist?hd=20260531&jcd=06',
                'race': 7, 'source_rows': cur.fetchall(),
                'web_evidence': 'official page explicitly marks tie; boats 2/4 both second',
                'scope': 'one verified race only; not proof for all 515 groups'}
    finally:
        conn.rollback()
        conn.close()
    return out


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    result = inventory()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding='utf-8')
    print(json.dumps({'symbols': {k: {a: v for a, v in s.items() if a in
        ('rows', 'races', 'numeric_coexist_rows', 'numeric_coexist_races', 'statuses')}
        for k, s in result['symbols'].items()}, 'duplicate_groups': result['duplicate_numeric_finish']['groups'],
        'duplicate_races': result['duplicate_numeric_finish']['races'],
        'blank_rows': result['blank_k3']['rows'], 'blank_races': result['blank_k3']['races']}, ensure_ascii=False))
