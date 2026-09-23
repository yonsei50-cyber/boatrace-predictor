"""Phase 2.5: resumable complete stored-history import; no predictive features."""
import argparse
import csv
import io
from collections import defaultdict
from datetime import date, datetime, timezone, timedelta
import json
from pathlib import Path
from psycopg2.extras import Json, execute_values
from scripts.db import source_connection, target_connection
from scripts.foundation import (canonical_json, digest, integer, motor_generation,
    identity_observation, women_only, VENUES, NORMALIZATION_VERSION, MOTOR_RULE_VERSION)
from scripts.import_sample import KEYS, key, race_date, insert, snapshot_before
from scripts.normalize import normalize_result, normalize_sex, normalize_grade, source_boolean
from scripts.history_source import TABLES, IDENTITY_SUPPORT, inventory, extract
from scripts.result_dataset_version import record_k3_result_dataset_version

VERSION = 'phase2.5-k3-only-history-v1'


def extraction_condition(table, partition):
    # identity-before-2017 is a named deterministic selection defined in
    # history_source.identity_support and docs/analysis_periods.md.
    return {'version':VERSION,'partition':partition,'order_by':list(KEYS[table])}


def bulk(cur, table, rows, conflict=''):
    if not rows:
        return
    fields = list(rows[0])
    if table in ('core.race_entry','core.race_result') and conflict=='ON CONFLICT (race_id,boat_no) DO NOTHING':
        # The importer holds a session advisory lock. Existing rows were checked
        # against their immutable source before reaching this transport path.
        cur.execute('SELECT race_id,boat_no FROM '+table+' WHERE race_id=ANY(%s)',
                    (sorted({r['race_id'] for r in rows}),))
        existing=set(cur.fetchall())
        rows=[r for r in rows if (r['race_id'],r['boat_no']) not in existing]
        if not rows:
            return
        buffer=io.StringIO()
        def encode(value):
            if value is None:
                return r'\N'
            value=canonical_json(value) if isinstance(value,(dict,list)) else str(value)
            return value.replace('\\','\\\\').replace('\t','\\t').replace('\n','\\n').replace('\r','\\r')
        for row in rows:
            buffer.write('\t'.join(encode(row[f]) for f in fields)+'\n')
        buffer.seek(0)
        cur.copy_expert('COPY '+table+' ('+','.join(fields)+') FROM STDIN',buffer)
        return
    values = [[Json(r[f], dumps=canonical_json) if isinstance(r[f], (dict,list)) else r[f]
               for f in fields] for r in rows]
    execute_values(cur, 'INSERT INTO '+table+' ('+','.join(fields)+') VALUES %s '+conflict,
                   values, page_size=1000)


def copy_raw(cur, batch, table, rows):
    """COPY changes transport only; the same FK/immutable batch guards still run."""
    buffer=io.StringIO()
    writer=csv.writer(buffer,lineterminator='\n')
    for position,row in enumerate(rows,1):
        writer.writerow((batch,canonical_json({k:row[k] for k in KEYS[table]}),position,
                         canonical_json(row),digest(row),'PRESERVED'))
    buffer.seek(0)
    cur.copy_expert('COPY raw.source_record (source_batch_id,source_record_key,source_position,'
                    'raw_payload,record_hash,interpretation_status) FROM STDIN WITH (FORMAT CSV)',buffer)


def preserve(cur, table, partition, rows, extracted_at):
    """One immutable complete partition. Changes are preserved, never auto-adopted."""
    if partition < '2017':
        raise ValueError('history scope starts 2017-01-01; pre-2017 full partitions are disabled')
    condition = extraction_condition(table,partition)
    hashed = digest(rows)
    cur.execute('SELECT source_batch_id,content_hash FROM raw.source_batch '
                'WHERE source_table=%s AND extraction_condition=%s ORDER BY source_batch_id',
                (table, Json(condition)))
    prior = cur.fetchall()
    equal = [i for i,h in prior if h == hashed]
    if equal:
        return equal[0], False, len({h for _,h in prior}) > 1
    batch = insert(cur, 'raw.source_batch', dict(source_name='PC-KYOTEI',
        source_type='SOURCE_DB_EXTRACT', source_locator='pckyotei.public.'+table,
        extraction_condition=condition, source_database='pckyotei', source_schema='public',
        source_table=table, retrieved_at=None, extracted_at=extracted_at,
        content_hash=hashed, row_count=len(rows), metadata={'phase':'2.5',
            'transaction_read_only':'on', 'acquisition_history':'UNKNOWN',
            'source_year_is_not_retrieval_time':True},
        status='PRESERVED' if rows else 'SOURCE_EMPTY'), 'source_batch_id')
    copy_raw(cur,batch,table,rows)
    return batch, True, bool(prior)


