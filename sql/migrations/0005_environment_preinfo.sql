-- Additive Phase 3C canonical interpretations over immutable C2/C3 evidence.
-- C4 values remain excluded: their scale and historical row/boat correspondence
-- are unresolved. These objects do not alter an existing frozen dataset.

CREATE OR REPLACE FUNCTION core.preinfo_tenth_status_v1(value text)
RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
 SELECT CASE WHEN value IS NULL OR btrim(value) = '' THEN 'MISSING'
             WHEN value ~ '^([0-9]{3}|-[0-9]{2})$' THEN 'VALID'
             ELSE 'INVALID' END
$$;

CREATE OR REPLACE FUNCTION core.preinfo_tenth_value_v1(value text)
RETURNS numeric LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
 SELECT CASE WHEN core.preinfo_tenth_status_v1(value) = 'VALID'
             THEN value::numeric / 10 ELSE NULL END
$$;

CREATE OR REPLACE FUNCTION core.preinfo_weather_status_v1(value text)
RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
 SELECT CASE WHEN value IS NULL OR btrim(value) = '' THEN 'MISSING'
             WHEN value ~ '^[1-6]$' THEN 'VALID'
             ELSE 'INVALID' END
$$;

CREATE OR REPLACE FUNCTION core.preinfo_weather_value_v1(value text)
RETURNS smallint LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
 SELECT CASE WHEN core.preinfo_weather_status_v1(value) = 'VALID'
             THEN value::smallint ELSE NULL END
$$;

CREATE OR REPLACE FUNCTION core.preinfo_direction_status_v1(value text)
RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
 SELECT CASE WHEN value IS NULL OR btrim(value) = '' THEN 'MISSING'
             WHEN value ~ '^(0[1-9]|1[0-6])$' THEN 'VALID'
             ELSE 'INVALID' END
$$;

CREATE OR REPLACE FUNCTION core.preinfo_direction_value_v1(value text)
RETURNS smallint LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
 SELECT CASE WHEN core.preinfo_direction_status_v1(value) = 'VALID'
             THEN value::smallint ELSE NULL END
$$;

-- A nonblank value is intentionally not promoted to a physical quantity until
-- its unit is confirmed. Zero is retained as an observation, not as a sentinel.
CREATE OR REPLACE FUNCTION core.preinfo_unresolved_measure_status_v1(value text)
RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
 SELECT CASE WHEN value IS NULL OR btrim(value) = '' THEN 'MISSING'
             ELSE 'UNRESOLVED' END
$$;

CREATE OR REPLACE FUNCTION core.exhibition_time_status_v1(value text)
RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
 SELECT CASE WHEN value IS NULL OR btrim(value) = '' THEN 'MISSING'
             WHEN value = '0000' THEN 'SOURCE_SENTINEL'
             WHEN value ~ '^[0-9]{4}$' THEN 'VALID'
             ELSE 'INVALID' END
$$;

CREATE OR REPLACE FUNCTION core.exhibition_time_seconds_v1(value text)
RETURNS numeric LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
 SELECT CASE WHEN core.exhibition_time_status_v1(value) = 'VALID'
             THEN value::numeric / 100 ELSE NULL END
$$;

CREATE OR REPLACE FUNCTION core.exhibition_tilt_status_v1(value text)
RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
 SELECT CASE WHEN value IS NULL OR btrim(value) = '' THEN 'MISSING'
             WHEN btrim(value) ~ '^-?[0-9]{2}$' THEN 'VALID'
             ELSE 'INVALID' END
$$;

CREATE OR REPLACE FUNCTION core.exhibition_tilt_degrees_v1(value text)
RETURNS numeric LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
 SELECT CASE WHEN core.exhibition_tilt_status_v1(value) = 'VALID'
             THEN btrim(value)::numeric / 10 ELSE NULL END
$$;

CREATE OR REPLACE FUNCTION core.exhibition_course_status_v1(value text)
RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
 SELECT CASE WHEN value IS NULL OR btrim(value) = '' THEN 'MISSING'
             WHEN btrim(value) ~ '^[1-6]$' THEN 'VALID'
             ELSE 'INVALID' END
