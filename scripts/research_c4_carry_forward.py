"""Read-only C4 exact-repeat diagnostics; raw strings only, no scale inference."""
from collections import Counter, defaultdict
from datetime import date, timedelta
import json

from scripts.db import source_connection

FIELDS = ('isshu', 'hanshu', 'mawariashi', 'chokusen')


def informative(values):
    return sum(isinstance(v, str) and len(v) == 4 and v.isascii()
               and v.isdigit() and v != '0000' for v in values) >= 4


def packet_is_informative(packet):
    return sum(informative(packet[i]) for i in range(4)) >= 2


def compare(a, b):
    return tuple(informative(a[i]) and a[i] == b[i] for i in range(4))


def run():
    conn = source_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout='300s'")
            cur.execute("""SELECT kaisai_nen||kaisai_tsukihi AS day,kyoteijo_code,
                race_no,count(*) AS boats,array_agg(teiban ORDER BY teiban) AS slots,
                array_agg(isshu ORDER BY teiban),array_agg(hanshu ORDER BY teiban),
                array_agg(mawariashi ORDER BY teiban),array_agg(chokusen ORDER BY teiban)
                FROM public.brd_c4 GROUP BY 1,2,3 ORDER BY 1,2,3""")
            rows = cur.fetchall()
        by_day = defaultdict(list)
        for day, venue, no, boats, slots, *packet in rows:
            by_day[(venue, day)].append((int(no), boats, slots, tuple(tuple(x) for x in packet)))
        bounds = {}
        for venue, day in by_day:
            first, last = bounds.get(venue, (day, day))
            bounds[venue] = (min(first, day), max(last, day))
        result = {'source_races': len(rows), 'days': len(by_day),
                  'adjacent_pairs': 0, 'eligible_pairs_by_field': Counter(),
                  'adjacent_pairs_by_observed_boundary': Counter(),
                  'full_packet_by_observed_boundary': Counter(),
                  'same_all_six_by_field': Counter(), 'same_by_venue_year_field': Counter(),
                  'same_field_count': Counter(), 'full_packet_same': 0,
                  'full_packet_by_venue_year': Counter(),
                  'full_packet_pairs': [],
                  'partial_field_repeat_pairs': 0,
                  'full_packet_permuted': 0, 'previous_calendar_day_full_packet': 0,
                  'previous_day_same_race_no': 0, 'examples': defaultdict(list),
                  'incomplete_races': []}
        for (venue, day), group in sorted(by_day.items()):
            for no, boats, slots, packet in group:
                if boats != 6 or slots != ['1','2','3','4','5','6']:
                    result['incomplete_races'].append((venue, day, no, boats, slots))
            for (no1, n1, slots1, a), (no2, n2, slots2, b) in zip(group, group[1:]):
                if no2 != no1 + 1 or n1 != 6 or n2 != 6:
                    continue
                result['adjacent_pairs'] += 1
                current_date = date.fromisoformat(day[:4]+'-'+day[4:6]+'-'+day[6:])
                first_raw, last_raw = bounds[venue]
                first_date = date.fromisoformat(first_raw[:4]+'-'+first_raw[4:6]+'-'+first_raw[6:])
                last_date = date.fromisoformat(last_raw[:4]+'-'+last_raw[4:6]+'-'+last_raw[6:])
                boundary = ('first_30_days' if (current_date-first_date).days < 30 else
                            'last_30_days' if (last_date-current_date).days < 30 else 'middle')
                result['adjacent_pairs_by_observed_boundary'][boundary] += 1
                matches = compare(a, b)
                for i, field in enumerate(FIELDS):
                    if informative(a[i]) and informative(b[i]):
                        result['eligible_pairs_by_field'][field] += 1
                    if matches[i]:
                        result['same_all_six_by_field'][field] += 1
                        result['same_by_venue_year_field'][(venue, day[:4], field)] += 1
                        ex = result['examples']['same_'+field]
                        if len(ex) < 8:
                            ex.append((venue, day, no1, no2, a[i], b[i]))
                result['same_field_count'][sum(matches)] += 1
                if packet_is_informative(a) and a == b:
                    result['full_packet_same'] += 1
                    result['full_packet_by_observed_boundary'][boundary] += 1
                    result['full_packet_by_venue_year'][(venue,day[:4])] += 1
                    result['full_packet_pairs'].append((venue,day,no1,no2))
                    ex = result['examples']['full_packet_same']
                    if len(ex) < 20: ex.append((venue, day, no1, no2, a))
                elif packet_is_informative(a) and all(informative(a[i]) for i in (0,2,3)):
                    boat_a = sorted(zip(*a))
                    boat_b = sorted(zip(*b))
                    if boat_a == boat_b:
                        result['full_packet_permuted'] += 1
                if any(matches) and a != b:
                    result['partial_field_repeat_pairs'] += 1
                    ex = result['examples']['partial_field_repeat']
                    if len(ex) < 20:
                        ex.append((venue,day,no1,no2,
                                   [FIELDS[i] for i,m in enumerate(matches) if m],a,b))
            previous_day = (date.fromisoformat(day[:4]+'-'+day[4:6]+'-'+day[6:]) - timedelta(days=1)).strftime('%Y%m%d')
            prior = by_day.get((venue, previous_day), ())
            prior_packets = defaultdict(list)
            for prior_no, n, slots, packet in prior:
                if n == 6 and packet_is_informative(packet):
                    prior_packets[packet].append(prior_no)
            for no, n, slots, packet in group:
                if n == 6 and packet_is_informative(packet) and packet in prior_packets:
                    result['previous_calendar_day_full_packet'] += 1
                    if no in prior_packets[packet]: result['previous_day_same_race_no'] += 1
                    ex = result['examples']['previous_day_full_packet']
                    if len(ex) < 20: ex.append((venue, previous_day, prior_packets[packet], day, no, packet))
        result['eligible_pairs_by_field'] = dict(result['eligible_pairs_by_field'])
        result['adjacent_pairs_by_observed_boundary'] = dict(result['adjacent_pairs_by_observed_boundary'])
        result['full_packet_by_observed_boundary'] = dict(result['full_packet_by_observed_boundary'])
        result['same_all_six_by_field'] = dict(result['same_all_six_by_field'])
        result['same_by_venue_year_field'] = [dict(venue=v, year=y, field=f, pairs=n)
                for (v,y,f),n in sorted(result['same_by_venue_year_field'].items())]
        result['full_packet_by_venue_year'] = [dict(venue=v,year=y,pairs=n)
                for (v,y),n in sorted(result['full_packet_by_venue_year'].items())]
        result['same_field_count'] = dict(result['same_field_count'])
        result['examples'] = dict(result['examples'])
        return result
    finally:
        conn.rollback()
        conn.close()


if __name__ == '__main__':
    result = run()
    path = '.local/c4_carry_readonly.json'
    with open(path, 'w', encoding='utf-8') as output:
        json.dump(result, output, ensure_ascii=False, indent=2)
    print(json.dumps({k: v for k,v in result.items() if k not in
                      ('same_by_venue_year_field', 'full_packet_by_venue_year',
                       'full_packet_pairs',
                       'examples', 'incomplete_races')}, ensure_ascii=False))
