-- Additive Phase 3B interpretations over immutable R2/R3 evidence.
-- These views do not alter the frozen snapshot contract or decide model eligibility.

CREATE OR REPLACE VIEW core.result_source_evidence AS
SELECT r.race_id,r.race_date,r.venue_code,r.race_no,
       CASE WHEN b.source_table='brd_r3'
                 AND nullif(btrim(s.raw_payload->>'teiban'),'') ~ '^[1-6]$'
            THEN (btrim(s.raw_payload->>'teiban'))::smallint END AS boat_no,
       b.source_table AS evidence_type,s.source_record_id,s.source_batch_id,
       s.source_record_key,s.raw_payload,s.record_hash,
       b.content_hash AS source_batch_hash,b.source_locator,b.extraction_condition,
       b.retrieved_at,b.extracted_at,b.ingested_at,
       s.raw_payload->>'data_kubun' AS data_kubun_raw,
       s.raw_payload->>'haraimodoshi_sanrentan_1a' AS trifecta_payout_combination_raw,
       s.raw_payload->>'chakujun' AS finish_raw,
       s.raw_payload->>'kigo' AS start_symbol_raw,
       s.raw_payload->>'st' AS start_timing_raw,
       s.raw_payload->>'shinnyu_course' AS actual_course_raw
FROM raw.source_record s
JOIN raw.source_batch b USING(source_batch_id)
LEFT JOIN core.race r
  ON s.raw_payload->>'kaisai_nen'=to_char(r.race_date,'YYYY')
 AND s.raw_payload->>'kaisai_tsukihi'=to_char(r.race_date,'MMDD')
 AND s.raw_payload->>'kyoteijo_code'=lpad(r.venue_code::text,2,'0')
 AND s.raw_payload->>'race_no'=lpad(r.race_no::text,2,'0')
WHERE b.source_table IN ('brd_r2','brd_r3')
  AND s.raw_payload->>'kaisai_nen'>='2017';

