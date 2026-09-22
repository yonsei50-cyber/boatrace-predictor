"""Read-only inventory and bounded extraction of every stored source row."""
from datetime import date, timedelta
from psycopg2.extras import RealDictCursor
from scripts.import_sample import KEYS

TABLES = tuple(KEYS)
START_YEAR = '2017'
IDENTITY_SUPPORT = 'identity-before-2017'


def identity_support(conn):
    """One latest eligible pre-2017 KI per player only when needed after 2017."""
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute('''SELECT * FROM (
            SELECT DISTINCT ON (k.toroku_bango) k.* FROM public.brd_ki k
            JOIN (SELECT toroku_bango,min(kaisai_nen) AS first_year FROM public.brd_l3
                  WHERE kaisai_nen >= %s GROUP BY toroku_bango) f USING(toroku_bango)
            WHERE k.kaisai_nen < f.first_year
            ORDER BY k.toroku_bango,k.kaisai_nen DESC,k.ki DESC
        ) selected WHERE kaisai_nen < %s ORDER BY toroku_bango,kaisai_nen,ki''',
                    (START_YEAR,START_YEAR))
        return [dict(r) for r in cur.fetchall()]


def inventory(conn):
    report = {}
    with conn.cursor() as cur:
        for table in TABLES:
            if table == 'brd_ki':
                cur.execute('SELECT kaisai_nen,ki,count(*),count(DISTINCT toroku_bango) '
                            'FROM public.brd_ki WHERE kaisai_nen >= %s GROUP BY 1,2 ORDER BY 1,2',(START_YEAR,))
                terms = cur.fetchall()
                support=identity_support(conn)
                report[table] = {'rows': sum(r[2] for r in terms)+len(support),
                    'period_rows':sum(r[2] for r in terms),'terms': terms,
                    'identity_support':{'rows':len(support),'partition':IDENTITY_SUPPORT,
                        'earliest_year':min((r['kaisai_nen'] for r in support),default=None),
                        'latest_year':max((r['kaisai_nen'] for r in support),default=None),
                        'rule':'latest eligible KI before earliest 2017+ race year; only selections older than 2017'},
                    'earliest_year': min(r[0] for r in terms) if terms else None,
                    'latest_year': max(r[0] for r in terms) if terms else None,
                    'date_coverage': 'NOT_APPLICABLE: source year/term, not publication date',
                    'venue_coverage': 'NOT_APPLICABLE'}
                continue
            cur.execute('SELECT kaisai_nen,kaisai_tsukihi,kyoteijo_code,count(*) '
                        'FROM public.' + table + ' WHERE kaisai_nen >= %s GROUP BY 1,2,3 ORDER BY 1,2,3',(START_YEAR,))
            rows = cur.fetchall()
            days, invalid, venues = set(), [], {}
            for year, md, venue, count in rows:
                try:
                    day = date(int(year), int(md[:2]), int(md[2:]))
                    if day.strftime('%Y%m%d') != year + md:
                        raise ValueError('noncanonical source date')
                except (ValueError, TypeError):
                    invalid.append([year, md, venue, count])
                    continue
                days.add(day)
                v = venues.setdefault(venue, {'rows': 0, 'days': []})
                v['rows'] += count
                v['days'].append(day.isoformat())
            lo, hi = (min(days), max(days)) if days else (None, None)
            gaps = [] if lo is None else [(lo + timedelta(days=i)).isoformat()
                for i in range((hi-lo).days+1) if lo + timedelta(days=i) not in days]
            report[table] = {'rows': sum(r[3] for r in rows),
                'earliest': str(lo), 'latest': str(hi), 'date_count': len(days),
                'absent_calendar_dates': gaps, 'invalid_date_groups': invalid,
                'venues': {k: {'rows':v['rows'], 'date_count':len(v['days']),
                    'earliest':min(v['days']), 'latest':max(v['days'])} for k,v in venues.items()},
                'partitions': sorted({r[0] + '-' + r[1][:2] for r in rows}),
                'missingness_interpretation': 'absence in stored DB; acquisition history and racing schedule UNKNOWN'}
    return report


def extract(conn, table, partition):
    if table not in TABLES:
        raise ValueError('unknown source table')
    if table=='brd_ki' and partition==IDENTITY_SUPPORT:
        return identity_support(conn)
    if partition < START_YEAR:
        raise ValueError('history scope starts 2017-01-01; use the bounded KI identity support selection')
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        if table == 'brd_ki':
            condition, args = 'kaisai_nen=%s', (partition,)
        else:
            condition, args = "kaisai_nen=%s AND left(kaisai_tsukihi,2)=%s", tuple(partition.split('-'))
        cur.execute('SELECT * FROM public.' + table + ' WHERE ' + condition +
                    ' ORDER BY ' + ','.join(KEYS[table]), args)
        return [dict(r) for r in cur.fetchall()]
