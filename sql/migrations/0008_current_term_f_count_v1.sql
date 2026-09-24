-- Race-entry L3 display count. Results never enter this feature.
-- All entries for one player on D must agree; otherwise D is unresolved.
CREATE OR REPLACE FUNCTION core.current_term_f_count_value_v1(raw_value text, parsed_value integer)
RETURNS integer LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
 SELECT CASE WHEN raw_value IS NOT NULL
                  AND btrim(raw_value) ~ '^[0-9]+$'
                  AND parsed_value IS NOT NULL
                  AND coalesce(nullif(ltrim(btrim(raw_value), '0'), ''), '0') = parsed_value::text
             THEN parsed_value ELSE NULL END
$$;

CREATE OR REPLACE FUNCTION core.current_term_f_count_status_v1(raw_value text, parsed_value integer)
RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
 SELECT CASE WHEN core.current_term_f_count_value_v1(raw_value, parsed_value) IS NOT NULL
             THEN 'VALID' ELSE 'UNRESOLVED' END
$$;

CREATE OR REPLACE FUNCTION core.current_term_start_v1(day date)
RETURNS date LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
 SELECT CASE WHEN extract(month FROM day) BETWEEN 5 AND 10
             THEN make_date(extract(year FROM day)::integer, 5, 1)
             WHEN extract(month FROM day) >= 11
             THEN make_date(extract(year FROM day)::integer, 11, 1)
             ELSE make_date(extract(year FROM day)::integer - 1, 11, 1) END
$$;

CREATE OR REPLACE VIEW core.race_entry_current_term_f_count_v1 AS
WITH observations AS (
    SELECT r.race_id, r.race_date, r.venue_code, r.race_no,
           e.boat_no, e.player_id, e.f_count_current_term_raw,
           e.source_record_id, s.source_batch_id, s.source_record_key,
           s.record_hash, b.source_table, b.content_hash AS source_batch_hash,
           b.retrieved_at, b.extracted_at, b.ingested_at,
           CASE WHEN b.source_table = 'brd_l3'
                THEN core.current_term_f_count_value_v1(
                    e.f_count_current_term_raw, e.f_count_current_term)
                ELSE NULL END AS observed_count
    FROM core.race_entry e
    JOIN core.race r USING (race_id)
    JOIN raw.source_record s ON s.source_record_id = e.source_record_id
    JOIN raw.source_batch b USING (source_batch_id)
), day_state AS (
    SELECT o.*,
           count(*) OVER day_player AS entry_count,
           count(observed_count) OVER day_player AS valid_entry_count,
           min(observed_count) OVER day_player AS minimum_count,
           max(observed_count) OVER day_player AS maximum_count
    FROM observations o
    WINDOW day_player AS (PARTITION BY race_date, player_id)
)
SELECT race_id, race_date, venue_code, race_no, boat_no,
       player_id AS registration_no,
       core.current_term_start_v1(race_date) AS term_start_date,
       f_count_current_term_raw AS current_term_f_count_raw,
       CASE WHEN entry_count = valid_entry_count
                     AND minimum_count = maximum_count
            THEN observed_count ELSE NULL END AS current_term_f_count,
       CASE WHEN entry_count = valid_entry_count
                     AND minimum_count = maximum_count
            THEN 'VALID' ELSE 'UNRESOLVED' END AS current_term_f_count_status,
       source_record_id, source_batch_id, source_record_key, record_hash,
       source_table, source_batch_hash, retrieved_at, extracted_at, ingested_at,
       'current-term-f-count-v1'::text AS feature_version,
       'f_kaisu'::text AS source_field,
       'RACE_ENTRY_INFORMATION'::text AS information_kind,
       'NOT_VERIFIED'::text AS historical_availability_status
FROM day_state;