$$;

CREATE OR REPLACE FUNCTION core.exhibition_course_value_v1(value text)
RETURNS smallint LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
 SELECT CASE WHEN core.exhibition_course_status_v1(value) = 'VALID'
             THEN btrim(value)::smallint ELSE NULL END
$$;

CREATE OR REPLACE FUNCTION core.exhibition_start_status_v1(value text, symbol text)
RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
 SELECT CASE WHEN btrim(coalesce(symbol,'')) = 'F' THEN 'F'
             WHEN btrim(coalesce(symbol,'')) = 'L' THEN 'L'
             WHEN btrim(coalesce(symbol,'')) <> '' THEN 'UNRESOLVED_SYMBOL'
             WHEN value IS NULL OR btrim(value) = '' THEN 'MISSING'
             WHEN value ~ '^[0-9]{3}$' THEN 'VALID'
             ELSE 'INVALID' END
$$;

CREATE OR REPLACE FUNCTION core.exhibition_start_seconds_v1(value text, symbol text)
RETURNS numeric LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
 SELECT CASE WHEN core.exhibition_start_status_v1(value,symbol) = 'VALID'
             THEN value::numeric / 100 ELSE NULL END
$$;

CREATE TABLE IF NOT EXISTS core.race_environment_preinfo (
    race_id bigint PRIMARY KEY REFERENCES core.race,
    air_temperature_raw text,
    air_temperature_c numeric(4,1)
      GENERATED ALWAYS AS (core.preinfo_tenth_value_v1(air_temperature_raw)) STORED,
    air_temperature_status text
      GENERATED ALWAYS AS (core.preinfo_tenth_status_v1(air_temperature_raw)) STORED,
    water_temperature_raw text,
    water_temperature_c numeric(4,1)
      GENERATED ALWAYS AS (core.preinfo_tenth_value_v1(water_temperature_raw)) STORED,
    water_temperature_status text
      GENERATED ALWAYS AS (core.preinfo_tenth_status_v1(water_temperature_raw)) STORED,
    weather_code_raw text,
    weather_code smallint
      GENERATED ALWAYS AS (core.preinfo_weather_value_v1(weather_code_raw)) STORED,
    weather_status text
      GENERATED ALWAYS AS (core.preinfo_weather_status_v1(weather_code_raw)) STORED,
    wind_direction_code_raw text,
    wind_direction_code smallint
      GENERATED ALWAYS AS (core.preinfo_direction_value_v1(wind_direction_code_raw)) STORED,
    wind_direction_status text
      GENERATED ALWAYS AS (core.preinfo_direction_status_v1(wind_direction_code_raw)) STORED,
    venue_direction_code_raw text,
    venue_direction_code smallint
      GENERATED ALWAYS AS (core.preinfo_direction_value_v1(venue_direction_code_raw)) STORED,
    venue_direction_status text
      GENERATED ALWAYS AS (core.preinfo_direction_status_v1(venue_direction_code_raw)) STORED,
    wind_speed_raw text,
    wind_speed_status text
      GENERATED ALWAYS AS (core.preinfo_unresolved_measure_status_v1(wind_speed_raw)) STORED,
    wave_height_raw text,
    wave_height_status text
      GENERATED ALWAYS AS (core.preinfo_unresolved_measure_status_v1(wave_height_raw)) STORED,
    surface_weather_marker_raw text,
    surface_weather_marker_status text
      GENERATED ALWAYS AS (core.preinfo_unresolved_measure_status_v1(surface_weather_marker_raw)) STORED,
    source_record_id bigint NOT NULL UNIQUE REFERENCES raw.source_record,
    normalization_version text NOT NULL DEFAULT 'phase3c-environment-preinfo-v1'
      CHECK (normalization_version = 'phase3c-environment-preinfo-v1'),
    provenance jsonb NOT NULL CHECK (jsonb_typeof(provenance) = 'object')
);

