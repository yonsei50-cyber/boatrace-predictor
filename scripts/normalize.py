"""PC-KYOTEI normalization. Evidence and unresolved codes: docs/source_mapping.md."""
from decimal import Decimal
import re
from scripts.foundation import NORMALIZATION_VERSION, integer

def normalize_sex(raw):
    value = {'1':'MALE','2':'FEMALE'}.get(raw)
    return value, 'CONFIRMED_CODE' if value else ('MISSING' if raw is None or not raw.strip() else 'UNRESOLVED')

def normalize_grade(raw):
    return {'1':'SG','2':'PG1','3':'G1','4':'G2','5':'G3','9':'GENERAL'}.get(raw)

def source_boolean(raw):
    # The PDF calls 0 an initial value, not a verified negative observation.
    return True if raw == '1' else None

def normalize_result(row):
    finish,course,st,symbol = (row.get(k) for k in ('chakujun','shinnyu_course','st','kigo'))
    finish_position = integer(finish,1,6)
    known_symbol = {'F':'F','L':'L','K':'ABSENT','S':'DISQUALIFIED'}.get(symbol)
    finish_fl = {'Ｆ':'F','Ｌ':'L'}.get(finish)
    if (finish_fl and known_symbol and finish_fl != known_symbol) or (finish_position and known_symbol):
        raise ValueError('BLOCKING: conflicting result finish and symbol')
    status = known_symbol or finish_fl or ('NORMAL' if finish_position else 'UNRESOLVED')
    start = None
    if status in ('F','L'):
        st_status = status
    elif symbol not in (None,' ','','K','S'):
        st_status = 'UNRESOLVED'
    elif st is None or not st.strip():
        st_status = 'MISSING'
    elif re.fullmatch(r'[0-9]{3}', st):
        start = Decimal(st) / 100
        st_status = 'NORMAL'
    else:
        st_status = 'UNRESOLVED'
    actual = integer(course,1,6)
    unresolved = status == 'UNRESOLVED' or st_status == 'UNRESOLVED' or (
        course is not None and course.strip() and actual is None)
    return dict(actual_course_raw=course,actual_course=actual,finish_raw=finish,
        finish_position=finish_position,result_status=status,result_symbol_raw=symbol,
        start_timing_raw=st,start_timing=start,start_timing_status=st_status,
        normalization_status='UNRESOLVED' if unresolved else 'NORMALIZED',
        normalization_version=NORMALIZATION_VERSION)
