"""Deterministic metadata for a complete K3-only Canonical result dataset."""

from datetime import date, timedelta

from psycopg2.extras import Json

from scripts.foundation import digest


SOURCE_TABLE = 'brd_k3'
RESULT_NORMALIZATION_VERSION = 'k3-only-result-v1'


def _months_through(first, last):
    current = first.replace(day=1)
    final = last.replace(day=1)
    while current <= final:
        yield current.strftime('%Y-%m')
        current = (current.replace(day=28) + timedelta(days=4)).replace(day=1)


def record_k3_result_dataset_version(cur, *, date_start, date_end,
                                     extraction_version):
    """Validate and record one immutable version for the full K3 result set."""
    if not isinstance(date_start, date) or not isinstance(date_end, date):
        raise TypeError('date_start and date_end must be dates')
    if date_start > date_end:
        raise ValueError('result dataset date range is reversed')
    if not extraction_version:
        raise ValueError('extraction_version is required')

    cur.execute("""SELECT extraction_condition->>'partition',row_count,content_hash
        FROM raw.source_batch
        WHERE source_table=%s AND extraction_condition->>'version'=%s
          AND extraction_condition->>'partition'>=%s
          AND extraction_condition->>'partition'<=%s
        ORDER BY extraction_condition->>'partition',source_batch_id""",
        (SOURCE_TABLE, extraction_version, date_start.strftime('%Y-%m'),
         date_end.strftime('%Y-%m')))
    manifest = [dict(month=month, rows=rows, content_hash=content_hash)
                for month, rows, content_hash in cur.fetchall()]
    expected_months = list(_months_through(date_start, date_end))
    if [item['month'] for item in manifest] != expected_months:
        raise RuntimeError('K3 source manifest is incomplete or ambiguous')

    cur.execute("""SELECT count(*),count(DISTINCT z.race_id),
            min(r.race_date),max(r.race_date),
            count(*) FILTER (WHERE b.source_table<>%s OR
                b.extraction_condition->>'version' IS DISTINCT FROM %s),
            count(*) FILTER (WHERE z.normalization_version<>%s)
        FROM core.race_result z
        JOIN core.race r USING(race_id)
        JOIN raw.source_record s ON s.source_record_id=z.source_record_id
        JOIN raw.source_batch b USING(source_batch_id)""",
        (SOURCE_TABLE, extraction_version, RESULT_NORMALIZATION_VERSION))
    result_boats, result_races, actual_start, actual_end, foreign, wrong_version = cur.fetchone()
    if not result_boats:
        raise RuntimeError('Canonical result dataset is empty')
    if foreign or wrong_version:
        raise RuntimeError('Canonical result lineage is not exclusively normalized K3')
    if actual_start < date_start or actual_end > date_end:
        raise RuntimeError('Canonical results fall outside the declared date range')
    if sum(item['rows'] for item in manifest) != result_boats:
        raise RuntimeError('K3 source manifest does not cover Canonical results exactly')

    manifest_hash = digest(manifest)
    version_id = 'K3_ONLY_RESULT_V1_' + manifest_hash[:16]
    cur.execute("""INSERT INTO core.result_dataset_version
        (version_id,authoritative_source,date_start,date_end,source_manifest,
         source_manifest_hash,normalization_version,result_races,result_boats)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        ON CONFLICT (version_id) DO NOTHING""",
        (version_id, SOURCE_TABLE, date_start, date_end, Json(manifest), manifest_hash,
         RESULT_NORMALIZATION_VERSION, result_races, result_boats))
    inserted = cur.rowcount == 1
    cur.execute("""SELECT authoritative_source,date_start,date_end,source_manifest,
            source_manifest_hash,normalization_version,result_races,result_boats
        FROM core.result_dataset_version WHERE version_id=%s""", (version_id,))
    stored = cur.fetchone()
    expected = (SOURCE_TABLE, date_start, date_end, manifest, manifest_hash,
                RESULT_NORMALIZATION_VERSION, result_races, result_boats)
    if stored != expected:
        raise RuntimeError('existing result dataset version metadata differs')
    return dict(version_id=version_id, authoritative_source=SOURCE_TABLE,
                date_start=date_start.isoformat(), date_end=date_end.isoformat(),
                source_manifest_hash=manifest_hash,
                normalization_version=RESULT_NORMALIZATION_VERSION,
                result_races=result_races, result_boats=result_boats,
                inserted=inserted)
