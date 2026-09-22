-- Additive and reapplicable. Populate existing entries with scripts.national_win_rate.
-- PC-KYOTEI PDF p.1: four characters, 0580 = 5.80. Zero meaning unresolved.
CREATE OR REPLACE FUNCTION core.l3_national_rate_status_v1(value text)
RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
 SELECT CASE WHEN value IS NULL OR btrim(value) = '' THEN 'MISSING'
             WHEN value = '0000' THEN 'UNRESOLVED'
             WHEN value ~ '^[0-9]{4}$' THEN 'VALID'
             ELSE 'INVALID' END
$$;
CREATE OR REPLACE FUNCTION core.l3_national_rate_value_v1(value text)
RETURNS numeric LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
 SELECT CASE WHEN core.l3_national_rate_status_v1(value) = 'VALID'
             THEN value::numeric / 100 ELSE NULL END
$$;
ALTER TABLE core.race_entry
 ADD COLUMN IF NOT EXISTS national_win_rate_raw text,
 ADD COLUMN IF NOT EXISTS national_win_rate numeric(4,2)
 GENERATED ALWAYS AS (core.l3_national_rate_value_v1(national_win_rate_raw)) STORED,
 ADD COLUMN IF NOT EXISTS national_win_rate_status text
 GENERATED ALWAYS AS (core.l3_national_rate_status_v1(national_win_rate_raw)) STORED;

CREATE OR REPLACE FUNCTION core.entry_l3_national_rate_v1()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE payload jsonb; raw_key jsonb; source_table_name text; race_row core.race%ROWTYPE;
BEGIN
 SELECT s.raw_payload,s.source_record_key,b.source_table INTO payload,raw_key,source_table_name
 FROM raw.source_record s JOIN raw.source_batch b USING(source_batch_id)
 WHERE s.source_record_id=NEW.source_record_id;
 SELECT * INTO race_row FROM core.race WHERE race_id=NEW.race_id;
 IF source_table_name IS DISTINCT FROM 'brd_l3'
    OR payload->>'kaisai_nen' IS DISTINCT FROM to_char(race_row.race_date,'YYYY')
    OR payload->>'kaisai_tsukihi' IS DISTINCT FROM to_char(race_row.race_date,'MMDD')
    OR payload->>'kyoteijo_code' IS DISTINCT FROM lpad(race_row.venue_code::text,2,'0')
    OR payload->>'race_no' IS DISTINCT FROM lpad(race_row.race_no::text,2,'0')
    OR payload->>'teiban' IS DISTINCT FROM NEW.boat_no::text
    OR payload->>'toroku_bango' IS DISTINCT FROM lpad(NEW.player_id::text,4,'0')
    OR raw_key IS DISTINCT FROM jsonb_build_object(
        'kaisai_nen',payload->>'kaisai_nen','kaisai_tsukihi',payload->>'kaisai_tsukihi',
        'kyoteijo_code',payload->>'kyoteijo_code','race_no',payload->>'race_no',
        'teiban',payload->>'teiban') THEN
   RAISE EXCEPTION 'L3 entry source identity mismatch';
 END IF;
 NEW.national_win_rate_raw := payload->>'zenkoku_ritsu_1';
 RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS entry_l3_national_rate ON core.race_entry;
CREATE TRIGGER entry_l3_national_rate BEFORE INSERT OR UPDATE ON core.race_entry
FOR EACH ROW EXECUTE FUNCTION core.entry_l3_national_rate_v1();

-- A parent correction must not silently change the meaning of adopted L3 values.
CREATE OR REPLACE FUNCTION core.race_l3_identity_v1()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF (NEW.race_date,NEW.venue_code,NEW.race_no) IS DISTINCT FROM
    (OLD.race_date,OLD.venue_code,OLD.race_no)
    AND EXISTS (SELECT 1 FROM core.race_entry WHERE race_id=OLD.race_id) THEN
   RAISE EXCEPTION 'race identity with adopted L3 entries cannot be changed';
 END IF;
 RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS race_l3_identity ON core.race;
CREATE TRIGGER race_l3_identity BEFORE UPDATE ON core.race
FOR EACH ROW EXECUTE FUNCTION core.race_l3_identity_v1();

CREATE OR REPLACE VIEW core.race_entry_national_win_rate AS
 SELECT e.race_id,r.race_date,r.venue_code,r.race_no,e.boat_no,
        e.player_id AS registration_no,e.national_win_rate_raw,
        e.national_win_rate,e.national_win_rate_status,
        e.source_record_id,s.source_batch_id,s.source_record_key,s.record_hash,
        b.source_table,b.content_hash AS source_batch_hash,b.retrieved_at,
        b.extracted_at,b.ingested_at,
        'l3-national-rate-v1'::text AS normalization_version,
        'RACE_ENTRY_INFORMATION'::text AS information_kind,
        'NOT_VERIFIED'::text AS historical_availability_status,
        'zenkoku_ritsu_1'::text AS source_field
 FROM core.race_entry e JOIN core.race r USING(race_id)
 JOIN raw.source_record s ON s.source_record_id=e.source_record_id
 JOIN raw.source_batch b USING(source_batch_id);
