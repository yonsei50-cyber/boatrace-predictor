"""Explicit nine-race sample import. The source connection executes SELECT only."""
import argparse
from datetime import date, timedelta
import json
from pathlib import Path
from psycopg2 import sql
from psycopg2.extras import Json, RealDictCursor
from scripts.db import DEFAULT_CONFIG, source_connection, target_connection
from scripts.foundation import (SAMPLE_RACES, VENUES, NORMALIZATION_VERSION,
    MOTOR_RULE_VERSION, SELECTION_VERSION, canonical_json, digest, integer,
    motor_generation, women_only, identity_observation)
from scripts.normalize import normalize_result, normalize_sex, normalize_grade, source_boolean

RACE_KEY = ('kaisai_nen','kaisai_tsukihi','kyoteijo_code','race_no')
KEYS = {'brd_l1': RACE_KEY[:3], 'brd_l2': RACE_KEY,
        'brd_l3': RACE_KEY + ('teiban',), 'brd_r3': RACE_KEY + ('teiban',),
        'brd_ki': ('toroku_bango','kaisai_nen','ki')}

def key(table, row):
    return tuple(row[k] for k in KEYS[table])

def race_date(row):
    return date.fromisoformat(row['kaisai_nen'] + '-' + row['kaisai_tsukihi'][:2] + '-' + row['kaisai_tsukihi'][2:])

def extract_source(config=DEFAULT_CONFIG):
    conn = source_connection(config)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute("SELECT clock_timestamp() AS extracted_at,current_setting('transaction_read_only') AS read_only")
            session = dict(cur.fetchone())
            records = {}
            conditions = {}
            for table in ('brd_l1','brd_l2','brd_l3','brd_r3'):
                fields = RACE_KEY[:3] if table == 'brd_l1' else RACE_KEY
                values = sorted(set(r[:len(fields)] for r in SAMPLE_RACES))
                query = sql.SQL('SELECT * FROM public.{} WHERE ({}) IN ({}) ORDER BY {}').format(
                    sql.Identifier(table), sql.SQL(',').join(map(sql.Identifier, fields)),
                    sql.SQL(',').join(sql.SQL('(') + sql.SQL(',').join(sql.Placeholder() for _ in fields) + sql.SQL(')') for _ in values),
                    sql.SQL(',').join(map(sql.Identifier, KEYS[table])))
                cur.execute(query, [x for row in values for x in row])
                records[table] = [dict(r) for r in cur.fetchall()]
                conditions[table] = {'fields': fields, 'tuples': values}
            # KI term applicability is not assumed. Only strictly earlier source years
            # supply stable identity attributes. This is not pre-race timestamp proof.
            pairs = sorted(set((r['toroku_bango'],r['kaisai_nen']) for r in records['brd_l3']))
            ki = {}
            choices = {}
            for player, year in pairs:
                cur.execute('''SELECT * FROM public.brd_ki WHERE toroku_bango=%s
                    AND kaisai_nen<%s ORDER BY kaisai_nen DESC,ki DESC LIMIT 1''', (player,year))
                row = cur.fetchone()
                if row is not None:
                    row = dict(row)
                    ki[key('brd_ki', row)] = row
                    choices[(player,year)] = key('brd_ki', row)
            records['brd_ki'] = [ki[k] for k in sorted(ki)]
            conditions['brd_ki'] = {'player_race_year_pairs':pairs,
                'rule':'latest (kaisai_nen,ki) strictly before race year; identity only'}
            cur.execute("SELECT current_setting('transaction_read_only') AS read_only")
            assert cur.fetchone()['read_only'] == session['read_only'] == 'on'
        return records, conditions, choices, session
    finally:
        conn.rollback()
        conn.close()

def insert(cur, table, values, returning=None):
    query = sql.SQL('INSERT INTO {}.{} ({}) VALUES ({})').format(
        *map(sql.Identifier, table.split('.')),
        sql.SQL(',').join(map(sql.Identifier, values)),
        sql.SQL(',').join(sql.Placeholder() for _ in values))
    if returning:
        query += sql.SQL(' RETURNING {}').format(sql.Identifier(returning))
    params = [Json(v, dumps=canonical_json) if isinstance(v,(dict,list)) else v for v in values.values()]
    cur.execute(query, params)
    return cur.fetchone()[0] if returning else None

