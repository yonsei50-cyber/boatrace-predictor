"""Read-only heuristic for C3 exhibition/C4 missing-slot disagreement."""
from collections import Counter
import json

from scripts.db import source_connection


def run():
    conn = source_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout='300s'")
            cur.execute("""WITH race AS (
                SELECT c4.kaisai_nen AS year,c4.kaisai_tsukihi AS mmdd,
                c4.kyoteijo_code AS venue,c4.race_no,count(*) AS boats,
                array_agg(c4.teiban ORDER BY c4.teiban)
                    FILTER (WHERE c3.tenji_time='0000') AS c3_zero,
                array_agg(c4.teiban ORDER BY c4.teiban)
                    FILTER (WHERE c4.isshu='0000' AND c4.mawariashi='0000'
                        AND c4.chokusen='0000') AS c4_zero
                FROM public.brd_c4 c4 JOIN public.brd_c3 c3
                    USING(kaisai_nen,kaisai_tsukihi,kyoteijo_code,race_no,teiban)
                WHERE c4.kyoteijo_code NOT IN ('01','12','13','18')
                GROUP BY 1,2,3,4)
                SELECT year,mmdd,venue,race_no,c3_zero[1],c4_zero[1]
                FROM race WHERE boats=6 AND array_length(c3_zero,1)=1
                  AND array_length(c4_zero,1)=1 AND c3_zero[1]<>c4_zero[1]
                ORDER BY 1,2,3,4""")
            candidates = [dict(day=y+d,venue=v,race_no=n,c3_zero_slot=c3,c4_zero_slot=c4)
                          for y,d,v,n,c3,c4 in cur.fetchall()]
        by_venue_year = Counter((r['venue'],r['day'][:4]) for r in candidates)
        return {'definition': 'one C3 exhibition 0000 slot, one C4 triple-0000 slot, different; six C4 boats; full-three-field venues only',
                'candidate_races': len(candidates),
                'by_venue_year': [dict(venue=v,year=y,races=n)
                                  for (v,y),n in sorted(by_venue_year.items())],
                'candidates': candidates}
    finally:
        conn.rollback();conn.close()


if __name__ == '__main__':
    result = run()
    with open('.local/c4_mapping_readonly.json','w',encoding='utf-8') as output:
        json.dump(result,output,ensure_ascii=False,indent=2)
    print(json.dumps({'candidate_races':result['candidate_races'],
                      'by_venue_year':result['by_venue_year']}))
