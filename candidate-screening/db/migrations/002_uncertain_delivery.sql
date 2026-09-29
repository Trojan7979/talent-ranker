-- An expired send lease or transport exception may follow provider acceptance.
-- Keep those messages out of automatic retries until an operator reconciles them.
ALTER TABLE screening_delivery_outbox
    DROP CONSTRAINT IF EXISTS screening_delivery_outbox_status_check;
ALTER TABLE screening_delivery_outbox
    ADD CONSTRAINT screening_delivery_outbox_status_check
    CHECK (status IN ('pending', 'processing', 'sent', 'failed', 'unknown', 'cancelled'));
CREATE INDEX IF NOT EXISTS screening_delivery_lease_idx
    ON screening_delivery_outbox (leased_until)
    WHERE status = 'processing';