def snapshot_before(cur, effective_date):
    """Freeze only results strictly earlier than D, with relevant dimensions."""
    statements = {
        'race': 'SELECT * FROM core.race WHERE race_date < %s ORDER BY race_id',
        # Keep the versioned Phase 2 result snapshot shape stable as entry inputs grow.
        'race_entry': '''SELECT e.race_id,e.boat_no,e.venue_code,e.player_id,e.motor_id,
            e.motor_no_raw,e.f_count_current_term_raw,e.f_count_current_term,
            e.l_count_current_term_raw,e.source_record_id,e.provenance
            FROM core.race_entry e JOIN core.race r USING(race_id)
            WHERE r.race_date < %s ORDER BY e.race_id,e.boat_no''',
        'race_result': '''SELECT e.* FROM core.race_result e JOIN core.race r USING(race_id)
            WHERE r.race_date < %s ORDER BY e.race_id,e.boat_no''',
        'player': '''SELECT p.* FROM core.player p WHERE EXISTS(SELECT 1 FROM core.race_entry e
            JOIN core.race r USING(race_id) WHERE e.player_id=p.player_id AND r.race_date<%s) ORDER BY player_id''',
        'motor': '''SELECT m.* FROM core.motor m WHERE EXISTS(SELECT 1 FROM core.race_entry e
            JOIN core.race r USING(race_id) WHERE e.motor_id=m.motor_id AND r.race_date<%s) ORDER BY motor_id''',
        'venue': '''SELECT v.* FROM core.venue v WHERE EXISTS(SELECT 1 FROM core.race r
            WHERE r.venue_code=v.venue_code AND r.race_date<%s) ORDER BY venue_code''',
    }
    snapshot = {}
    for table, query in statements.items():
        cur.execute(query, (effective_date,))
        names = [d.name for d in cur.description]
        snapshot[table] = [dict(zip(names,row)) for row in cur.fetchall()]
    return json.loads(canonical_json(snapshot))

def freeze_dataset(cur, effective_date):
    snapshot = snapshot_before(cur, effective_date)
    if not snapshot['race']:
        raise ValueError('empty fixed dataset')
    raw_ids = sorted({value for rows in snapshot.values() for row in rows for field,value in row.items()
                      if field.endswith('source_record_id') and value is not None})
    cur.execute('''SELECT source_record_id,source_batch_id,record_hash FROM raw.source_record
        WHERE source_record_id=ANY(%s) ORDER BY source_record_id''', (raw_ids,))
    manifest = {'records':[{'source_record_id':r,'source_batch_id':b,'record_hash':h} for r,b,h in cur.fetchall()],
                'rules':{'normalization':NORMALIZATION_VERSION,'motor':MOTOR_RULE_VERSION,
                         'selection':SELECTION_VERSION}, 'effective_date':effective_date.isoformat()}
    dates = [r['race_date'] for r in snapshot['race']]
    return insert(cur, 'core.dataset_version', dict(
        dataset_name='phase2-sample-' + effective_date.isoformat(),dataset_type='RETROSPECTIVE_RESULT_FOUNDATION',
        date_start=min(dates),date_end=max(dates),effective_date=effective_date,
        results_cutoff_date=effective_date-timedelta(days=1),source_manifest=manifest,
        normalization_version=NORMALIZATION_VERSION,selection_rule_version=SELECTION_VERSION,
        row_counts={k:len(v) for k,v in snapshot.items()},
        missing_excluded_summary={'coverage':'explicit sample only; not continuous history',
            'excluded_races_at_or_after_D':len(SAMPLE_RACES)-len(snapshot['race']),
            'historical_available_at':'UNKNOWN; current source DB extraction, no invented timestamps',
            'missing_sex':sum(p['sex'] is None for p in snapshot['player']),
            'unresolved_results':sum(r['normalization_status'] != 'NORMALIZED' for r in snapshot['race_result'])},
        canonical_snapshot=snapshot,canonical_content_hash=digest(snapshot),
        manifest_locator='inline:core.dataset_version.source_manifest',manifest_hash=digest(manifest),
        status='FROZEN_SAMPLE'), 'dataset_version_id')

