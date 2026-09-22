"""Reproducible empty-DB verification; removes only its own disposable database."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
from scripts.db import target_connection
from scripts.foundation import canonical_json, digest
from scripts.import_history import (preserve, VERSION, initialize_players, canonical_month,
    stored, bulk, first_player_entries)
from scripts.history_source import IDENTITY_SUPPORT
from scripts.import_sample import import_sample, extract_source
from scripts.verify_import import disposable_database
from scripts.freeze_history import freeze_month, snapshot_month
from scripts.audit_history import audit


def sample_tests():
    os.environ['BOATRACE_TEST_DB']='1'
    with disposable_database() as connect:
        with patch('scripts.import_sample.target_connection',connect):
            import_sample()
        suite=unittest.defaultTestLoader.discover(str(Path(__file__).resolve().parents[1]/'tests'))
        with patch('test_database.target_connection',connect), patch('test_national_win_rate.target_connection',connect):
            result=unittest.TextTestRunner(verbosity=2).run(suite)
        if not result.wasSuccessful() or result.skipped:
            raise RuntimeError('test failure or skip')
    with disposable_database() as connect:
        bounded_pipeline(connect)
    return {'tests':result.testsRun,'failures':0,'skips':0,'empty_sample_database_removed':True,
            'bounded_real_source_pipeline_and_idempotency':'PASS'}


def bounded_pipeline(connect):
    records,_,_,_=extract_source()
    months=sorted({r['kaisai_nen']+'-'+r['kaisai_tsukihi'][:2] for r in records['brd_l2']})
    conn=connect()
    try:
        with conn.cursor() as cur:
            from scripts.foundation import VENUES
            bulk(cur,'core.venue',[dict(venue_code=i,venue_name=n) for i,n in enumerate(VENUES,1)],
                 'ON CONFLICT (venue_code) DO NOTHING')
            for table,rows in records.items():
                parts=sorted({r['kaisai_nen'] for r in rows}) if table=='brd_ki' else months
                for part in parts:
                    subset=[r for r in rows if (r['kaisai_nen'] if table=='brd_ki'
                        else r['kaisai_nen']+'-'+r['kaisai_tsukihi'][:2])==part]
                    batch,_,_=preserve(cur,table,part,subset,datetime.now(timezone.utc))
                    if preserve(cur,table,part,subset,datetime.now(timezone.utc))!=(batch,False,False):
                        raise RuntimeError('bounded raw idempotency failed')
            ki=[r for year in sorted({r['kaisai_nen'] for r in records['brd_ki']}) for r in stored(cur,'brd_ki',year)]
            first={}
            for month in months:
                for i,r in stored(cur,'brd_l3',month):
                    first.setdefault(r['toroku_bango'],(r['kaisai_nen'],i,r))
            sexes=initialize_players(cur,ki,first)
            if first_player_entries(cur)!=first:
                raise RuntimeError('SQL earliest-player selection differs from source-order selection')
            for month in months:
                first_run=canonical_month(cur,month,sexes)
                if canonical_month(cur,month,sexes)!=first_run:
                    raise RuntimeError('bounded canonical idempotency failed')
            for month in months:
                first_run=freeze_month(cur,month)
                second_run=freeze_month(cur,month)
                if second_run['new'] or first_run['logical_hash']!=second_run['logical_hash']:
                    raise RuntimeError('bounded frozen dataset idempotency failed')
            cur.execute('SELECT count(*) FROM core.dataset_version WHERE selection_rule_version=%s '
                        'AND date_end<>effective_date-1',(VERSION,))
            if cur.fetchone()[0]:
                raise RuntimeError('partial month cutoff must follow last observed day')
        conn.commit()
    finally:
        conn.rollback();conn.close()


def raw_hashes(connection):
    """Bounded-memory independent verification of every raw row/batch hash."""
    connection.commit()
    connection.set_session(readonly=True,isolation_level='REPEATABLE READ')
    with connection.cursor() as cur:
        cur.execute("SET statement_timeout='0'")
    total=0
    codes=defaultdict(Counter)
    shapes=defaultdict(Counter)
    with connection.cursor() as cur:
        cur.execute("SELECT source_batch_id,row_count,content_hash,source_table FROM raw.source_batch "
                    "WHERE extraction_condition->>'version' IS NULL OR "
                    "(extraction_condition->>'version'=%s AND extraction_condition->>'partition'>='2017') "
                    "ORDER BY source_batch_id",(VERSION,))
        batches=cur.fetchall()
    for batch,count,expected,table in batches:
        hasher=hashlib.sha256(b'[')
        observed=0
        with connection.cursor(name='hash_'+str(batch)) as cur:
            cur.itersize=1000
            cur.execute('SELECT raw_payload,record_hash,source_position FROM raw.source_record '
                        'WHERE source_batch_id=%s ORDER BY source_position',(batch,))
            for payload,row_hash,position in cur:
                encoded=canonical_json(payload).encode('utf-8')
                if hashlib.sha256(encoded).hexdigest()!=row_hash or position!=observed+1:
                    raise RuntimeError('raw row hash/position mismatch')
                if observed:
                    hasher.update(b',')
                hasher.update(encoded)
                observed+=1
                codes[table][str(payload.get('record_id'))]+=1
                shapes[table][tuple(sorted(payload))]+=1
        hasher.update(b']')
        if observed!=count or hasher.hexdigest()!=expected:
            raise RuntimeError('raw batch hash/count mismatch')
        total+=observed
        print(json.dumps({'stage':'raw_hash','batch':batch,'rows':observed}),flush=True)
    return {'batches':len(batches),'rows':total,'hashes':'PASS',
        'source_record_codes':{t:dict(c) for t,c in codes.items()},
        'source_column_shapes':{t:[{'columns':list(k),'rows':n} for k,n in c.items()] for t,c in shapes.items()}}


def dataset_hashes(connection):
    connection.commit()
    connection.set_session(readonly=True,isolation_level='REPEATABLE READ')
    datasets=[]
    with connection.cursor() as cur:
        cur.execute('SELECT dataset_version_id FROM core.dataset_version ORDER BY dataset_version_id')
        dataset_ids=[r[0] for r in cur.fetchall()]
        for identifier in dataset_ids:
            cur.execute('SELECT canonical_snapshot,canonical_content_hash,source_manifest,manifest_hash,effective_date '
                        'FROM core.dataset_version WHERE dataset_version_id=%s',(identifier,))
            snapshot,content,manifest,manifest_hash,effective=cur.fetchone()
            if digest(snapshot)!=content or digest(manifest)!=manifest_hash:
                raise RuntimeError('stored dataset content/manifest hash mismatch')
            if any(r['race_date']>=effective.isoformat() for r in snapshot['race']):
                raise RuntimeError('stored dataset D-1 violation')
            datasets.append(identifier)
            print(json.dumps({'stage':'dataset_hash','dataset_id':identifier}),flush=True)
    return {'dataset_hashes_verified':datasets,'hashes':'PASS'}


def replay(inventory_path):
    report=json.loads(Path(inventory_path).read_text(encoding='utf-8'))
    inv=report['source_inventory']
    months=sorted({m for t,v in inv.items() if t!='brd_ki' for m in v['partitions']})
    years=sorted({r[0] for r in inv['brd_ki']['terms']})+[IDENTITY_SUPPORT]
    real=target_connection()
    real.commit()
    with real.cursor() as cur:
        cur.execute("SET TRANSACTION READ ONLY")
    out={'raw_replay':{},'canonical_replay':[]}
    try:
        with disposable_database() as connect:
            scratch=connect()
            try:
                with scratch.cursor() as cur:
                    cur.execute("SET statement_timeout='0'")
                for table in ('brd_l1','brd_l2','brd_l3','brd_r3','brd_ki'):
                    rows_count=0
                    for partition in years if table=='brd_ki' else months:
                        with real.cursor() as cur:
                            raw=stored(cur,table,partition)
                        rows=[r for _,r in raw]
                        with scratch.cursor() as cur:
                            batch,new,conflict=preserve(cur,table,partition,rows,datetime.now(timezone.utc))
                            if not new or conflict:
                                raise RuntimeError('unexpected empty-DB raw replay state')
                            again=preserve(cur,table,partition,rows,datetime.now(timezone.utc))
                            if again!=(batch,False,False):
                                raise RuntimeError('raw idempotency failure')
                        scratch.commit()
                        rows_count+=len(rows)
                        print(json.dumps({'stage':'replay_raw','table':table,'partition':partition}),flush=True)
                    out['raw_replay'][table]=rows_count
                from scripts.foundation import VENUES
                with scratch.cursor() as cur:
                    bulk(cur,'core.venue',[dict(venue_code=i,venue_name=n) for i,n in enumerate(VENUES,1)])
                    ki=[r for y in years for r in stored(cur,'brd_ki',y)]
                    first=first_player_entries(cur)
                    sexes=initialize_players(cur,ki,first)
                scratch.commit()
                for month in months:
                    with scratch.cursor() as cur:
                        first_run=canonical_month(cur,month,sexes)
                        first_hash=digest(snapshot_month(cur,month))
                        second_run=canonical_month(cur,month,sexes)
                        if first_run!=second_run or first_hash!=digest(snapshot_month(cur,month)):
                            raise RuntimeError('canonical replay content/count/issues mismatch')
                    scratch.commit()
                    print(json.dumps({'stage':'replay_canonical','partition':month}),flush=True)
                # Read only after replay has populated its canonical foundation;
                # the original task may freeze its immutable shards in parallel.
                with real.cursor() as cur:
                    cur.execute("SELECT dataset_name,source_manifest->>'logical_content_hash' FROM core.dataset_version "
                                "WHERE selection_rule_version=%s",(VERSION,))
                    expected=dict(cur.fetchall())
                if len(expected)!=len(months):
                    raise RuntimeError('source history shards must all be frozen before comparison')
                for month in months:
                    with scratch.cursor() as cur:
                        frozen=freeze_month(cur,month)
                        repeated=freeze_month(cur,month)
                        if repeated['new'] or repeated['logical_hash']!=frozen['logical_hash']:
                            raise RuntimeError('dataset idempotency failure')
                        if expected.get(VERSION+'-'+month)!=frozen['logical_hash']:
                            raise RuntimeError('portable dataset mismatch '+month)
                    scratch.commit()
                    out['canonical_replay'].append(frozen)
                    print(json.dumps({'stage':'replay_dataset','partition':month,'equal':True}),flush=True)
                scratch.commit()
                out['audit']=audit(scratch)
                if out['audit']['status']!='PASS':
                    raise RuntimeError('replay audit blocking')
                out['status']='PASS'
            finally:
                scratch.rollback();scratch.close()
        out['temporary_database_removed']=True
        return out
    finally:
        real.rollback();real.close()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',choices=['sample-tests','hashes','datasets','replay'],required=True)
    parser.add_argument('--inventory',type=Path)
    parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args()
    if args.mode=='sample-tests':
        result=sample_tests()
    elif args.mode=='replay':
        result=replay(args.inventory)
    else:
        conn=target_connection()
        try:
            result=dataset_hashes(conn) if args.mode=='datasets' else raw_hashes(conn)
        finally:
            conn.rollback();conn.close()
    args.report.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
