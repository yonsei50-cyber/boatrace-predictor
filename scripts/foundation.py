"""Pure rules and deterministic serialization; no source DB dependency."""
from datetime import date, timedelta
from decimal import Decimal
import hashlib
import json
import re

NORMALIZATION_VERSION = 'pckyotei-foundation-v1'
MOTOR_RULE_VERSION = 'user-fixed-month-day-v1'
SELECTION_VERSION = 'phase2-explicit-races-v1'
VENUES = ['桐生','戸田','江戸川','平和島','多摩川','浜名湖','蒲郡','常滑',
          '津','三国','びわこ','住之江','尼崎','鳴門','丸亀','児島',
          '宮島','徳山','下関','若松','芦屋','福岡','唐津','大村']
MOTOR_STARTS = [(12,27),(8,6),(5,7),(6,9),(4,9),(4,15),(7,19),(11,11),
                (12,22),(3,7),(5,1),(3,23),(4,2),(4,6),(9,3),(12,17),
                (10,19),(4,15),(3,29),(11,26),(4,23),(2,18),(9,5),(6,22)]
# An explicit, bounded source selection, not a whole-period migration.
SAMPLE_RACES = [
    ('2024','0506','03','01'), ('2024','0507','03','01'),
    ('2024','0718','07','01'), ('2024','0719','07','01'),
    ('2026','0807','02','06'), ('2026','0901','05','04'),
    ('2026','0901','05','11'), ('2026','0901','06','07'),
    ('2026','0901','19','06'),
]

def canonical_json(value):
    def default(v):
        if isinstance(v, (date, Decimal)):
            return str(v)
        raise TypeError(type(v).__name__)
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False, default=default)

def digest(value):
    return hashlib.sha256(canonical_json(value).encode('utf-8')).hexdigest()

def integer(raw, low=0, high=None):
    if raw is None or not re.fullmatch(r'[0-9]+', raw.strip()):
        return None
    value = int(raw)
    return value if value >= low and (high is None or value <= high) else None

def motor_generation(venue, race_date):
    if not 1 <= venue <= 24:
        raise ValueError('unknown venue')
    month, day = MOTOR_STARTS[venue - 1]
    year = race_date.year - (race_date < date(race_date.year, month, day))
    return year, date(year, month, day), date(year + 1, month, day)

def women_only(sexes, boats):
    if 'MALE' in sexes:
        return False, 'CONFIRMED'
    if sorted(boats) == list(range(1, 7)) and len(sexes) == 6 and all(s == 'FEMALE' for s in sexes):
        return True, 'CONFIRMED'
    return None, 'UNKNOWN'

def identity_observation(candidates, first_race_year):
    eligible = [r for r in candidates if r['kaisai_nen'] < first_race_year]
    return min(eligible,key=lambda r:(r['kaisai_nen'],r['ki'])) if eligible else None

def results_before(snapshot, effective_date):
    """Read a frozen snapshot, never JOIN mutable current canonical tables."""
    dates = {r['race_id']: date.fromisoformat(r['race_date']) for r in snapshot['race']}
    result = [r for r in snapshot['race_result'] if dates[r['race_id']] < effective_date]
    if any(dates[r['race_id']] > effective_date - timedelta(days=1) for r in result):
        raise ValueError('cutoff violation')
    return result
