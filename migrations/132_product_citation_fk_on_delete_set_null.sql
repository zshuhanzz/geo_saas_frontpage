-- Migration 132: preserve historical citation facts when product config is deleted.
--
-- Context:
--   geo_citations.matched_product_id is an optional Analyzer classification.
--   The original FK used NO ACTION, so deleting a configured product that had
--   already appeared in analyzed results failed with a foreign-key violation.
--
-- Behavior after this migration:
--   - deleting geo_client_topic_products only clears matched_product_id;
--   - the citation row, URL, domain, role, timestamps, and reportable history
--     remain unchanged;
--   - disabling/re-enabling products continues to use is_active and does not
--     invoke this FK behavior.
--
-- Run manually in Cloud SQL. The application also detaches the references in
-- its delete transaction, so this constraint is a durable defense-in-depth
-- rule for every current and future deletion path.

BEGIN;

ALTER TABLE geo_citations
    DROP CONSTRAINT IF EXISTS geo_citations_matched_product_id_fkey;

ALTER TABLE geo_citations
    ADD CONSTRAINT geo_citations_matched_product_id_fkey
    FOREIGN KEY (matched_product_id)
    REFERENCES geo_client_topic_products(id)
    ON DELETE SET NULL
    NOT VALID;

ALTER TABLE geo_citations
    VALIDATE CONSTRAINT geo_citations_matched_product_id_fkey;

DO $$
DECLARE
    delete_action "char";
BEGIN
    SELECT c.confdeltype
      INTO delete_action
      FROM pg_constraint c
      JOIN pg_class t ON t.oid = c.conrelid
     WHERE t.relname = 'geo_citations'
       AND c.conname = 'geo_citations_matched_product_id_fkey';

    IF delete_action IS DISTINCT FROM 'n' THEN
        RAISE EXCEPTION
            'Expected geo_citations_matched_product_id_fkey ON DELETE SET NULL, got %',
            delete_action;
    END IF;
END $$;

COMMIT;