CREATE OR REPLACE VIEW core.race_result_state AS
WITH evidence AS (
    SELECT race_id,boat_no,evidence_type,source_record_id,source_batch_id,
           record_hash,source_batch_hash,data_kubun_raw,
           trifecta_payout_combination_raw,finish_raw
    FROM core.result_source_evidence WHERE race_id IS NOT NULL
),
r2 AS (
    SELECT race_id,count(*) AS r2_source_record_count,
           count(DISTINCT record_hash) AS r2_distinct_revision_count,
           count(DISTINCT record_hash)>1 AS r2_revision_conflict,
           array_agg(source_record_id ORDER BY source_record_id) AS r2_source_record_ids,
           array_agg(DISTINCT source_batch_id ORDER BY source_batch_id) AS r2_source_batch_ids,
           array_agg(record_hash ORDER BY source_record_id) AS r2_record_hashes,
           array_agg(DISTINCT source_batch_hash ORDER BY source_batch_hash) AS r2_source_batch_hashes,
           array_agg(DISTINCT data_kubun_raw ORDER BY data_kubun_raw)
               FILTER (WHERE data_kubun_raw IS NOT NULL) AS r2_data_kubun_raw_values,
           array_agg(DISTINCT trifecta_payout_combination_raw ORDER BY trifecta_payout_combination_raw)
               FILTER (WHERE trifecta_payout_combination_raw IS NOT NULL)
               AS r2_trifecta_payout_combination_raw_values,
           bool_or(data_kubun_raw='9') AS has_verified_event_code,
           bool_or(btrim(coalesce(trifecta_payout_combination_raw,'')) ~ '^[1-6]{3}$'
                   AND btrim(trifecta_payout_combination_raw)<>'000'
                   AND substr(btrim(trifecta_payout_combination_raw),1,1)
                         <>substr(btrim(trifecta_payout_combination_raw),2,1)
                   AND substr(btrim(trifecta_payout_combination_raw),1,1)
                         <>substr(btrim(trifecta_payout_combination_raw),3,1)
                   AND substr(btrim(trifecta_payout_combination_raw),2,1)
                         <>substr(btrim(trifecta_payout_combination_raw),3,1))
               AS has_valid_trifecta_payout
    FROM evidence WHERE evidence_type='brd_r2' GROUP BY race_id
),
r3_boat AS (
    SELECT race_id,boat_no,count(*) AS source_record_count,
           count(DISTINCT record_hash) AS distinct_revision_count,
           count(DISTINCT record_hash)>1 AS revision_conflict,
           bool_and(nullif(btrim(finish_raw),'') IS NOT NULL) AS meaningful_finish
    FROM evidence WHERE evidence_type='brd_r3' AND boat_no IS NOT NULL
    GROUP BY race_id,boat_no
),
r3_boat_rollup AS (
    SELECT race_id,count(*) AS r3_distinct_boats,
           count(*) FILTER (WHERE meaningful_finish AND NOT revision_conflict)
               AS r3_meaningful_boats,
           bool_or(revision_conflict) AS r3_revision_conflict
    FROM r3_boat GROUP BY race_id
),
r3_lineage AS (
    SELECT race_id,count(*) AS r3_source_record_count,
           count(*) FILTER (WHERE boat_no IS NULL) AS r3_invalid_boat_rows,
           array_agg(source_record_id ORDER BY source_record_id) AS r3_source_record_ids,
           array_agg(DISTINCT source_batch_id ORDER BY source_batch_id) AS r3_source_batch_ids,
           array_agg(record_hash ORDER BY source_record_id) AS r3_record_hashes,
           array_agg(DISTINCT source_batch_hash ORDER BY source_batch_hash) AS r3_source_batch_hashes
    FROM evidence WHERE evidence_type='brd_r3' GROUP BY race_id
),
classified AS (
    SELECT race.race_id,race.race_date,race.venue_code,race.race_no,
           coalesce(rb.r3_distinct_boats,0) AS r3_distinct_boats,
           coalesce(rb.r3_meaningful_boats,0) AS r3_meaningful_boats,
           coalesce(rl.r3_source_record_count,0) AS r3_source_record_count,
           coalesce(rl.r3_invalid_boat_rows,0) AS r3_invalid_boat_rows,
           coalesce(rb.r3_revision_conflict,false) AS r3_revision_conflict,
           coalesce(r2.r2_source_record_count,0) AS r2_source_record_count,
           coalesce(r2.r2_distinct_revision_count,0) AS r2_distinct_revision_count,
           coalesce(r2.r2_revision_conflict,false) AS r2_revision_conflict,
           coalesce(r2.has_verified_event_code,false) AS has_verified_r2_event_code,
           coalesce(r2.has_valid_trifecta_payout,false) AS has_valid_r2_trifecta_payout,
           r2.r2_data_kubun_raw_values,r2.r2_trifecta_payout_combination_raw_values,
           r2.r2_source_record_ids,r2.r2_source_batch_ids,r2.r2_record_hashes,
           r2.r2_source_batch_hashes,rl.r3_source_record_ids,rl.r3_source_batch_ids,
           rl.r3_record_hashes,rl.r3_source_batch_hashes
    FROM core.race race
    LEFT JOIN r2 USING(race_id)
    LEFT JOIN r3_boat_rollup rb USING(race_id)
    LEFT JOIN r3_lineage rl USING(race_id)
    WHERE race.race_date>=DATE '2017-01-01'
)
SELECT c.*,
       CASE
         WHEN r2_revision_conflict OR r3_revision_conflict THEN 'UNRESOLVED'
         WHEN r3_invalid_boat_rows>0 THEN 'SOURCE_INCOMPLETE'
         WHEN r3_distinct_boats=6 AND r3_meaningful_boats=6
           THEN 'RESULT_RECORDS_PRESENT'
         WHEN r3_meaningful_boats>0 THEN 'SOURCE_INCOMPLETE'
         WHEN has_verified_r2_event_code THEN 'R2_EVENT_STATE_PRESENT'
         WHEN has_valid_r2_trifecta_payout THEN 'R2_PAYOUT_PRESENT_R3_MISSING'
         WHEN r3_distinct_boats>0 AND r3_distinct_boats<>6 THEN 'SOURCE_INCOMPLETE'
         WHEN r3_source_record_count=0 THEN 'SOURCE_INCOMPLETE'
         ELSE 'UNRESOLVED'
       END AS result_state,
       'result-state-v1'::text AS classification_version
FROM classified c;

