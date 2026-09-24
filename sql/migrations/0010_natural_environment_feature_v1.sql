-- Race-grain, source-preserving environment observations. The pre-holdout
-- builder populates only 2017-2024; a later holdout task may append rows.
CREATE TABLE core.natural_environment_feature_v1 (
    race_id bigint PRIMARY KEY REFERENCES core.race,
    race_date date NOT NULL,
    venue_code smallint NOT NULL,
    race_no smallint NOT NULL,
    l2_deadline_raw text NOT NULL,
    c2_record_id_raw text,
    hogaku_code_raw text,
    fuko_code_raw text,
    fusoku_raw text,
    tenki_code_raw text,
    kion_raw text,
    wind_relative_d smallint CHECK (wind_relative_d BETWEEN 0 AND 15),
    wind_category text NOT NULL,
    wind_speed_m double precision,
    weather text NOT NULL,
    air_temperature_c double precision,
    tide_source_available boolean NOT NULL,
    tide_chiten_code text,
    tide_height double precision,
    tide_direction text,
    tide_change_speed double precision,
    tide_status text NOT NULL,
    tide_unresolved_reason text,
    tide_extrema_lineage jsonb NOT NULL,
    source_provenance jsonb NOT NULL,
    CHECK ((tide_status = 'NOT_APPLICABLE') = (NOT tide_source_available)),
    CHECK ((tide_status = 'AVAILABLE') = (tide_height IS NOT NULL)),
    CHECK ((tide_status = 'AVAILABLE') = (tide_change_speed IS NOT NULL))
);
CREATE INDEX natural_environment_feature_v1_date_idx
    ON core.natural_environment_feature_v1(race_date);