CREATE TABLE IF NOT EXISTS core.race_boat_preinfo (
    race_id bigint NOT NULL,
    boat_no smallint NOT NULL CHECK (boat_no BETWEEN 1 AND 6),
    exhibition_time_raw text,
    exhibition_time_seconds numeric(5,2)
      GENERATED ALWAYS AS (core.exhibition_time_seconds_v1(exhibition_time_raw)) STORED,
    exhibition_time_status text
      GENERATED ALWAYS AS (core.exhibition_time_status_v1(exhibition_time_raw)) STORED,
    tilt_raw text,
    tilt_degrees numeric(3,1)
      GENERATED ALWAYS AS (core.exhibition_tilt_degrees_v1(tilt_raw)) STORED,
    tilt_status text
      GENERATED ALWAYS AS (core.exhibition_tilt_status_v1(tilt_raw)) STORED,
    exhibition_course_raw text,
    exhibition_course smallint
      GENERATED ALWAYS AS (core.exhibition_course_value_v1(exhibition_course_raw)) STORED,
    exhibition_course_status text
      GENERATED ALWAYS AS (core.exhibition_course_status_v1(exhibition_course_raw)) STORED,
    exhibition_start_timing_raw text,
    exhibition_start_symbol_raw text,
    exhibition_start_timing numeric(4,2)
      GENERATED ALWAYS AS (core.exhibition_start_seconds_v1(
          exhibition_start_timing_raw,exhibition_start_symbol_raw)) STORED,
    exhibition_start_status text
      GENERATED ALWAYS AS (core.exhibition_start_status_v1(
          exhibition_start_timing_raw,exhibition_start_symbol_raw)) STORED,
    source_record_id bigint NOT NULL UNIQUE REFERENCES raw.source_record,
    normalization_version text NOT NULL DEFAULT 'phase3c-environment-preinfo-v1'
      CHECK (normalization_version = 'phase3c-environment-preinfo-v1'),
    provenance jsonb NOT NULL CHECK (jsonb_typeof(provenance) = 'object'),
    PRIMARY KEY (race_id,boat_no),
    FOREIGN KEY (race_id,boat_no) REFERENCES core.race_entry
);

CREATE OR REPLACE FUNCTION core.load_race_environment_preinfo_v1()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE payload jsonb; raw_key jsonb; source_table_name text; race_row core.race%ROWTYPE;
BEGIN
 SELECT s.raw_payload,s.source_record_key,b.source_table
 INTO payload,raw_key,source_table_name
 FROM raw.source_record s JOIN raw.source_batch b USING(source_batch_id)
 WHERE s.source_record_id=NEW.source_record_id;
 SELECT * INTO race_row FROM core.race WHERE race_id=NEW.race_id;
 IF source_table_name IS DISTINCT FROM 'brd_c2'
    OR payload->>'kaisai_nen' IS DISTINCT FROM to_char(race_row.race_date,'YYYY')
    OR payload->>'kaisai_tsukihi' IS DISTINCT FROM to_char(race_row.race_date,'MMDD')
    OR payload->>'kyoteijo_code' IS DISTINCT FROM lpad(race_row.venue_code::text,2,'0')
    OR payload->>'race_no' IS DISTINCT FROM lpad(race_row.race_no::text,2,'0')
    OR raw_key IS DISTINCT FROM jsonb_build_object(
       'kaisai_nen',payload->>'kaisai_nen','kaisai_tsukihi',payload->>'kaisai_tsukihi',
       'kyoteijo_code',payload->>'kyoteijo_code','race_no',payload->>'race_no') THEN
   RAISE EXCEPTION 'C2 race source identity mismatch';
 END IF;
 NEW.air_temperature_raw := payload->>'kion';
 NEW.water_temperature_raw := payload->>'suion';
 NEW.weather_code_raw := payload->>'tenki_code';
 NEW.wind_direction_code_raw := payload->>'fuko_code';
 NEW.venue_direction_code_raw := payload->>'hogaku_code';
 NEW.wind_speed_raw := payload->>'fusoku';
 NEW.wave_height_raw := payload->>'hako';
 NEW.surface_weather_marker_raw := payload->>'suimenkisho_joho';
 NEW.normalization_version := 'phase3c-environment-preinfo-v1';
 NEW.provenance := jsonb_build_object(
   'normalization_version','phase3c-environment-preinfo-v1',
   'source_table','brd_c2',
   'source_fields',jsonb_build_array('kion','suion','tenki_code','fuko_code',
      'hogaku_code','fusoku','hako','suimenkisho_joho'),
   'information_kind','PRE_RACE_SOURCE_CLASS',
   'historical_availability_status','SOURCE_CLASS_POLICY_NOT_EXACT_AS_OF_PROOF',
   'result_dependency',false);
 RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS load_race_environment_preinfo ON core.race_environment_preinfo;
