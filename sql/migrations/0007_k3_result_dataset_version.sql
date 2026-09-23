-- Versioned metadata for the adopted K3-only result population.
-- Older frozen core.dataset_version rows remain immutable historical artifacts.
CREATE TABLE core.result_dataset_version (
    version_id text PRIMARY KEY,
    authoritative_source text NOT NULL CHECK (authoritative_source='brd_k3'),
    date_start date NOT NULL,
    date_end date NOT NULL,
    source_manifest jsonb NOT NULL,
    source_manifest_hash text NOT NULL CHECK (source_manifest_hash ~ '^[0-9a-f]{64}$'),
    normalization_version text NOT NULL,
    result_races bigint NOT NULL CHECK (result_races>=0),
    result_boats bigint NOT NULL CHECK (result_boats>=0),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK (date_start<=date_end)
);
CREATE TRIGGER immutable_result_dataset_version
BEFORE UPDATE OR DELETE OR TRUNCATE ON core.result_dataset_version
FOR EACH STATEMENT EXECUTE FUNCTION raw.reject_mutation();