def import_sample(config=DEFAULT_CONFIG):
    records, conditions, choices, session = extract_source(config)
    # Fail before writing if entry/result keys or player identities disagree.
    l2 = {key('brd_l2',r):r for r in records['brd_l2']}
    entries = {key('brd_l3',r):r for r in records['brd_l3']}
    results = {key('brd_r3',r):r for r in records['brd_r3']}
    if set(l2) != set(SAMPLE_RACES) or set(entries) != set(results):
        raise ValueError('BLOCKING: missing/conflicting source race/entry/result set')
    if len(entries) != len(SAMPLE_RACES)*6:
        raise ValueError('BLOCKING: sample must contain six source entries per race')
    for k, r in entries.items():
        if integer(r['teiban'],1,6) is None or r['toroku_bango'] != results[k]['toroku_bango']:
            raise ValueError('BLOCKING: invalid boat or conflicting registration')
    conn = target_connection(config)
    try:
        with conn.cursor() as cur:
            cur.execute('SELECT count(*) FROM raw.source_batch')
            if cur.fetchone()[0]:
                raise RuntimeError('BLOCKING: sample already imported; no overwrite')
            raw_ids = {}
            for table, rows in records.items():
                batch = insert(cur, 'raw.source_batch', dict(source_name='PC-KYOTEI',
                    source_type='SOURCE_DB_EXTRACT',source_locator='pckyotei.public.'+table,
                    extraction_condition=conditions[table],source_database='pckyotei',source_schema='public',
                    source_table=table,retrieved_at=None,extracted_at=session['extracted_at'],
                    content_hash=digest(rows),row_count=len(rows),
                    metadata={'transaction_read_only':session['read_only'],'source_year_is_not_retrieval_time':True},
                    status='PRESERVED'), 'source_batch_id')
                for position,row in enumerate(rows,1):
                    raw_ids[(table,key(table,row))] = insert(cur,'raw.source_record',dict(
                        source_batch_id=batch,source_record_key={k:row[k] for k in KEYS[table]},
                        source_race_id=None,source_position=position,raw_payload=row,record_hash=digest(row),
                        interpretation_status='PRESERVED'), 'source_record_id')
            for code,name in enumerate(VENUES,1):
                insert(cur,'core.venue',dict(venue_code=code,venue_name=name))
            player_sexes = {}
            by_player = {}
            for row in records['brd_ki']:
                by_player.setdefault(row['toroku_bango'],[]).append(row)
            for player in sorted({r['toroku_bango'] for r in entries.values()}):
                candidates = by_player.get(player,[])
                sexes = {normalize_sex(r['seibetsu_code'])[0] for r in candidates}
                if len(sexes) > 1:
                    raise ValueError('BLOCKING: conflicting source player sex')
                # Earliest selected observation avoids borrowing a later year's identity
                # for an older race in this sample.
                first_year = min(r['kaisai_nen'] for r in entries.values() if r['toroku_bango']==player)
                attr = identity_observation(candidates,first_year)
                entry = next(r for r in entries.values() if r['toroku_bango']==player)
                sex,status = normalize_sex(attr['seibetsu_code'] if attr else None)
                attr_id = raw_ids[('brd_ki',key('brd_ki',attr))] if attr else None
                player_id = integer(player,1)
                if player_id is None:
                    raise ValueError('invalid player registration')
                player_sexes[player_id] = sex
                insert(cur,'core.player',dict(player_id=player_id,
                    player_name_raw=attr['shimei_kanji'] if attr else entry['shimei'],
                    sex_raw=attr['seibetsu_code'] if attr else None,sex=sex,sex_normalization_status=status,
                    training_class_raw=attr['yosei_ki'] if attr else None,
                    training_class=integer(attr['yosei_ki'],1) if attr else None,
                    source_record_id=attr_id or raw_ids[('brd_l3',key('brd_l3',entry))],
                    sex_source_record_id=attr_id,provenance={'normalization_version':NORMALIZATION_VERSION,
                        'identity_only':True,'historical_availability':'UNKNOWN'}))
            motors = {}
            l1 = {key('brd_l1',r):r for r in records['brd_l1']}
            for rk in sorted(l2):
                row = l2[rk]
                day,venue = race_date(row),int(row['kyoteijo_code'])
                race_entries = [r for k,r in entries.items() if k[:4]==rk]
                women,status = women_only([player_sexes[int(r['toroku_bango'])] for r in race_entries],
                                         [int(r['teiban']) for r in race_entries])
                source_fixed = source_boolean(row['shinnyukotei'])
                grade = l1.get(rk[:3])
                race_id = insert(cur,'core.race',dict(race_date=day,venue_code=venue,race_no=int(row['race_no']),
                    grade_raw=grade['grade_code'] if grade else None,
                    grade=normalize_grade(grade['grade_code']) if grade else None,
                    women_only_derived=women,women_only_status=status,
                    women_only_basis={'rule':'ENTRANT_PLAYER_SEX_V1','boats':[int(r['teiban']) for r in race_entries],
                                      'player_ids':[int(r['toroku_bango']) for r in race_entries]},
                    entry_fixed_source=source_fixed,entry_fixed_effective=True if venue==3 else source_fixed,
                    entry_fixed_basis='EDOGAWA_MODEL_RULE' if venue==3 else 'SOURCE_L2',
                    stabilizer_source=source_boolean(row['anteiban_shiyo']),
                    stabilizer_available_for_prediction=None,race_status='RESULT_RECORDS_PRESENT',
                    source_record_id=raw_ids[('brd_l2',rk)],
                    grade_source_record_id=raw_ids[('brd_l1',rk[:3])] if grade else None,
                    provenance={'normalization_version':NORMALIZATION_VERSION,
                        'stabilizer_prediction_availability':'UNKNOWN; extraction is retrospective'}), 'race_id')
                for entry in race_entries:
                    ek = key('brd_l3',entry)
                    entry_id = raw_ids[('brd_l3',ek)]
                    motor_no = integer(entry['motor_no'],1)
                    motor_id = None
                    if motor_no is not None:
                        year,start,end = motor_generation(venue,day)
                        mk = (venue,year,motor_no)
                        if mk not in motors:
                            motors[mk] = insert(cur,'core.motor',dict(venue_code=venue,
                                generation_start_year=year,generation_start_date=start,generation_end_date=end,
                                motor_no=motor_no,identity_rule_version=MOTOR_RULE_VERSION,source_record_id=entry_id,
                                provenance={'number_field':'motor_no','generation_basis':'USER_DEFINED_RULE'}), 'motor_id')
                        motor_id=motors[mk]
                    insert(cur,'core.race_entry',dict(race_id=race_id,boat_no=int(entry['teiban']),venue_code=venue,
                        player_id=int(entry['toroku_bango']),motor_id=motor_id,motor_no_raw=entry['motor_no'],
                        f_count_current_term_raw=entry['f_kaisu'],f_count_current_term=integer(entry['f_kaisu']),
                        l_count_current_term_raw=entry['l_kaisu'],source_record_id=entry_id,
                        provenance={'boat_field':'teiban','boat_no_source_field':'hull number, not lane',
                                    'f_suspension_state':'NOT_CALCULATED'}))
                    result = normalize_result(results[ek])
                    insert(cur,'core.race_result',dict(race_id=race_id,boat_no=int(entry['teiban']),
                        **result,source_record_id=raw_ids[('brd_r3',ek)],
                        provenance={'normalization_version':NORMALIZATION_VERSION,
                                    'actual_course_field':'shinnyu_course','st_fields':['st','kigo']}))
            versions = [freeze_dataset(cur,date(2026,9,1)),freeze_dataset(cur,date(2026,9,2))]
        # A failed source check must leave the entire target sample uncommitted.
        again,_,_,after = extract_source(config)
        if digest(records) != digest(again) or after['read_only'] != 'on':
            raise RuntimeError('BLOCKING: sampled source changed across extraction; investigate')
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {'source_read_only':'on','source_sample_before_after_hash_equal':True,
            'source_hash':digest(records),'raw_counts':{t:len(r) for t,r in records.items()},
            'dataset_version_ids':versions}

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=DEFAULT_CONFIG)
    args=parser.parse_args()
    print(json.dumps(import_sample(args.config),indent=2))