def stored(cur, table, partition):
    condition = extraction_condition(table,partition)
    cur.execute('SELECT source_batch_id FROM raw.source_batch WHERE source_table=%s '
                'AND extraction_condition=%s ORDER BY source_batch_id', (table, Json(condition)))
    batches = cur.fetchall()
    if len(batches) != 1:
        raise RuntimeError('BLOCKING: absent/ambiguous raw partition '+table+' '+partition)
    cur.execute('SELECT source_record_id,raw_payload FROM raw.source_record '
                'WHERE source_batch_id=%s ORDER BY source_position', batches[0])
    return [(i,r) for i,r in cur.fetchall()]


def initialize_players(cur, ki, first_entries):
    by_player = defaultdict(list)
    ids = {}
    for raw_id, r in ki:
        if key('brd_ki',r) in ids:
            raise RuntimeError('BLOCKING: duplicate KI natural key')
        by_player[r['toroku_bango']].append(r)
        ids[key('brd_ki',r)] = raw_id
    rows, sexes = [], {}
    for player, (first_year, raw_id, entry) in sorted(first_entries.items()):
        attr = identity_observation(by_player[player], first_year)
        eligible = [r for r in by_player[player] if r['kaisai_nen'] < first_year]
        known = {normalize_sex(r['seibetsu_code'])[0] for r in eligible} - {None}
        if len(known) > 1:
            attr = None  # Retain all KI raw; no choice between conflicting sexes.
        sex, status = normalize_sex(attr['seibetsu_code'] if attr else None)
        if len(known) > 1:
            status = 'UNRESOLVED'
        attr_id = ids[key('brd_ki',attr)] if attr else None
        player_id = integer(player,1)
        if player_id is None:
            continue
        sexes[player_id] = sex
        rows.append(dict(player_id=player_id,
            player_name_raw=attr['shimei_kanji'] if attr else entry['shimei'],
            sex_raw=attr['seibetsu_code'] if attr else None, sex=sex,
            sex_normalization_status=status, training_class_raw=attr['yosei_ki'] if attr else None,
            training_class=integer(attr['yosei_ki'],1) if attr else None,
            source_record_id=attr_id or raw_id, sex_source_record_id=attr_id,
            provenance={'normalization_version':NORMALIZATION_VERSION, 'identity_only':True,
                'historical_availability':'UNKNOWN', 'selection_version':VERSION,
                'earliest_race_year':first_year, 'eligible_sex_conflict':len(known)>1}))
    fields = [f for f in rows[0] if f != 'player_id'] if rows else []
    bulk(cur, 'core.player', rows, 'ON CONFLICT (player_id) DO UPDATE SET '+
         ','.join(f+'=EXCLUDED.'+f for f in fields))
    return sexes


def first_player_entries(cur):
    """Aggregate on PostgreSQL; return only one earliest source row per player."""
    cur.execute('''WITH picked AS MATERIALIZED (
        SELECT DISTINCT ON (s.raw_payload->>'toroku_bango')
            s.source_record_id,s.raw_payload->>'toroku_bango' AS player,
            s.raw_payload->>'kaisai_nen' AS first_year
        FROM raw.source_record s JOIN raw.source_batch b USING(source_batch_id)
        WHERE b.source_table='brd_l3' AND b.extraction_condition->>'version'=%s
          AND b.extraction_condition->>'partition'>='2017-01'
        ORDER BY s.raw_payload->>'toroku_bango',s.raw_payload->>'kaisai_nen',
            s.raw_payload->>'kaisai_tsukihi',s.raw_payload->>'kyoteijo_code',
            s.raw_payload->>'race_no',s.raw_payload->>'teiban',s.source_record_id
        ) SELECT p.player,p.first_year,s.source_record_id,s.raw_payload
        FROM picked p JOIN raw.source_record s USING(source_record_id) ORDER BY p.player''',(VERSION,))
    return {p:(y,i,r) for p,y,i,r in cur.fetchall()}


