-- Preserve C3 part-change observations at race x boat x source-field grain.
-- The source codes establish that an exchange was reported, but do not establish
-- a quantity.  In particular, no positive code is converted to quantity = 1.

CREATE OR REPLACE FUNCTION core.part_change_type_v1(value text)
RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
 SELECT CASE value
   WHEN 'propeller' THEN 'PROPELLER'
   WHEN 'piston' THEN 'PISTON'
   WHEN 'piston_ring' THEN 'PISTON_RING'
   WHEN 'denki_isshiki' THEN 'DENKI_ISSHIKI'
   WHEN 'carburetor' THEN 'CARBURETOR'
   WHEN 'cylinder' THEN 'CYLINDER'
   WHEN 'crankshaft' THEN 'CRANKSHAFT'
   WHEN 'gearcase' THEN 'GEARCASE'
   WHEN 'careerbody' THEN 'CAREERBODY'
   ELSE NULL END
$$;

CREATE OR REPLACE FUNCTION core.part_change_status_v1(source_field text, value jsonb)
RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
 SELECT CASE
   WHEN core.part_change_type_v1(source_field) IS NULL THEN 'UNRESOLVED_TYPE'
   WHEN value IS NULL OR value = 'null'::jsonb OR btrim(value #>> '{}') = ''
     THEN 'UNRESOLVED_BLANK'
   WHEN source_field = 'piston' AND value IN (to_jsonb('1'::text),to_jsonb('2'::text))
     THEN 'UNRESOLVED_QUANTITY'
   WHEN source_field = 'piston_ring' AND value IN (
     to_jsonb('1'::text),to_jsonb('2'::text),to_jsonb('3'::text),to_jsonb('4'::text))
     THEN 'UNRESOLVED_QUANTITY'
   WHEN source_field NOT IN ('piston','piston_ring') AND value = to_jsonb('1'::text)
     THEN 'UNRESOLVED_QUANTITY'
   ELSE 'UNRESOLVED_VALUE' END
$$;

CREATE TABLE IF NOT EXISTS core.race_boat_part_change (
    part_change_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    race_id bigint NOT NULL,
    boat_no smallint NOT NULL CHECK (boat_no BETWEEN 1 AND 6),
    part_type_raw text NOT NULL,
    part_type text,
    source_field text NOT NULL,
    ordinal smallint NOT NULL DEFAULT 1 CHECK (ordinal > 0),
    raw_value jsonb,
    quantity_raw text,
    quantity integer,
    status text NOT NULL CHECK (status IN (
      'UNRESOLVED_TYPE','UNRESOLVED_QUANTITY','UNRESOLVED_BLANK','UNRESOLVED_VALUE')),
    source_record_id bigint NOT NULL REFERENCES raw.source_record,
    normalization_version text NOT NULL DEFAULT 'phase3d-part-change-v1'
      CHECK (normalization_version = 'phase3d-part-change-v1'),
    provenance jsonb NOT NULL CHECK (jsonb_typeof(provenance) = 'object'),
    FOREIGN KEY (race_id,boat_no) REFERENCES core.race_entry,
    UNIQUE (source_record_id,source_field,ordinal),
    CHECK (quantity IS NULL),
    CHECK (part_type IS NULL OR part_type IN (
      'PROPELLER','PISTON','PISTON_RING','DENKI_ISSHIKI','CARBURETOR',
      'CYLINDER','CRANKSHAFT','GEARCASE','CAREERBODY'))
);

CREATE INDEX IF NOT EXISTS race_boat_part_change_race_boat_idx
ON core.race_boat_part_change(race_id,boat_no);
CREATE INDEX IF NOT EXISTS race_boat_part_change_part_type_idx
ON core.race_boat_part_change(part_type);
CREATE INDEX IF NOT EXISTS race_boat_part_change_status_idx
ON core.race_boat_part_change(status);

CREATE OR REPLACE FUNCTION core.load_race_boat_part_change_v1()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
  payload jsonb;
  raw_key jsonb;
  source_table_name text;
  source_version text;
  race_row core.race%ROWTYPE;
BEGIN
 SELECT s.raw_payload,s.source_record_key,b.source_table,b.extraction_condition->>'version'
 INTO payload,raw_key,source_table_name,source_version
 FROM raw.source_record s JOIN raw.source_batch b USING(source_batch_id)
 WHERE s.source_record_id=NEW.source_record_id;
 SELECT * INTO race_row FROM core.race WHERE race_id=NEW.race_id;

 IF source_table_name IS DISTINCT FROM 'brd_c3'
    OR source_version IS DISTINCT FROM 'phase3c-environment-preinfo-v1'
    OR payload->>'kaisai_nen' IS DISTINCT FROM to_char(race_row.race_date,'YYYY')
    OR payload->>'kaisai_tsukihi' IS DISTINCT FROM to_char(race_row.race_date,'MMDD')
    OR payload->>'kyoteijo_code' IS DISTINCT FROM lpad(race_row.venue_code::text,2,'0')
    OR payload->>'race_no' IS DISTINCT FROM lpad(race_row.race_no::text,2,'0')
    OR nullif(btrim(payload->>'teiban'),'')::smallint IS DISTINCT FROM NEW.boat_no
    OR raw_key IS DISTINCT FROM jsonb_build_object(
       'kaisai_nen',payload->>'kaisai_nen','kaisai_tsukihi',payload->>'kaisai_tsukihi',
       'kyoteijo_code',payload->>'kyoteijo_code','race_no',payload->>'race_no',
       'teiban',payload->>'teiban')
    OR NEW.source_field NOT IN ('propeller','piston','piston_ring','denki_isshiki',
       'carburetor','cylinder','crankshaft','gearcase','careerbody')
    OR NOT payload ? NEW.source_field
    OR payload->NEW.source_field = to_jsonb('0'::text)
    OR NEW.ordinal <> 1 THEN
   RAISE EXCEPTION 'C3 part-change source identity mismatch';
 END IF;

 NEW.part_type_raw := NEW.source_field;
 NEW.part_type := core.part_change_type_v1(NEW.source_field);
 NEW.raw_value := payload->NEW.source_field;
 NEW.quantity_raw := payload->>NEW.source_field;
 NEW.quantity := NULL;
 NEW.status := core.part_change_status_v1(NEW.source_field,payload->NEW.source_field);
 NEW.normalization_version := 'phase3d-part-change-v1';
 NEW.provenance := jsonb_build_object(
   'normalization_version','phase3d-part-change-v1',
   'source_table','brd_c3',
   'source_field',NEW.source_field,
   'source_code_semantics','PART_EXCHANGE_CODE',
   'quantity_semantics','UNRESOLVED',
   'information_kind','PRE_RACE_SOURCE_CLASS',
   'historical_availability_status','SOURCE_CLASS_POLICY_NOT_EXACT_AS_OF_PROOF',
   'result_dependency',false,
   'boat_identity_field','teiban');
 RETURN NEW;
EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range THEN
 RAISE EXCEPTION 'C3 part-change source identity mismatch';
END;
$$;

DROP TRIGGER IF EXISTS load_race_boat_part_change ON core.race_boat_part_change;
CREATE TRIGGER load_race_boat_part_change
BEFORE INSERT OR UPDATE ON core.race_boat_part_change
FOR EACH ROW EXECUTE FUNCTION core.load_race_boat_part_change_v1();

CREATE OR REPLACE FUNCTION core.backfill_race_boat_part_change_v1(
    p_source_batch_id bigint DEFAULT NULL)
RETURNS bigint LANGUAGE plpgsql AS $$
DECLARE inserted_count bigint;
BEGIN
 WITH candidate AS (
   SELECT s.source_record_id,s.raw_payload,p.source_field,p.raw_value
   FROM raw.source_record s
   JOIN raw.source_batch b USING(source_batch_id)
   CROSS JOIN LATERAL (VALUES
     ('propeller',s.raw_payload->'propeller'),
     ('piston',s.raw_payload->'piston'),
     ('piston_ring',s.raw_payload->'piston_ring'),
     ('denki_isshiki',s.raw_payload->'denki_isshiki'),
     ('carburetor',s.raw_payload->'carburetor'),
     ('cylinder',s.raw_payload->'cylinder'),
     ('crankshaft',s.raw_payload->'crankshaft'),
     ('gearcase',s.raw_payload->'gearcase'),
     ('careerbody',s.raw_payload->'careerbody')
   ) AS p(source_field,raw_value)
   WHERE b.source_table='brd_c3'
     AND b.extraction_condition->>'version'='phase3c-environment-preinfo-v1'
     AND (p_source_batch_id IS NULL OR s.source_batch_id=p_source_batch_id)
     AND s.raw_payload->>'kaisai_nen'>='2017'
     AND s.raw_payload->>'kaisai_nen' ~ '^[0-9]{4}$'
     AND s.raw_payload->>'kaisai_tsukihi' ~ '^[0-9]{4}$'
     AND s.raw_payload->>'kyoteijo_code' ~ '^(0[1-9]|1[0-9]|2[0-4])$'
     AND s.raw_payload->>'race_no' ~ '^(0[1-9]|1[0-2])$'
     AND btrim(coalesce(s.raw_payload->>'teiban','')) ~ '^[1-6]$'
     AND s.source_record_key=jsonb_build_object(
       'kaisai_nen',s.raw_payload->>'kaisai_nen','kaisai_tsukihi',s.raw_payload->>'kaisai_tsukihi',
       'kyoteijo_code',s.raw_payload->>'kyoteijo_code','race_no',s.raw_payload->>'race_no',
       'teiban',s.raw_payload->>'teiban')
     AND s.raw_payload ? p.source_field
     -- Only the documented initial code is omitted. Blank and invalid values
     -- remain first-class unresolved rows.
     AND p.raw_value IS DISTINCT FROM to_jsonb('0'::text)
 )
 INSERT INTO core.race_boat_part_change(
   race_id,boat_no,part_type_raw,source_field,ordinal,source_record_id,provenance,status)
 SELECT r.race_id,btrim(c.raw_payload->>'teiban')::smallint,c.source_field,
        c.source_field,1,c.source_record_id,'{}'::jsonb,'UNRESOLVED_VALUE'
 FROM candidate c
 JOIN core.race r
   ON r.race_date=to_date((c.raw_payload->>'kaisai_nen') ||
                          (c.raw_payload->>'kaisai_tsukihi'),'YYYYMMDD')
  AND r.venue_code=(c.raw_payload->>'kyoteijo_code')::smallint
  AND r.race_no=(c.raw_payload->>'race_no')::smallint
 JOIN core.race_entry e
   ON e.race_id=r.race_id AND e.boat_no=btrim(c.raw_payload->>'teiban')::smallint
 ON CONFLICT (source_record_id,source_field,ordinal) DO NOTHING;
 GET DIAGNOSTICS inserted_count = ROW_COUNT;
 RETURN inserted_count;
END;
$$;

CREATE OR REPLACE VIEW core.race_boat_part_change_lineage AS
SELECT p.part_change_id,p.race_id,r.race_date,r.venue_code,r.race_no,p.boat_no,
       p.part_type_raw,p.part_type,p.source_field,p.ordinal,p.raw_value,
       p.quantity_raw,p.quantity,p.status,p.source_record_id,s.source_batch_id,
       s.source_record_key,s.record_hash,b.content_hash AS source_batch_hash,
       b.source_locator,b.retrieved_at,b.extracted_at,b.ingested_at,
       p.normalization_version,p.provenance
FROM core.race_boat_part_change p
JOIN core.race r USING(race_id)
JOIN raw.source_record s ON s.source_record_id=p.source_record_id
JOIN raw.source_batch b ON b.source_batch_id=s.source_batch_id;
