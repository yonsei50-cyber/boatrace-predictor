"""Immutable monthly retrospective shards; each has an explicit D-1 bound."""
import argparse
from datetime import date, timedelta
import json
from pathlib import Path
from scripts.db import target_connection
from scripts.foundation import canonical_json, digest, NORMALIZATION_VERSION, MOTOR_RULE_VERSION
from scripts.import_sample import insert
from scripts.import_history import VERSION


def month_bounds(partition):
    year,month=map(int,partition.split('-'))
    start=date(year,month,1)
    if start<date(2017,1,1):
        raise ValueError('history scope starts 2017-01-01')
    end=date(year+int(month==12),1 if month==12 else month+1,1)
    return start,end


def snapshot_month(cur, partition):
    start,end=month_bounds(partition)
    where='r.race_date >= %s AND r.race_date < %s'
    queries={
        'race':'SELECT r.* FROM core.race r WHERE '+where+' ORDER BY race_id',
        'race_entry':'SELECT e.* FROM core.race_entry e JOIN core.race r USING(race_id) WHERE '+where+' ORDER BY e.race_id,e.boat_no',
        'race_result':'SELECT e.* FROM core.race_result e JOIN core.race r USING(race_id) WHERE '+where+' ORDER BY e.race_id,e.boat_no',
        'player':'SELECT p.* FROM core.player p WHERE EXISTS (SELECT 1 FROM core.race_entry e JOIN core.race r USING(race_id) WHERE e.player_id=p.player_id AND '+where+') ORDER BY player_id',
        'motor':'SELECT m.* FROM core.motor m WHERE EXISTS (SELECT 1 FROM core.race_entry e JOIN core.race r USING(race_id) WHERE e.motor_id=m.motor_id AND '+where+') ORDER BY motor_id',
        'venue':'SELECT v.* FROM core.venue v WHERE EXISTS (SELECT 1 FROM core.race r WHERE r.venue_code=v.venue_code AND '+where+') ORDER BY venue_code'}
    snapshot={}
    for table,query in queries.items():
        cur.execute(query,(start,end))
        fields=[d.name for d in cur.description]
        snapshot[table]=[dict(zip(fields,row)) for row in cur.fetchall()]
    return json.loads(canonical_json(snapshot))


def logical_snapshot(snapshot, records):
    """Portable content: natural identities and raw hashes, not sequence values."""
    races={r['race_id']:[r['race_date'],r['venue_code'],r['race_no']] for r in snapshot['race']}
    motors={r['motor_id']:[r['venue_code'],r['generation_start_year'],r['motor_no']] for r in snapshot['motor']}
    result={}
    for table,rows in snapshot.items():
        canonical=[]
        for row in rows:
            r=dict(row)
            for field,value in list(r.items()):
                if field.endswith('source_record_id'):
                    r[field]=records[value]['record_hash'] if value is not None else None
                elif field=='race_id':
                    r[field]=races[value]
                elif field=='motor_id':
                    r[field]=motors[value] if value is not None else None
            canonical.append(r)
        result[table]=sorted(canonical,key=canonical_json)
    return result


def freeze_month(cur, partition):
    snapshot=snapshot_month(cur,partition)
    if not snapshot['race']:
        raise ValueError('no canonical races in partition')
    start,end=month_bounds(partition)
    # The latest month may be only partially acquired. Do not imply that its
    # remaining calendar days were observed or that a future cutoff is complete.
    end=date.fromisoformat(max(r['race_date'] for r in snapshot['race']))+timedelta(days=1)
    ids=sorted({v for rows in snapshot.values() for r in rows for k,v in r.items()
                if k.endswith('source_record_id') and v is not None})
    race_year={r['race_id']:r['race_date'][:4] for r in snapshot['race']}
    player_year={}
    for entry in snapshot['race_entry']:
        player=entry['player_id']
        year=race_year[entry['race_id']]
        player_year[player]=min(player_year.get(player,year),year)
    cur.execute("SELECT s.source_record_id,s.source_batch_id,s.record_hash,b.source_table,"
                "s.raw_payload->>'kaisai_nen',s.raw_payload->>'kaisai_tsukihi',s.raw_payload->>'toroku_bango' "
                'FROM raw.source_record s JOIN raw.source_batch b USING(source_batch_id) '
                'WHERE s.source_record_id=ANY(%s) ORDER BY s.source_record_id',(ids,))
    records={}
    for i,b,h,t,year,md,player in cur.fetchall():
        if t!='brd_ki':
            if year+md>=end.strftime('%Y%m%d'):
                raise RuntimeError('BLOCKING: future raw dimension/result in frozen shard')
        else:
            if year>=player_year[int(player)]:
                raise RuntimeError('BLOCKING: future KI in frozen shard')
        records[i]={'source_record_id':i,'source_batch_id':b,'record_hash':h}
    portable=digest(logical_snapshot(snapshot,records))
    manifest={'records':list(records.values()),'rules':{'normalization':NORMALIZATION_VERSION,
        'motor':MOTOR_RULE_VERSION,'selection':VERSION},'partition':partition,
        'effective_date':end.isoformat(),'logical_content_hash':portable}
    name=VERSION+'-'+partition
    content_hash,manifest_hash=digest(snapshot),digest(manifest)
    cur.execute('SELECT canonical_content_hash,manifest_hash FROM core.dataset_version WHERE dataset_name=%s',(name,))
    existing=cur.fetchall()
    if existing:
        if existing!=[(content_hash,manifest_hash)]:
            raise RuntimeError('BLOCKING: current canonical differs from frozen partition '+partition)
        return {'partition':partition,'logical_hash':portable,'new':False}
    insert(cur,'core.dataset_version',dict(dataset_name=name,dataset_type='RETROSPECTIVE_RESULT_FOUNDATION',
        date_start=min(r['race_date'] for r in snapshot['race']),date_end=max(r['race_date'] for r in snapshot['race']),
        effective_date=end,results_cutoff_date=end-timedelta(days=1),source_manifest=manifest,
        normalization_version=NORMALIZATION_VERSION,selection_rule_version=VERSION,
        row_counts={t:len(rows) for t,rows in snapshot.items()},
        missing_excluded_summary={'coverage':'one stored-history calendar month; compose shards for full history',
            'historical_available_at':'UNKNOWN; not a prediction-ready historical dataset',
            'D_rule':'all selected source race dates < effective_date; KI year strictly earlier',
            'unresolved_results':sum(r['normalization_status']=='UNRESOLVED' for r in snapshot['race_result'])},
        canonical_snapshot=snapshot,canonical_content_hash=content_hash,
        manifest_locator='inline:core.dataset_version.source_manifest',manifest_hash=manifest_hash,status='FROZEN_HISTORY_SHARD'))
    return {'partition':partition,'logical_hash':portable,'new':True}


def freeze(connect=target_connection):
    conn=connect()
    out=[]
    try:
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout='0'")
            cur.execute('SELECT pg_try_advisory_lock(hashtext(%s))',(VERSION,))
            if not cur.fetchone()[0]:
                raise RuntimeError('history mutation already running')
            cur.execute("SELECT DISTINCT to_char(race_date,'YYYY-MM') FROM core.race WHERE race_date >= '2017-01-01' ORDER BY 1")
            months=[r[0] for r in cur.fetchall()]
        for month in months:
            with conn.cursor() as cur:
                item=freeze_month(cur,month)
            conn.commit()
            out.append(item)
            print(json.dumps(item),flush=True)
        return out
    finally:
        conn.rollback();conn.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args()
    args.report.write_text(json.dumps(freeze(),indent=2),encoding='utf-8')
