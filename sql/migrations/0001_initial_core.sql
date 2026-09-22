-- Apply once to an empty database inside a transaction. No legacy dependencies.
CREATE SCHEMA raw;
CREATE SCHEMA core;

CREATE TABLE raw.source_batch (
    source_batch_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_name text NOT NULL,
    source_type text NOT NULL,
    source_locator text NOT NULL,
    extraction_condition jsonb NOT NULL,
    source_database text,
    source_schema text,
    source_table text,
    retrieved_at timestamptz,
    extracted_at timestamptz NOT NULL,
    ingested_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    content_hash text NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    row_count integer NOT NULL CHECK (row_count >= 0),
    metadata jsonb NOT NULL,
    status text NOT NULL
);
CREATE TABLE raw.source_record (
    source_record_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_batch_id bigint NOT NULL REFERENCES raw.source_batch,
    source_record_key jsonb NOT NULL,
    source_race_id text,
    source_position integer NOT NULL CHECK (source_position > 0),
    raw_payload jsonb NOT NULL CHECK (jsonb_typeof(raw_payload) = 'object'),
    record_hash text NOT NULL CHECK (record_hash ~ '^[0-9a-f]{64}$'),
    interpretation_status text NOT NULL,
    UNIQUE (source_batch_id, source_position)
);
CREATE INDEX source_record_hash_idx ON raw.source_record(record_hash);

CREATE TABLE core.venue (
    venue_code smallint PRIMARY KEY CHECK (venue_code BETWEEN 1 AND 24),
    venue_name text NOT NULL UNIQUE
);
CREATE TABLE core.player (
    player_id integer PRIMARY KEY CHECK (player_id > 0),
    player_name_raw text,
    sex_raw text,
    sex text CHECK (sex IN ('MALE', 'FEMALE')),
    sex_normalization_status text NOT NULL,
    training_class_raw text,
    training_class integer CHECK (training_class > 0),
    source_record_id bigint NOT NULL REFERENCES raw.source_record,
    sex_source_record_id bigint REFERENCES raw.source_record,
    provenance jsonb NOT NULL,
    CHECK (sex IS NULL OR sex_source_record_id IS NOT NULL)
);
CREATE TABLE core.race (
    race_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    race_date date NOT NULL,
    venue_code smallint NOT NULL REFERENCES core.venue,
    race_no smallint NOT NULL CHECK (race_no BETWEEN 1 AND 12),
    grade_raw text,
    grade text,
    women_only_derived boolean,
    women_only_status text NOT NULL,
    women_only_basis jsonb NOT NULL,
    entry_fixed_source boolean,
    entry_fixed_effective boolean,
    entry_fixed_basis text NOT NULL,
    stabilizer_source boolean,
    stabilizer_available_for_prediction boolean,
    race_status text NOT NULL,
    source_record_id bigint NOT NULL REFERENCES raw.source_record,
    grade_source_record_id bigint REFERENCES raw.source_record,
    provenance jsonb NOT NULL,
    UNIQUE (race_date, venue_code, race_no),
    UNIQUE (race_id, venue_code),
    CHECK ((women_only_derived IS NULL) = (women_only_status = 'UNKNOWN'))
);
CREATE TABLE core.motor (
    motor_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    venue_code smallint NOT NULL REFERENCES core.venue,
    generation_start_year integer NOT NULL,
    generation_start_date date NOT NULL,
    generation_end_date date NOT NULL,
    motor_no integer NOT NULL CHECK (motor_no > 0),
    identity_rule_version text NOT NULL,
    source_record_id bigint NOT NULL REFERENCES raw.source_record,
    provenance jsonb NOT NULL,
    UNIQUE (venue_code, generation_start_year, motor_no),
    UNIQUE (motor_id, venue_code),
    CHECK (generation_start_date < generation_end_date),
    CHECK (extract(year FROM generation_start_date) = generation_start_year)
);
CREATE TABLE core.race_entry (
    race_id bigint NOT NULL,
    boat_no smallint NOT NULL CHECK (boat_no BETWEEN 1 AND 6),
    venue_code smallint NOT NULL,
    player_id integer NOT NULL REFERENCES core.player,
    motor_id bigint,
    motor_no_raw text,
    f_count_current_term_raw text,
    f_count_current_term integer CHECK (f_count_current_term >= 0),
    l_count_current_term_raw text,
    source_record_id bigint NOT NULL REFERENCES raw.source_record,
    provenance jsonb NOT NULL,
    PRIMARY KEY (race_id, boat_no),
    FOREIGN KEY (race_id, venue_code) REFERENCES core.race (race_id, venue_code),
    FOREIGN KEY (motor_id, venue_code) REFERENCES core.motor (motor_id, venue_code)
);
CREATE TABLE core.race_result (
    race_id bigint NOT NULL,
    boat_no smallint NOT NULL,
    actual_course_raw text,
    actual_course smallint CHECK (actual_course BETWEEN 1 AND 6),
    finish_raw text,
    finish_position smallint CHECK (finish_position BETWEEN 1 AND 6),
    result_status text NOT NULL,
    result_symbol_raw text,
    start_timing_raw text,
    start_timing numeric(6,3),
    start_timing_status text NOT NULL,
    normalization_status text NOT NULL,
    normalization_version text NOT NULL,
    source_record_id bigint NOT NULL REFERENCES raw.source_record,
    provenance jsonb NOT NULL,
    PRIMARY KEY (race_id, boat_no),
    FOREIGN KEY (race_id, boat_no) REFERENCES core.race_entry,
    CHECK (start_timing_status = 'NORMAL' OR start_timing IS NULL),
    CHECK (start_timing IS NULL OR start_timing >= 0),
    CHECK ((result_status = 'NORMAL') = (finish_position IS NOT NULL))
);
CREATE TABLE core.dataset_version (
    dataset_version_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    dataset_name text NOT NULL,
    dataset_type text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    date_start date NOT NULL,
    date_end date NOT NULL,
    effective_date date NOT NULL,
    results_cutoff_date date NOT NULL,
    source_manifest jsonb NOT NULL,
    normalization_version text NOT NULL,
    selection_rule_version text NOT NULL,
    row_counts jsonb NOT NULL,
    missing_excluded_summary jsonb NOT NULL,
    canonical_snapshot jsonb NOT NULL,
    canonical_content_hash text NOT NULL CHECK (canonical_content_hash ~ '^[0-9a-f]{64}$'),
    manifest_locator text NOT NULL,
    manifest_hash text NOT NULL CHECK (manifest_hash ~ '^[0-9a-f]{64}$'),
    status text NOT NULL,
    CHECK (date_start <= date_end),
    CHECK (results_cutoff_date = effective_date - 1),
    CHECK (date_end <= results_cutoff_date)
);