CREATE TRIGGER load_race_environment_preinfo
BEFORE INSERT OR UPDATE ON core.race_environment_preinfo
FOR EACH ROW EXECUTE FUNCTION core.load_race_environment_preinfo_v1();

CREATE OR REPLACE FUNCTION core.load_race_boat_preinfo_v1()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE payload jsonb; raw_key jsonb; source_table_name text; race_row core.race%ROWTYPE;
BEGIN
 SELECT s.raw_payload,s.source_record_key,b.source_table
 INTO payload,raw_key,source_table_name
 FROM raw.source_record s JOIN raw.source_batch b USING(source_batch_id)
 WHERE s.source_record_id=NEW.source_record_id;
 SELECT * INTO race_row FROM core.race WHERE race_id=NEW.race_id;
 IF source_table_name IS DISTINCT FROM 'brd_c3'
    OR payload->>'kaisai_nen' IS DISTINCT FROM to_char(race_row.race_date,'YYYY')
    OR payload->>'kaisai_tsukihi' IS DISTINCT FROM to_char(race_row.race_date,'MMDD')
    OR payload->>'kyoteijo_code' IS DISTINCT FROM lpad(race_row.venue_code::text,2,'0')
    OR payload->>'race_no' IS DISTINCT FROM lpad(race_row.race_no::text,2,'0')
    OR nullif(btrim(payload->>'teiban'),'')::smallint IS DISTINCT FROM NEW.boat_no
    OR raw_key IS DISTINCT FROM jsonb_build_object(
       'kaisai_nen',payload->>'kaisai_nen','kaisai_tsukihi',payload->>'kaisai_tsukihi',
       'kyoteijo_code',payload->>'kyoteijo_code','race_no',payload->>'race_no',
       'teiban',payload->>'teiban') THEN
   RAISE EXCEPTION 'C3 race/boat source identity mismatch';
 END IF;
 NEW.exhibition_time_raw := payload->>'tenji_time';
 NEW.tilt_raw := payload->>'tilt';
 NEW.exhibition_course_raw := payload->>'tenji_shinnyu_course';
 NEW.exhibition_start_timing_raw := payload->>'tenji_st';
 NEW.exhibition_start_symbol_raw := payload->>'tenji_kigo';
 NEW.normalization_version := 'phase3c-environment-preinfo-v1';
 NEW.provenance := jsonb_build_object(
   'normalization_version','phase3c-environment-preinfo-v1',
   'source_table','brd_c3',
   'source_fields',jsonb_build_array('tenji_time','tilt','tenji_shinnyu_course',
      'tenji_st','tenji_kigo'),
   'information_kind','PRE_RACE_SOURCE_CLASS',
   'historical_availability_status','SOURCE_CLASS_POLICY_NOT_EXACT_AS_OF_PROOF',
   'result_dependency',false,
   'boat_identity_field','teiban');
 RETURN NEW;
EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range THEN
 RAISE EXCEPTION 'C3 race/boat source identity mismatch';
END;
$$;
DROP TRIGGER IF EXISTS load_race_boat_preinfo ON core.race_boat_preinfo;
CREATE TRIGGER load_race_boat_preinfo
BEFORE INSERT OR UPDATE ON core.race_boat_preinfo
FOR EACH ROW EXECUTE FUNCTION core.load_race_boat_preinfo_v1();