def canonical_month(cur, partition, sexes):
    month_start=date.fromisoformat(partition+'-01')
    if month_start<date(2017,1,1):
        raise ValueError('history scope starts 2017-01-01')
    month_end=(month_start.replace(day=28)+timedelta(days=4)).replace(day=1)
    sources = {t:stored(cur,t,partition) for t in TABLES if t != 'brd_ki'}
    maps = {t:{key(t,r):(i,r) for i,r in rows} for t,rows in sources.items()}
    for table, rows in sources.items():
        if len(maps[table]) != len(rows):
            raise RuntimeError('BLOCKING: duplicate source natural key '+table)
    # Phase 2 evidence may be reused only if its complete payload is identical.
    # Raw revisions are not a policy for silently replacing adopted records.
    for canonical, source_table, join in (
        ('race','brd_l2','JOIN core.race r ON r.race_id=c.race_id'),
        ('race_entry','brd_l3','JOIN core.race r ON r.race_id=c.race_id'),
        ('race_result','brd_k3','JOIN core.race r ON r.race_id=c.race_id')):
        cur.execute('SELECT s.raw_payload,s.record_hash FROM core.'+canonical+' c '+join+
                    " JOIN raw.source_record s ON s.source_record_id=c.source_record_id "
                    "WHERE r.race_date >= %s AND r.race_date < %s",(month_start,month_end))
        for payload,hash_value in cur.fetchall():
            new=maps[source_table].get(key(source_table,payload))
            if new is None or digest(new[1])!=hash_value:
                raise RuntimeError('BLOCKING: existing canonical source revision '+canonical)
    cur.execute('''SELECT s.raw_payload,s.record_hash FROM core.race c
        JOIN raw.source_record s ON s.source_record_id=c.grade_source_record_id
        WHERE c.race_date >= %s AND c.race_date < %s''',(month_start,month_end))
    for payload,hash_value in cur.fetchall():
        new=maps['brd_l1'].get(key('brd_l1',payload))
        if new is None or digest(new[1])!=hash_value:
            raise RuntimeError('BLOCKING: existing canonical source revision race_grade')
    groups = defaultdict(list)
    issues = defaultdict(int)
    examples = {}
    def issue(name, raw_id):
        issues[name] += 1
        examples.setdefault(name, raw_id)
    for i,r in sources['brd_l3']:
        groups[key('brd_l3',r)[:4]].append((i,r))
    races, entrants, results, motors, motor_dates = [], [], [], {}, {}
    for rk,(raw_id,r) in sorted(maps['brd_l2'].items()):
        try:
            day = race_date(r)
        except (ValueError,TypeError):
            issue('INVALID_RACE_DATE',raw_id); continue
        venue, number = integer(r['kyoteijo_code'],1,24), integer(r['race_no'],1,12)
        if venue is None or number is None:
            issue('INVALID_RACE_KEY',raw_id); continue
        es = groups.get(rk,[])
        valid = [(i,e) for i,e in es if integer(e['teiban'],1,6) is not None
                 and integer(e['toroku_bango'],1) in sexes]
        women,status = women_only([sexes[int(e['toroku_bango'])] for _,e in valid],
                                  [int(e['teiban']) for _,e in valid])
        gi,grade = maps['brd_l1'].get(rk[:3],(None,None))
        fixed = source_boolean(r['shinnyukotei'])
        races.append(dict(race_date=day, venue_code=venue, race_no=number,
            grade_raw=grade['grade_code'] if grade else None,
            grade=normalize_grade(grade['grade_code']) if grade else None,
            women_only_derived=women, women_only_status=status,
            women_only_basis={'rule':'ENTRANT_PLAYER_SEX_V1', 'boats':[int(e['teiban']) for _,e in valid],
                'player_ids':[int(e['toroku_bango']) for _,e in valid]},
            entry_fixed_source=fixed, entry_fixed_effective=True if venue==3 else fixed,
            entry_fixed_basis='EDOGAWA_MODEL_RULE' if venue==3 else 'SOURCE_L2',
            stabilizer_source=source_boolean(r['anteiban_shiyo']), stabilizer_available_for_prediction=None,
            race_status='RESULT_RECORDS_PRESENT' if len(valid)==6 and all(key('brd_l3',e) in maps['brd_k3'] for _,e in valid)
                        else 'SOURCE_INCOMPLETE', source_record_id=raw_id, grade_source_record_id=gi,
            provenance={'normalization_version':NORMALIZATION_VERSION,
                'stabilizer_prediction_availability':'UNKNOWN; extraction is retrospective'}))
        for ei,e in es:
            if (ei,e) not in valid:
                issue('INVALID_ENTRY_REQUIRED_FIELD',ei); continue
            motor = integer(e['motor_no'],1)
            mk = None
            if motor is not None:
                year,start,end = motor_generation(venue,day)
                mk=(venue,year,motor)
                motor_dates.setdefault(mk,day.strftime('%Y%m%d'))
                motors.setdefault(mk,dict(venue_code=venue,generation_start_year=year,
                    generation_start_date=start,generation_end_date=end,motor_no=motor,
                    identity_rule_version=MOTOR_RULE_VERSION,source_record_id=ei,
                    provenance={'number_field':'motor_no','generation_basis':'USER_DEFINED_RULE'}))
            entrants.append((day,venue,number,ei,e,mk))
    # Every omission remains addressable in immutable raw; no invented parent race.
    for i,r in sources['brd_l3']:
        if key('brd_l3',r)[:4] not in maps['brd_l2']:
            issue('L3_WITHOUT_L2',i)
    bulk(cur,'core.race',races, 'ON CONFLICT (race_date,venue_code,race_no) DO UPDATE SET '+
         ','.join(f+'=EXCLUDED.'+f for f in ('women_only_derived','women_only_status','women_only_basis')))
    # Canonical motor evidence must never point later than its earliest race.
    bulk(cur,'core.motor',list(motors.values()), 'ON CONFLICT (venue_code,generation_start_year,motor_no) DO NOTHING')
    cur.execute('SELECT motor_id,venue_code,generation_start_year,motor_no,source_record_id FROM core.motor')
    motor_rows=cur.fetchall()
    motor_ids = {(v,y,n):i for i,v,y,n,_ in motor_rows}
    old_refs = {(v,y,n):s for _,v,y,n,s in motor_rows}
    candidates=[mk for mk,m in motors.items() if old_refs[mk]!=m['source_record_id']]
    if candidates:
        cur.execute("SELECT source_record_id,(raw_payload->>'kaisai_nen')||(raw_payload->>'kaisai_tsukihi') "
                    "FROM raw.source_record WHERE source_record_id=ANY(%s)",
                    (sorted({old_refs[mk] for mk in candidates}),))
        old_dates=dict(cur.fetchall())
        updates=[(motors[mk]['source_record_id'],motor_ids[mk]) for mk in candidates
                 if old_dates[old_refs[mk]]>motor_dates[mk]]
        if updates:
            cur.executemany('UPDATE core.motor SET source_record_id=%s WHERE motor_id=%s',updates)
    cur.execute("SELECT race_id,race_date,venue_code,race_no FROM core.race WHERE race_date >= %s AND race_date < %s",(month_start,month_end))
    race_ids = {(d,v,n):i for i,d,v,n in cur.fetchall()}
    entry_rows = []
    adopted = set()
    for day,venue,number,ei,e,mk in entrants:
        race_id=race_ids[(day,venue,number)]
        ek=key('brd_l3',e)
        entry_rows.append(dict(race_id=race_id,boat_no=int(e['teiban']),venue_code=venue,
            player_id=int(e['toroku_bango']),motor_id=motor_ids[mk] if mk else None,
            motor_no_raw=e['motor_no'],f_count_current_term_raw=e['f_kaisu'],
            f_count_current_term=integer(e['f_kaisu']),l_count_current_term_raw=e['l_kaisu'],
            source_record_id=ei,provenance={'boat_field':'teiban',
                'boat_no_source_field':'hull number, not lane','f_suspension_state':'NOT_CALCULATED'}))
        if ek not in maps['brd_k3']:
            issue('ENTRY_WITHOUT_RESULT',ei); continue
        ri,r=maps['brd_k3'][ek]
        adopted.add(ek)
        if e['toroku_bango'] != r['toroku_bango']:
            issue('REGISTRATION_CONFLICT',ri); continue
        try:
            normalized = normalize_result(r)
        except ValueError:
            issue('RESULT_CODE_CONFLICT',ri); continue
        results.append(dict(race_id=race_id,boat_no=int(e['teiban']),**normalized,
            source_record_id=ri,provenance={'source':'brd_k3',
                'normalization_version':normalized['normalization_version'],
                'actual_course_field':'shinnyu_course','start_timing_field':'st'}))
    for ek,(i,r) in maps['brd_k3'].items():
        if ek not in adopted:
            issue('K3_WITHOUT_VALID_ENTRY',i)
    bulk(cur,'core.race_entry',entry_rows,'ON CONFLICT (race_id,boat_no) DO NOTHING')
    bulk(cur,'core.race_result',results,'ON CONFLICT (race_id,boat_no) DO NOTHING')
    cur.execute('''UPDATE core.race r SET race_status=CASE WHEN
        (SELECT count(*) FROM core.race_entry e WHERE e.race_id=r.race_id)=6 AND
        (SELECT count(*) FROM core.race_result z WHERE z.race_id=r.race_id)=6
        THEN 'RESULT_RECORDS_PRESENT' ELSE 'SOURCE_INCOMPLETE' END
        WHERE r.race_date >= %s AND r.race_date < %s''',(month_start,month_end))
    return {'issues':dict(issues),'example_raw_ids':examples,
            'eligible_rows':{'race':len(races),'entry':len(entry_rows),'result':len(results)}}


