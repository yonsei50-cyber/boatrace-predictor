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
    """Normalize individual results from K3 while retaining every source token."""
    finish,course,st = (row.get(k) for k in ('chakujun','shinnyu_course','st'))
    token = finish.strip() if finish is not None else ''
    finish_position = integer(token,1,6) if re.fullmatch(r'[0-9]+',token) else None
    status = ('F' if token == 'F' else 'L' if token in ('L0','L1')
              else 'NORMAL' if finish_position is not None else 'UNRESOLVED')
    start = None
    if status in ('F','L'):
        st_status = status
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
        finish_position=finish_position,result_status=status,result_symbol_raw=None,
        start_timing_raw=st,start_timing=start,start_timing_status=st_status,
        normalization_status='UNRESOLVED' if unresolved else 'NORMALIZED',
        normalization_version='k3-only-result-v1')
