-- Keep the same generation-period invariant when parent rows are corrected.
CREATE FUNCTION core.check_motor_parent_period() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_TABLE_NAME = 'race' THEN
        IF EXISTS (
            SELECT 1 FROM core.race_entry e JOIN core.motor m USING(motor_id)
            WHERE e.race_id=NEW.race_id AND
              (NEW.race_date < m.generation_start_date OR NEW.race_date >= m.generation_end_date)
        ) THEN RAISE EXCEPTION 'race correction outside referenced motor period'; END IF;
    ELSE
        IF EXISTS (
            SELECT 1 FROM core.race_entry e JOIN core.race r USING(race_id)
            WHERE e.motor_id=NEW.motor_id AND
              (r.race_date < NEW.generation_start_date OR r.race_date >= NEW.generation_end_date)
        ) THEN RAISE EXCEPTION 'motor correction excludes referenced race'; END IF;
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER race_motor_period BEFORE UPDATE OF race_date ON core.race
FOR EACH ROW EXECUTE FUNCTION core.check_motor_parent_period();
CREATE TRIGGER motor_race_period BEFORE UPDATE OF generation_start_date,generation_end_date ON core.motor
FOR EACH ROW EXECUTE FUNCTION core.check_motor_parent_period();

-- A correction belongs in a NEW batch; completed batch hashes/counts stay valid.
CREATE FUNCTION raw.check_record_position() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM raw.source_batch b WHERE b.source_batch_id=NEW.source_batch_id
                   AND NEW.source_position <= b.row_count) THEN
        RAISE EXCEPTION 'record position exceeds immutable batch row count';
    END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER record_batch_position BEFORE INSERT ON raw.source_record
FOR EACH ROW EXECUTE FUNCTION raw.check_record_position();

CREATE FUNCTION raw.check_batch_complete() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF (SELECT count(*) FROM raw.source_record WHERE source_batch_id=NEW.source_batch_id) <> NEW.row_count THEN
        RAISE EXCEPTION 'incomplete source batch';
    END IF;
    RETURN NULL;
END;
$$;
CREATE CONSTRAINT TRIGGER batch_complete AFTER INSERT ON raw.source_batch
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION raw.check_batch_complete();