CREATE OR REPLACE FUNCTION core.backfill_race_environment_preinfo_v1(
    p_source_batch_id bigint DEFAULT NULL)
RETURNS bigint LANGUAGE plpgsql AS $$
DECLARE inserted_count bigint;
BEGIN
 IF EXISTS (
   WITH candidate AS MATERIALIZED (
     SELECT s.source_record_id,s.raw_payload
     FROM raw.source_record s JOIN raw.source_batch b USING(source_batch_id)
     WHERE b.source_table='brd_c2'
       AND (p_source_batch_id IS NULL OR s.source_batch_id=p_source_batch_id)
       AND s.raw_payload->>'kaisai_nen' ~ '^[0-9]{4}$'
       AND s.raw_payload->>'kaisai_tsukihi' ~ '^[0-9]{4}$'
       AND s.raw_payload->>'kyoteijo_code' ~ '^(0[1-9]|1[0-9]|2[0-4])$'
       AND s.raw_payload->>'race_no' ~ '^(0[1-9]|1[0-2])$'
   )
   SELECT 1 FROM candidate c
   JOIN core.race r
     ON r.race_date=to_date((c.raw_payload->>'kaisai_nen') ||
                            (c.raw_payload->>'kaisai_tsukihi'),'YYYYMMDD')
    AND r.venue_code=(c.raw_payload->>'kyoteijo_code')::smallint
    AND r.race_no=(c.raw_payload->>'race_no')::smallint
   JOIN core.race_environment_preinfo p USING(race_id)
   WHERE p.source_record_id<>c.source_record_id
 ) THEN RAISE EXCEPTION 'C2 canonical source conflict'; END IF;
 WITH eligible AS (
   SELECT min(s.source_record_id) AS source_record_id,
          s.raw_payload->>'kaisai_nen' AS y,s.raw_payload->>'kaisai_tsukihi' AS md,
          s.raw_payload->>'kyoteijo_code' AS venue,s.raw_payload->>'race_no' AS race_no
   FROM raw.source_record s JOIN raw.source_batch b USING(source_batch_id)
   WHERE b.source_table='brd_c2' AND s.raw_payload->>'kaisai_nen'>='2017'
     AND (p_source_batch_id IS NULL OR s.source_batch_id=p_source_batch_id)
     AND s.raw_payload->>'kaisai_nen' ~ '^[0-9]{4}$'
     AND s.raw_payload->>'kaisai_tsukihi' ~ '^[0-9]{4}$'
     AND s.raw_payload->>'kyoteijo_code' ~ '^(0[1-9]|1[0-9]|2[0-4])$'
     AND s.raw_payload->>'race_no' ~ '^(0[1-9]|1[0-2])$'
     AND s.source_record_key=jsonb_build_object(
       'kaisai_nen',s.raw_payload->>'kaisai_nen','kaisai_tsukihi',s.raw_payload->>'kaisai_tsukihi',
       'kyoteijo_code',s.raw_payload->>'kyoteijo_code','race_no',s.raw_payload->>'race_no')
   GROUP BY s.raw_payload->>'kaisai_nen',s.raw_payload->>'kaisai_tsukihi',
            s.raw_payload->>'kyoteijo_code',s.raw_payload->>'race_no'
   HAVING count(*)=1
 )
 INSERT INTO core.race_environment_preinfo(race_id,source_record_id,provenance)
 SELECT r.race_id,e.source_record_id,'{}'::jsonb
 FROM eligible e JOIN core.race r
  ON r.race_date=to_date(e.y || e.md,'YYYYMMDD')
  AND r.venue_code=e.venue::smallint AND r.race_no=e.race_no::smallint
 WHERE NOT EXISTS (SELECT 1 FROM core.race_environment_preinfo existing
                   WHERE existing.race_id=r.race_id)
 ON CONFLICT DO NOTHING;
 GET DIAGNOSTICS inserted_count = ROW_COUNT;
 RETURN inserted_count;
