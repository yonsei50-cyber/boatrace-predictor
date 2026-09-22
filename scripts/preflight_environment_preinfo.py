"""Read-only stored C2/C3/C4 inventory. No import, features, or model fitting."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from scripts.db import source_connection, target_connection

KEY = ('kaisai_nen','kaisai_tsukihi','kyoteijo_code','race_no')
PARTS = ('propeller','piston','piston_ring','denki_isshiki','carburetor',
         'cylinder','crankshaft','gearcase','careerbody')
FIELDS = {
    'brd_c2': ('suimenkisho_joho','hogaku_code','kion','tenki_code','fusoku','fuko_code','suion','hako'),
    'brd_c3': ('tenji_time','tilt','tenji_shinnyu_course','tenji_st','tenji_kigo')+PARTS,
    'brd_c4': ('hanshu','isshu','mawariashi','chokusen'),
}


def raw_shape(value):
    if value is None:return 'NULL'
    if value=='':return 'EMPTY'
    if not value.strip():return 'SPACE_ONLY'
    if set(value.strip()) <= {'_','＿'}:return 'UNDERSCORE'
    if re.fullmatch('[+-]?0+',value):return 'ZERO_TEXT'
    if re.fullmatch('[+-]?[0-9]+',value):return 'INTEGER_TEXT'
    return 'OTHER_TEXT'


def query(cur,sql,params=()):
    cur.execute(sql,params)
    return [dict(zip([c.name for c in cur.description],r)) for r in cur.fetchall()]


def table_profile(conn,table):
    fields=FIELDS[table]
    with conn.cursor() as cur:
        columns=query(cur,"SELECT column_name,data_type,character_maximum_length,is_nullable "
                      "FROM information_schema.columns WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position",(table,))
        pk=query(cur,"SELECT pg_get_constraintdef(c.oid) AS definition FROM pg_constraint c "
                 "JOIN pg_class t ON t.oid=c.conrelid JOIN pg_namespace n ON n.oid=t.relnamespace "
                 "WHERE n.nspname='public' AND t.relname=%s AND c.contype='p'",(table,))
        race_rows=query(cur,'SELECT kaisai_nen AS year,kyoteijo_code AS venue,count(*) AS rows,'
            'count(DISTINCT (kaisai_tsukihi,race_no)) AS races,min(kaisai_nen||kaisai_tsukihi) AS first_date,'
            'max(kaisai_nen||kaisai_tsukihi) AS last_date FROM public.'+table+
            " WHERE kaisai_nen>='2017' GROUP BY 1,2 ORDER BY 1,2")
        missing=query(cur,'SELECT l.kaisai_nen AS year,l.kyoteijo_code AS venue,count(*) AS missing_races '
            'FROM public.brd_l2 l WHERE l.kaisai_nen>=\'2017\' AND NOT EXISTS (SELECT 1 FROM public.'+table+
            ' s WHERE '+ ' AND '.join('s.'+k+'=l.'+k for k in KEY)+') GROUP BY 1,2 ORDER BY 1,2')
        orphan=query(cur,'SELECT count(*) AS rows FROM public.'+table+" s WHERE s.kaisai_nen>='2017' AND NOT EXISTS "
            '(SELECT 1 FROM public.brd_l2 l WHERE '+ ' AND '.join('s.'+k+'=l.'+k for k in KEY)+')')[0]['rows']
        boats=query(cur,'SELECT n AS boat_rows,count(*) AS races FROM (SELECT count(*) AS n FROM public.'+table+
            " WHERE kaisai_nen>='2017' GROUP BY "+','.join(KEY)+') x GROUP BY 1 ORDER BY 1')
    overall={f:Counter() for f in fields}
    groups={}
    dates={f:{} for f in fields}
    nonzero_dates={f:{} for f in fields}
    examples={f:{} for f in fields}
    st_combo=Counter();parts_combo=Counter();parts_examples=[];codes=Counter()
    total=0
    with conn.cursor(name='profile_'+table) as cur:
        cur.itersize=10000
        selected=KEY+(('teiban',) if table!='brd_c2' else ())+('record_id','data_kubun')+fields
        cur.execute('SELECT '+','.join(selected)+' FROM public.'+table+" WHERE kaisai_nen>='2017'")
        for values in cur:
            row=dict(zip(selected,values));year=row['kaisai_nen'];venue=row['kyoteijo_code']
            day=year+row['kaisai_tsukihi'];group=(year,venue)
            bucket=groups.setdefault(group,{f:Counter() for f in fields})
            codes[(row['record_id'],row['data_kubun'])]+=1
            for field in fields:
                value=row[field];shape=raw_shape(value)
                overall[field][value]+=1;bucket[field][shape]+=1
                if shape not in ('NULL','EMPTY','SPACE_ONLY','UNDERSCORE'):
                    bounds=dates[field].setdefault(venue,[day,day])
                    bounds[0]=min(bounds[0],day);bounds[1]=max(bounds[1],day)
                if shape=='INTEGER_TEXT':
                    bounds=nonzero_dates[field].setdefault(venue,[day,day])
                    bounds[0]=min(bounds[0],day);bounds[1]=max(bounds[1],day)
                if shape not in examples[field]:
                    examples[field][shape]={'key':{k:row[k] for k in KEY+(('teiban',) if table!='brd_c2' else ())},'raw':value}
            if table=='brd_c3':
                st_combo[(row['tenji_kigo'],raw_shape(row['tenji_st']),row['tenji_shinnyu_course'])]+=1
                positive=[f for f in PARTS if row[f] is not None and re.fullmatch('[1-9]',row[f])]
                parts_combo[(year,venue,len(positive))]+=1
                if len(positive)>1 and len(parts_examples)<5:
                    parts_examples.append({'key':{k:row[k] for k in KEY+('teiban',)},'raw':{f:row[f] for f in PARTS}})
            total+=1
            if total%500000==0:print(json.dumps({'table':table,'profiled':total}),flush=True)
    if total!=sum(r['rows'] for r in race_rows):
        raise RuntimeError('profile row count differs from independent SQL count')
    profile={}
    for field,counter in overall.items():
        shapes=Counter()
        for value,count in counter.items():shapes[raw_shape(value)]+=count
        profile[field]={'raw_values':[{'raw':v,'rows':n} for v,n in sorted(counter.items(),key=lambda x:(x[0] is not None,x[0] or ''))],
            'shapes':dict(shapes),'nonblank_bounds_by_venue':dates[field],
            'nonzero_integer_bounds_by_venue':nonzero_dates[field],'examples':examples[field]}
    result={'source':'pckyotei.public.'+table,'columns':columns,'primary_key':pk,
        'rows':total,'races':sum(r['races'] for r in race_rows),'year_venue':race_rows,
        'missing_vs_l2':missing,'orphan_rows_vs_l2':orphan,'rows_per_race':boats,
        'record_codes':[{'record_id':k[0],'data_kubun':k[1],'rows':n} for k,n in codes.items()],
        'fields':profile,'year_venue_field_shapes':[
            {'year':year,'venue':venue,'fields':{f:dict(c) for f,c in group.items()}}
            for (year,venue),group in sorted(groups.items())]}
    if table=='brd_c3':
        result['start_exhibition_combinations']=[{'kigo':k[0],'st_shape':k[1],'course_raw':k[2],'rows':v} for k,v in st_combo.items()]
        result['positive_part_field_counts']=[{'year':k[0],'venue':k[1],'positive_fields':k[2],'rows':v} for k,v in parts_combo.items()]
        result['multiple_parts_examples']=parts_examples
    return result


def targeted_checks():
    conn=source_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout='180s'")
            wind=query(cur,"""SELECT fusoku,CASE WHEN nullif(btrim(fuko_code),'') IS NULL
                THEN 'BLANK' ELSE 'PRESENT' END AS direction_state,count(*) AS rows
                FROM public.brd_c2 WHERE kaisai_nen>='2017' GROUP BY 1,2 ORDER BY 1,2""")
            st=query(cur,"""SELECT kaisai_nen AS year,kyoteijo_code AS venue,
                tenji_kigo,CASE WHEN nullif(btrim(tenji_st),'') IS NULL THEN 'BLANK'
                WHEN tenji_st ~ '^[0-9]{3}$' THEN 'THREE_DIGITS' ELSE 'OTHER' END AS st_format,
                count(*) AS rows FROM public.brd_c3 WHERE kaisai_nen>='2017'
                GROUP BY 1,2,3,4 ORDER BY 1,2,3,4""")
            sample=query(cur,"""SELECT c.*,l.shimekiri_yotei_jikoku FROM public.brd_c2 c
                JOIN public.brd_l2 l USING(kaisai_nen,kaisai_tsukihi,kyoteijo_code,race_no)
                WHERE c.kaisai_nen='2026' AND c.kaisai_tsukihi='0918' AND c.kyoteijo_code='02'
                ORDER BY c.race_no""")
            changes=query(cur,"""SELECT CASE WHEN kaisai_nen||kaisai_tsukihi<'20250411'
                THEN 'BEFORE_20250411' ELSE 'FROM_20250411' END AS period,count(*) AS rows,
                count(*) FILTER (WHERE coalesce(nullif(btrim(hanshu),''),'0000')='0000'
                  AND coalesce(nullif(btrim(isshu),''),'0000')='0000'
                  AND coalesce(nullif(btrim(mawariashi),''),'0000')='0000'
                  AND coalesce(nullif(btrim(chokusen),''),'0000')='0000') AS all_blank_or_zero,
                count(*) FILTER (WHERE hanshu='0000' OR isshu='0000' OR mawariashi='0000' OR chokusen='0000') AS any_zero
                FROM public.brd_c4 WHERE kaisai_nen>='2017' GROUP BY 1 ORDER BY 1""")
            incidents=query(cur,"""SELECT * FROM public.brd_c4 WHERE
                (kaisai_nen,kaisai_tsukihi,kyoteijo_code) IN
                (('2025','0728','20'),('2025','0722','06'),('2024','1125','24'),
                 ('2023','1216','24'),('2025','0726','20'),('2025','0604','24'),('2025','0820','24'))
                ORDER BY kaisai_nen,kaisai_tsukihi,kyoteijo_code,race_no,teiban""")
            incomplete=query(cur,"""SELECT kaisai_nen,kaisai_tsukihi,kyoteijo_code,race_no,
                count(*) AS rows,array_agg(teiban ORDER BY teiban) AS boats FROM public.brd_c4
                WHERE kaisai_nen>='2017' GROUP BY 1,2,3,4 HAVING count(*)<>6 ORDER BY 1,2,3,4""")
            small_large=query(cur,"""SELECT * FROM public.brd_c4 WHERE kaisai_nen>='2017'
                AND (isshu='0004' OR isshu='6877' OR mawariashi='0005' OR chokusen='3833')
                ORDER BY kaisai_nen,kaisai_tsukihi,kyoteijo_code,race_no,teiban""")
        return {'wind_direction_pairs':wind,'start_exhibition_year_venue':st,'c2_marker_sample':sample,
            'c4_acquisition_policy_periods':changes,'c4_publisher_incident_rows':incidents,
            'c4_incomplete_races':incomplete,'c4_diagnostic_raw_examples':small_large}
    finally:conn.rollback();conn.close()


def run(output):
    conn=source_connection()
    result={'observed_at':datetime.now(timezone.utc).isoformat(),'scope_start':'2017-01-01',
        'policy':'read-only source inventory; raw-shape counts are not semantic normalization', 'tables':{}}
    try:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout='180s'")
            cur.execute('SHOW transaction_read_only');result['source_read_only']=cur.fetchone()[0]
            result['l2_year_venue']=query(cur,"SELECT kaisai_nen AS year,kyoteijo_code AS venue,count(*) AS races FROM public.brd_l2 WHERE kaisai_nen>='2017' GROUP BY 1,2 ORDER BY 1,2")
            result['other_source_fields']=query(cur,"SELECT table_name,column_name,data_type FROM information_schema.columns WHERE table_schema='public' AND column_name ~ '(fusoku|fuko|hako|kion|suion|tenki|tenji|hanshu|isshu|mawariashi|chokusen|tilt|piston)' ORDER BY 1,2")
            result['result_source_alternatives']={}
            for table in ('brd_r2','brd_k2','brd_k3'):
                result['result_source_alternatives'][table]=query(cur,'SELECT count(*) AS rows,'
                    'min(kaisai_nen||kaisai_tsukihi) AS first_date,max(kaisai_nen||kaisai_tsukihi) AS last_date '
                    'FROM public.'+table+" WHERE kaisai_nen>='2017'")[0]
        for table in FIELDS:
            print('profile '+table,flush=True)
            result['tables'][table]=table_profile(conn,table)
            output.write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
        with conn.cursor() as cur:
            result['missing_c2_keys']=query(cur,"""SELECT l.kaisai_nen,l.kaisai_tsukihi,l.kyoteijo_code,l.race_no
                FROM public.brd_l2 l LEFT JOIN public.brd_c2 c USING(kaisai_nen,kaisai_tsukihi,kyoteijo_code,race_no)
                WHERE l.kaisai_nen>='2017' AND c.record_id IS NULL ORDER BY 1,2,3,4""")
            result['c2_time_marker']=query(cur,"""SELECT c.kaisai_nen AS year,c.kyoteijo_code AS venue,
                count(*) AS rows,count(*) FILTER (WHERE c.suimenkisho_joho ~ '^([01][0-9]|2[0-3])[0-5][0-9]$') AS hhmm_rows,
                count(*) FILTER (WHERE c.suimenkisho_joho ~ '^([01][0-9]|2[0-3])[0-5][0-9]$'
                  AND l.shimekiri_yotei_jikoku ~ '^([01][0-9]|2[0-3])[0-5][0-9]$'
                  AND c.suimenkisho_joho>l.shimekiri_yotei_jikoku) AS after_nominal_deadline
                FROM public.brd_c2 c JOIN public.brd_l2 l USING(kaisai_nen,kaisai_tsukihi,kyoteijo_code,race_no)
                WHERE c.kaisai_nen>='2017' GROUP BY 1,2 ORDER BY 1,2""")
            result['c2_marker_by_race']=query(cur,"""SELECT race_no,count(*) AS rows,
                count(*) FILTER (WHERE nullif(btrim(suimenkisho_joho),'') IS NOT NULL) AS nonblank
                FROM public.brd_c2 WHERE kaisai_nen>='2017' GROUP BY 1 ORDER BY 1""")
        target=target_connection()
        try:
            target.commit();target.set_session(readonly=True)
            with target.cursor() as cur:
                result['new_raw_source_coverage']=query(cur,'SELECT source_table,count(*) AS batches,sum(row_count) AS rows FROM raw.source_batch GROUP BY 1 ORDER BY 1')
        finally:target.rollback();target.close()
        return result
    finally:
        conn.rollback();conn.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args();args.report.parent.mkdir(parents=True,exist_ok=True)
    result=run(args.report)
    result['targeted_checks']=targeted_checks()
    result['complete']=True
    args.report.write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str)+'\n',encoding='utf-8')
    print(json.dumps({t:{k:v[k] for k in ('rows','races','orphan_rows_vs_l2')} for t,v in result['tables'].items()}))