CREATE OR REPLACE VIEW core.boat_finish_state AS
WITH evidence AS (
    SELECT race_id,boat_no,source_record_id,source_batch_id,record_hash,
           source_batch_hash,finish_raw,start_symbol_raw,start_timing_raw,actual_course_raw
    FROM core.result_source_evidence
    WHERE race_id IS NOT NULL AND evidence_type='brd_r3' AND boat_no IS NOT NULL
),
per_boat AS (
    SELECT race_id,boat_no,count(*) AS source_record_count,
           count(DISTINCT record_hash) AS distinct_revision_count,
           count(DISTINCT record_hash)>1 AS revision_conflict,
           CASE WHEN count(DISTINCT record_hash)=1 THEN min(finish_raw) END AS finish_raw,
           CASE WHEN count(DISTINCT record_hash)=1 THEN min(start_symbol_raw) END AS start_symbol_raw,
           CASE WHEN count(DISTINCT record_hash)=1 THEN min(start_timing_raw) END AS start_timing_raw,
           CASE WHEN count(DISTINCT record_hash)=1 THEN min(actual_course_raw) END AS actual_course_raw,
           array_agg(DISTINCT finish_raw ORDER BY finish_raw) AS finish_raw_values,
           array_agg(DISTINCT start_symbol_raw ORDER BY start_symbol_raw) AS start_symbol_raw_values,
           array_agg(DISTINCT start_timing_raw ORDER BY start_timing_raw) AS start_timing_raw_values,
           array_agg(DISTINCT actual_course_raw ORDER BY actual_course_raw) AS actual_course_raw_values,
           array_agg(source_record_id ORDER BY source_record_id) AS source_record_ids,
           array_agg(DISTINCT source_batch_id ORDER BY source_batch_id) AS source_batch_ids,
           array_agg(record_hash ORDER BY source_record_id) AS record_hashes,
           array_agg(DISTINCT source_batch_hash ORDER BY source_batch_hash) AS source_batch_hashes
    FROM evidence GROUP BY race_id,boat_no
),
parsed AS (
    SELECT p.*,
           CASE WHEN NOT revision_conflict AND btrim(finish_raw) ~ '^0?[1-6]$'
                THEN (btrim(finish_raw))::smallint END AS numeric_finish
    FROM per_boat p
),
numeric_counts AS (
    SELECT race_id,numeric_finish,count(*) AS boats
    FROM parsed WHERE numeric_finish IS NOT NULL GROUP BY race_id,numeric_finish
),
race_flags AS (
    SELECT race_id,bool_or(revision_conflict) AS revision_conflict,
           bool_or(boats>1) AS numeric_duplicate
    FROM parsed LEFT JOIN numeric_counts USING(race_id,numeric_finish)
    GROUP BY race_id
)
SELECT e.race_id,r.race_date,r.venue_code,r.race_no,e.boat_no,
       p.finish_raw,p.numeric_finish AS finish_position,
       CASE
         WHEN coalesce(f.revision_conflict,false) THEN 'UNRESOLVED_SOURCE_CONFLICT'
         WHEN p.numeric_finish IS NOT NULL AND n.boats>1 THEN 'NUMERIC_DUPLICATE_UNRESOLVED'
         WHEN p.numeric_finish IS NOT NULL AND coalesce(f.numeric_duplicate,false)
           THEN 'NUMERIC_IN_DUPLICATE_RACE_UNRESOLVED'
         WHEN p.numeric_finish IS NOT NULL THEN 'NUMERIC_VALID'
         WHEN p.finish_raw IS NULL OR nullif(btrim(p.finish_raw),'') IS NULL
           THEN 'NO_INDIVIDUAL_RESULT'
         ELSE 'UNRESOLVED_SPECIAL'
       END AS finish_state,
       p.finish_raw_values,
       p.start_symbol_raw,p.start_timing_raw,z.start_timing,z.start_timing_status,
       p.start_symbol_raw_values,p.start_timing_raw_values,
       p.actual_course_raw,z.actual_course,
       p.actual_course_raw_values,
       coalesce(p.source_record_count,0) AS r3_source_record_count,
       coalesce(p.distinct_revision_count,0) AS r3_distinct_revision_count,
       coalesce(p.revision_conflict,false) AS r3_revision_conflict,
       p.source_record_ids AS r3_source_record_ids,p.source_batch_ids AS r3_source_batch_ids,
       p.record_hashes AS r3_record_hashes,p.source_batch_hashes AS r3_source_batch_hashes,
       'finish-state-v1'::text AS classification_version
FROM core.race_entry e
JOIN core.race r USING(race_id)
LEFT JOIN parsed p USING(race_id,boat_no)
LEFT JOIN numeric_counts n ON n.race_id=p.race_id AND n.numeric_finish=p.numeric_finish
LEFT JOIN race_flags f ON f.race_id=e.race_id
LEFT JOIN core.race_result z ON z.race_id=e.race_id AND z.boat_no=e.boat_no
WHERE r.race_date>=DATE '2017-01-01';
