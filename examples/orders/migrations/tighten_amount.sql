ALTER TABLE orders ADD CONSTRAINT positive_amount CHECK (amount_cents > 0) NOT VALID;