END;
$$;

CREATE OR REPLACE FUNCTION core.backfill_race_boat_preinfo_v1(
    p_source_batch_id bigint DEFAULT NULL)
RETURNS bigint LANGUAGE plpgsql AS $$
DECLARE inserted_count bigint;
BEGIN
 IF EXISTS (
   WITH candidate AS MATERIALIZED (
     SELECT s.source_record_id,s.raw_payload
     FROM raw.source_record s JOIN raw.source_batch b USING(source_batch_id)
     WHERE b.source_table='brd_c3'
       AND (p_source_batch_id IS NULL OR s.source_batch_id=p_source_batch_id)
       AND s.raw_payload->>'kaisai_nen' ~ '^[0-9]{4}$'
       AND s.raw_payload->>'kaisai_tsukihi' ~ '^[0-9]{4}$'
       AND s.raw_payload->>'kyoteijo_code' ~ '^(0[1-9]|1[0-9]|2[0-4])$'
       AND s.raw_payload->>'race_no' ~ '^(0[1-9]|1[0-2])$'
       AND s.raw_payload->>'teiban' ~ '^[1-6]$'
   )
   SELECT 1 FROM candidate c
   JOIN core.race r
     ON r.race_date=to_date((c.raw_payload->>'kaisai_nen') ||
                            (c.raw_payload->>'kaisai_tsukihi'),'YYYYMMDD')
    AND r.venue_code=(c.raw_payload->>'kyoteijo_code')::smallint
    AND r.race_no=(c.raw_payload->>'race_no')::smallint
   JOIN core.race_boat_preinfo p
     ON p.race_id=r.race_id AND p.boat_no=(c.raw_payload->>'teiban')::smallint
   WHERE p.source_record_id<>c.source_record_id
 ) THEN RAISE EXCEPTION 'C3 canonical source conflict'; END IF;
 WITH eligible AS (
   SELECT min(s.source_record_id) AS source_record_id,
          s.raw_payload->>'kaisai_nen' AS y,s.raw_payload->>'kaisai_tsukihi' AS md,
          s.raw_payload->>'kyoteijo_code' AS venue,s.raw_payload->>'race_no' AS race_no,
          s.raw_payload->>'teiban' AS boat
   FROM raw.source_record s JOIN raw.source_batch b USING(source_batch_id)
   WHERE b.source_table='brd_c3' AND s.raw_payload->>'kaisai_nen'>='2017'
     AND (p_source_batch_id IS NULL OR s.source_batch_id=p_source_batch_id)
     AND s.raw_payload->>'kaisai_nen' ~ '^[0-9]{4}$'
     AND s.raw_payload->>'kaisai_tsukihi' ~ '^[0-9]{4}$'
     AND s.raw_payload->>'kyoteijo_code' ~ '^(0[1-9]|1[0-9]|2[0-4])$'
     AND s.raw_payload->>'race_no' ~ '^(0[1-9]|1[0-2])$'
     AND btrim(coalesce(s.raw_payload->>'teiban','')) ~ '^[1-6]$'
     AND s.source_record_key=jsonb_build_object(
       'kaisai_nen',s.raw_payload->>'kaisai_nen','kaisai_tsukihi',s.raw_payload->>'kaisai_tsukihi',
       'kyoteijo_code',s.raw_payload->>'kyoteijo_code','race_no',s.raw_payload->>'race_no',
       'teiban',s.raw_payload->>'teiban')
   GROUP BY s.raw_payload->>'kaisai_nen',s.raw_payload->>'kaisai_tsukihi',
            s.raw_payload->>'kyoteijo_code',s.raw_payload->>'race_no',s.raw_payload->>'teiban'
   HAVING count(*)=1
 )
 INSERT INTO core.race_boat_preinfo(race_id,boat_no,source_record_id,provenance)
 SELECT r.race_id,btrim(e.boat)::smallint,e.source_record_id,'{}'::jsonb
 FROM eligible e JOIN core.race r
   ON r.race_date=to_date(e.y || e.md,'YYYYMMDD')
  AND r.venue_code=e.venue::smallint AND r.race_no=e.race_no::smallint
 JOIN core.race_entry re ON re.race_id=r.race_id AND re.boat_no=btrim(e.boat)::smallint
 WHERE NOT EXISTS (SELECT 1 FROM core.race_boat_preinfo existing
                   WHERE existing.race_id=r.race_id AND existing.boat_no=btrim(e.boat)::smallint)
 ON CONFLICT DO NOTHING;
 GET DIAGNOSTICS inserted_count = ROW_COUNT;
 RETURN inserted_count;
