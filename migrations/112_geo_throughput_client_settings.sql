-- 112_geo_throughput_client_settings.sql
-- Client-level prompt expansion controls and Analyzer lookup acceleration.
--
-- batch_id remains an Asia/Shanghai business-date string in YYYY-MM-DD format.
-- This migration intentionally does not add a collector_run_id. Same-day
-- Collector reruns are isolated by batch_id + analyzed_at IS NULL.

BEGIN;

ALTER TABLE geo_clients
    ADD COLUMN IF NOT EXISTS reuse_latest_final_prompt boolean,
    ADD COLUMN IF NOT EXISTS country_localization_mode text,
    ADD COLUMN IF NOT EXISTS final_prompt_per_client_prompt integer,
    ADD COLUMN IF NOT EXISTS default_calls_per_prompt integer;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
          FROM pg_constraint
         WHERE conname = 'geo_clients_country_localization_mode_chk'
    ) THEN
        ALTER TABLE geo_clients
            ADD CONSTRAINT geo_clients_country_localization_mode_chk
            CHECK (
                country_localization_mode IS NULL
                OR country_localization_mode IN ('generic', 'localized_by_country')
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1
          FROM pg_constraint
         WHERE conname = 'geo_clients_final_prompt_per_client_prompt_chk'
    ) THEN
        ALTER TABLE geo_clients
            ADD CONSTRAINT geo_clients_final_prompt_per_client_prompt_chk
            CHECK (
                final_prompt_per_client_prompt IS NULL
                OR final_prompt_per_client_prompt >= 1
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1
          FROM pg_constraint
         WHERE conname = 'geo_clients_default_calls_per_prompt_chk'
    ) THEN
        ALTER TABLE geo_clients
            ADD CONSTRAINT geo_clients_default_calls_per_prompt_chk
            CHECK (
                default_calls_per_prompt IS NULL
                OR default_calls_per_prompt >= 1
            );
    END IF;
END $$;

COMMENT ON COLUMN geo_clients.reuse_latest_final_prompt IS
    'Client-level Collector setting. NULL means use default false. TRUE reuses newest historical Final Prompts for the same prompt key.';
COMMENT ON COLUMN geo_clients.country_localization_mode IS
    'Client-level Collector setting. NULL means generic. generic reuses Final Prompts across countries; localized_by_country separates reuse by country.';
COMMENT ON COLUMN geo_clients.final_prompt_per_client_prompt IS
    'Client-level override for final_prompt_per_client_prompt. NULL falls back to Global Config, then code default 1.';
COMMENT ON COLUMN geo_clients.default_calls_per_prompt IS
    'Client-level override for default_calls_per_prompt. NULL falls back to Global Config, then code default 1.';

COMMIT;
