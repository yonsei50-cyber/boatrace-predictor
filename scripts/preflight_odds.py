"""Read-only O6 and preserved CSV inventory; no canonical odds or timing guesses."""
import argparse
from collections import Counter, defaultdict
import csv
from datetime import date, timedelta
from decimal import Decimal
import hashlib
from itertools import permutations
import json
from pathlib import Path

from scripts.db import source_connection


def inventory(preserved):
    files = []
    csv_values = defaultdict(set)
    for item in json.loads((preserved / 'raw_file_manifest.json').read_text(encoding='utf-8-sig')):
        path = Path(item['Preserved'])
        content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        if content_hash.lower() != item['SHA256'].lower():
            raise RuntimeError('preserved CSV hash mismatch')
        with path.open(encoding='utf-8-sig', newline='') as f:
            rows = list(csv.DictReader(f))
        groups = defaultdict(set)
        for r in rows:
            if r['hiduke'] < '2017-01-01':
                continue
            key = (r['race_id'], r['bet_type'], r['combination'])
            groups[key].add(r['odds_5min'])
            csv_values[key].add(r['odds_5min'])
        files.append({'path': str(path), 'sha256': content_hash, 'rows': len(rows),
            'dates': sorted({r['hiduke'] for r in rows}), 'venues': sorted({r['kyoteijo_code'] for r in rows}),
            'race_ids': sorted({r['race_id'] for r in rows}), 'bet_types': sorted({r['bet_type'] for r in rows}),
            'distinct_keys': len(groups), 'duplicate_key_excess': len(rows)-len(groups),
            'conflicting_keys': sum(len(v)>1 for v in groups.values()),
            'retrieved_at': sorted({r['retrieved_at'] for r in rows}),
            'source_urls': sorted({r['source_url'] for r in rows}),
            'classification': 'LEGACY_AUXILIARY_OBSERVATION',
            'source_shimekiri': None, 'claimed_selector': 'slider=5',
            'classification_note': 'no source_shimekiri column; not merged into either primary dataset'})
    out = {'scope_start': '2017-01-01', 'csv_files': files,
        'csv_cross_file_conflicting_keys': sum(len(v)>1 for v in csv_values.values())}
    expected = [''.join(p) for p in permutations('123456', 3)]
    hashes, days = {}, set()
    venue = defaultdict(lambda: {'rows': 0, 'min_date': '99999999', 'max_date': '', 'days': set()})
    states, years, months, tokens, lengths = Counter(), Counter(), Counter(), Counter(), Counter()
    invalid_order = duplicate_rows = conflicting_rows = 0
    csv_comparison = []
    conn = source_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout='180s'")
            cur.execute('SHOW transaction_read_only')
            out['transaction_read_only'] = cur.fetchone()[0]
        with conn.cursor(name='odds_inventory') as cur:
            cur.itersize = 1000
            cur.execute("""SELECT kaisai_nen,kaisai_tsukihi,kyoteijo_code,race_no,
                record_id,data_kubun,odds_koshinjikan,odds_sanrentan
                FROM public.brd_o6 WHERE kaisai_nen >= '2017'""")
            for year, md, v, race, record, state, time, payload in cur:
                day = year + md
                key = day + v + race
                h = hashlib.sha256((payload or '').encode()).hexdigest()
                if key in hashes:
                    duplicate_rows += 1
                    conflicting_rows += hashes[key] != h
                hashes[key] = h
                days.add(day)
                stats = venue[v]
                stats['rows'] += 1
                stats['min_date'] = min(stats['min_date'], day)
                stats['max_date'] = max(stats['max_date'], day)
                stats['days'].add(day)
                states[(record, state, time)] += 1
                years[year] += 1
                months[year+'-'+md[:2]] += 1
                lengths[len(payload) if payload is not None else -1] += 1
                blocks = [(payload or '')[i:i+9] for i in range(0, len(payload or ''), 9)]
                if [b[:3] for b in blocks] != expected:
                    invalid_order += 1
                for b in blocks:
                    value = b[3:]
                    category = value if value in ('000000', '******', '099999') else (
                        'NUMERIC_OTHER' if len(value)==6 and value.isascii() and value.isdigit() else 'INVALID')
                    tokens[category] += 1
                    csv_key = (key, '3連単', '-'.join(b[:3]))
                    if csv_key in csv_values:
                        csv_comparison.append({'key': csv_key, 'o6_raw': value,
                            'o6_decimal': str(Decimal(value)/10) if value.isdigit() else None,
                            'csv_values': sorted(csv_values[csv_key]),
                            'interpretation': 'different timing/source; discrepancy is not same-snapshot conflict'})
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT kaisai_nen||kaisai_tsukihi||kyoteijo_code||race_no FROM public.brd_r3 WHERE kaisai_nen >= '2017'")
            result_keys = {r[0] for r in cur.fetchall()}
        missing = result_keys - hashes.keys()
        missing_by_day = Counter(k[:8] for k in missing)
        start, end = date.fromisoformat(min(days)), date.fromisoformat(max(days))
        calendar_missing = [(start+timedelta(days=i)).isoformat() for i in range((end-start).days+1)
                            if (start+timedelta(days=i)).strftime('%Y%m%d') not in days]
        out['o6'] = {'classification': 'FINAL_USER_CONFIRMED',
            'classification_evidence': 'user instruction: source_shimekiri=5 is five-minute; other odds are final',
            'source_defined_state': 'CLOSING_AT_CUTOFF', 'rows': sum(years.values()),
            'races': len(hashes), 'date_min': min(days), 'date_max': max(days), 'days': len(days),
            'venue_count': len(venue), 'venues': {v: {**s, 'days': len(s['days'])} for v,s in venue.items()},
            'years': dict(years), 'months': dict(months), 'states': [{'record_id': k[0],
                'data_kubun': k[1], 'odds_koshinjikan': k[2], 'rows': n} for k,n in states.items()],
            'length_distribution': dict(lengths), 'combination_order_invalid_rows': invalid_order,
            'odds_token_counts': dict(tokens), 'duplicate_race_rows': duplicate_rows,
            'conflicting_race_rows': conflicting_rows, 'calendar_missing_dates': calendar_missing,
            'r3_races': len(result_keys), 'r3_matched': len(result_keys & hashes.keys()),
            'r3_missing': len(missing), 'missing_by_day': dict(sorted(missing_by_day.items())),
            'missing_by_venue': dict(Counter(k[8:10] for k in missing)),
            'missing_before_o6_start': sum(k[:8]<min(days) for k in missing),
            'missing_within_o6_range': sum(min(days)<=k[:8]<=max(days) for k in missing),
            'retrieved_at': None, 'historical_snapshot_timestamp': None,
            'coverage_denominator': 'observed R3 keys, not proof of official scheduled races'}
        out['o6_vs_csv'] = csv_comparison
    finally:
        conn.rollback()
        conn.close()
    return out


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--preserved', type=Path, required=True)
    p.add_argument('--report', type=Path, required=True)
    args = p.parse_args()
    out = inventory(args.preserved)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k:v for k,v in out['o6'].items() if k in ('rows','races','date_min','date_max',
        'combination_order_invalid_rows','odds_token_counts','r3_missing')}, ensure_ascii=False))