END;
$$;

CREATE OR REPLACE VIEW core.race_environment_preinfo_status AS
SELECT r.race_id,r.race_date,r.venue_code,r.race_no,
       CASE WHEN p.race_id IS NULL THEN 'MISSING_SOURCE' ELSE 'AVAILABLE' END AS coverage_status,
       p.air_temperature_raw,p.air_temperature_c,p.air_temperature_status,
       p.water_temperature_raw,p.water_temperature_c,p.water_temperature_status,
       p.weather_code_raw,p.weather_code,p.weather_status,
       p.wind_direction_code_raw,p.wind_direction_code,p.wind_direction_status,
       p.venue_direction_code_raw,p.venue_direction_code,p.venue_direction_status,
       p.wind_speed_raw,p.wind_speed_status,p.wave_height_raw,p.wave_height_status,
       p.surface_weather_marker_raw,p.surface_weather_marker_status,
       p.source_record_id,s.source_batch_id,s.source_record_key,s.record_hash,
       b.content_hash AS source_batch_hash,b.source_locator,b.retrieved_at,b.extracted_at,b.ingested_at,
       p.normalization_version,p.provenance
FROM core.race r
LEFT JOIN core.race_environment_preinfo p USING(race_id)
LEFT JOIN raw.source_record s ON s.source_record_id=p.source_record_id
LEFT JOIN raw.source_batch b ON b.source_batch_id=s.source_batch_id;

CREATE OR REPLACE VIEW core.race_boat_preinfo_status AS
SELECT r.race_id,r.race_date,r.venue_code,r.race_no,e.boat_no,
       CASE WHEN p.race_id IS NULL THEN 'MISSING_SOURCE' ELSE 'AVAILABLE' END AS coverage_status,
       p.exhibition_time_raw,p.exhibition_time_seconds,p.exhibition_time_status,
       p.tilt_raw,p.tilt_degrees,p.tilt_status,
       p.exhibition_course_raw,p.exhibition_course,p.exhibition_course_status,
       p.exhibition_start_timing_raw,p.exhibition_start_symbol_raw,
       p.exhibition_start_timing,p.exhibition_start_status,
       p.source_record_id,s.source_batch_id,s.source_record_key,s.record_hash,
       b.content_hash AS source_batch_hash,b.source_locator,b.retrieved_at,b.extracted_at,b.ingested_at,
       p.normalization_version,p.provenance
FROM core.race_entry e JOIN core.race r USING(race_id)
LEFT JOIN core.race_boat_preinfo p USING(race_id,boat_no)
LEFT JOIN raw.source_record s ON s.source_record_id=p.source_record_id
LEFT JOIN raw.source_batch b ON b.source_batch_id=s.source_batch_id;

-- This is metadata only. It neither reads nor canonicalizes C4 values.
CREATE OR REPLACE VIEW core.c4_field_structural_status AS
SELECT v.venue_code,f.source_field,
       CASE WHEN (v.venue_code=1 AND f.source_field='isshu')
                  OR v.venue_code=3
                  OR (v.venue_code IN (12,13,18) AND f.source_field='chokusen')
            THEN 'STRUCTURALLY_NOT_PROVIDED' ELSE 'UNRESOLVED' END AS structural_status,
       'environment_preinfo_source_inventory_v1'::text AS source_basis
FROM core.venue v
CROSS JOIN (VALUES ('isshu'),('hanshu'),('mawariashi'),('chokusen')) AS f(source_field);