-- Source revisions and fixed datasets are appended, never overwritten.
CREATE FUNCTION raw.reject_mutation() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'immutable table: %', TG_TABLE_NAME;
END;
$$;
CREATE TRIGGER immutable_batch BEFORE UPDATE OR DELETE OR TRUNCATE ON raw.source_batch
FOR EACH STATEMENT EXECUTE FUNCTION raw.reject_mutation();
CREATE TRIGGER immutable_record BEFORE UPDATE OR DELETE OR TRUNCATE ON raw.source_record
FOR EACH STATEMENT EXECUTE FUNCTION raw.reject_mutation();
CREATE TRIGGER immutable_dataset BEFORE UPDATE OR DELETE OR TRUNCATE ON core.dataset_version
FOR EACH STATEMENT EXECUTE FUNCTION raw.reject_mutation();

-- The composite FKs enforce venue identity. Validate the half-open period too.
CREATE FUNCTION core.check_motor_period() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.motor_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM core.motor m JOIN core.race r ON r.race_id = NEW.race_id
        WHERE m.motor_id = NEW.motor_id AND r.race_date >= m.generation_start_date
          AND r.race_date < m.generation_end_date
    ) THEN RAISE EXCEPTION 'motor outside generation period'; END IF;
    RETURN NEW;
END;
$$;
CREATE TRIGGER entry_motor_period BEFORE INSERT OR UPDATE ON core.race_entry
FOR EACH ROW EXECUTE FUNCTION core.check_motor_period();