def run(raw_only=False, canonical_only=False, inventory_path=None):
    source = None if canonical_only else source_connection()
    target = target_connection()
    report={'version':VERSION,'scope_start':'2017-01-01','status':'RUNNING','raw':{},'canonical':{}}
    try:
        with target.cursor() as cur:
            cur.execute("SELECT pg_try_advisory_lock(hashtext(%s))",(VERSION,))
            if not cur.fetchone()[0]:
                raise RuntimeError('history import already running')
            cur.execute("SET statement_timeout='0'")
        target.commit()
        if source is not None:
            with source.cursor() as cur:
                cur.execute("SET statement_timeout='0'")
        if canonical_only:
            if inventory_path is None:
                raise ValueError('canonical-only requires successful raw report')
            prior=json.loads(Path(inventory_path).read_text(encoding='utf-8'))
            if prior.get('status') not in ('RAW_COMPLETE','CANONICAL_COMPLETE') or prior.get('scope_start')!='2017-01-01':
                raise RuntimeError('BLOCKING: raw acquisition did not complete')
            report['source_inventory']=prior['source_inventory']
            with target.cursor() as cur:
                cur.execute("SELECT source_table,extraction_condition->>'partition',row_count FROM raw.source_batch "
                            "WHERE extraction_condition->>'version'=%s AND "
                            "((source_table <> 'brd_ki' AND extraction_condition->>'partition'>='2017-01') "
                            "OR (source_table='brd_ki' AND extraction_condition->>'partition'>='2017'))",(VERSION,))
                partitions=cur.fetchall()
            months=sorted({m for t,v in report['source_inventory'].items() if t!='brd_ki' for m in v['partitions']})
            years=sorted({r[0] for r in report['source_inventory']['brd_ki']['terms']})+[IDENTITY_SUPPORT]
            expected={(t,p) for t in TABLES for p in (years if t=='brd_ki' else months)}
            if len(partitions)!=len(expected) or {(t,p) for t,p,_ in partitions}!=expected:
                raise RuntimeError('BLOCKING: incomplete/ambiguous raw acquisition')
            for t in TABLES:
                if sum(n for table,_,n in partitions if table==t)!=report['source_inventory'][t]['rows']:
                    raise RuntimeError('BLOCKING: raw acquisition count mismatch')
            report['source_inventory_basis']='preserved raw partition set; no live source adoption'
        else:
            report['source_inventory']=inventory(source)
            months=sorted({m for t,v in report['source_inventory'].items() if t!='brd_ki' for m in v['partitions']})
            years=sorted({r[0] for r in report['source_inventory']['brd_ki']['terms']})+[IDENTITY_SUPPORT]
            print(json.dumps({'stage':'inventory','rows':{t:v['rows'] for t,v in report['source_inventory'].items()}}),flush=True)
        for table in TABLES:
            if canonical_only:
                continue
            counts={'inserted_batches':0,'reused_batches':0,'rows':0}
            for part in years if table=='brd_ki' else months:
                # Failed SELECT never becomes SOURCE_EMPTY or a successful batch.
                try:
                    rows=extract(source,table,part)
                except Exception:
                    print(json.dumps({'stage':'source_fetch','status':'SOURCE_FETCH_FAILED',
                        'table':table,'partition':part}),flush=True)
                    raise
                with target.cursor() as cur:
                    batch,new,conflict=preserve(cur,table,part,rows,datetime.now(timezone.utc))
                target.commit()
                counts['inserted_batches' if new else 'reused_batches']+=1
                counts['rows']+=len(rows)
                if conflict:
                    raise RuntimeError('BLOCKING: changed source partition preserved; revision adoption requires decision')
                print(json.dumps({'stage':'raw','table':table,'partition':part,'rows':len(rows),'new':new}),flush=True)
            report['raw'][table]=counts
            if counts['rows']!=report['source_inventory'][table]['rows']:
                raise RuntimeError('BLOCKING: partition extraction does not cover inventory')
        if source is not None:
            source.rollback();source.close();source=None
        if not raw_only:
            with target.cursor() as cur:
                bulk(cur,'core.venue',[dict(venue_code=i,venue_name=n) for i,n in enumerate(VENUES,1)],
                     'ON CONFLICT (venue_code) DO NOTHING')
                ki=[r for y in years for r in stored(cur,'brd_ki',y)]
                first=first_player_entries(cur)
                sexes=initialize_players(cur,ki,first)
            target.commit()
            for month in months:
                with target.cursor() as cur:
                    report['canonical'][month]=canonical_month(cur,month,sexes)
                target.commit()
                print(json.dumps({'stage':'canonical','partition':month,**report['canonical'][month]}),flush=True)
            with target.cursor() as cur:
                report['result_dataset_version'] = record_k3_result_dataset_version(
                    cur, date_start=date.fromisoformat(report['scope_start']),
                    date_end=date.fromisoformat(report['source_inventory']['brd_k3']['latest']),
                    extraction_version=VERSION)
            target.commit()
        report['status']='RAW_COMPLETE' if raw_only else 'CANONICAL_COMPLETE'
        return report
    except Exception:
        target.rollback()
        raise
    finally:
        if source is not None:
            source.rollback();source.close()
        target.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw-only',action='store_true')
    parser.add_argument('--canonical-only',action='store_true')
    parser.add_argument('--inventory',type=Path,help='successful raw report required for canonical-only')
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args()
    try:
        if args.raw_only and args.canonical_only:
            parser.error('choose one stage')
        result=run(args.raw_only,args.canonical_only,args.inventory)
    except Exception as exc:
        args.report.write_text(json.dumps({'status':'FAILED','exception_type':type(exc).__name__,
            'meaning':'not SOURCE_EMPTY; committed raw partitions remain preserved'},indent=2),encoding='utf-8')
        raise
    args.report.write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
