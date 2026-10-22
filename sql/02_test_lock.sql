-- Open TWO pgAdmin Query Tool tabs or two psql terminals connected to incident_lab.
-- SESSION A: execute this first. Leave the transaction open while testing.
BEGIN;
UPDATE demo_accounts SET balance = balance + 10 WHERE account_id = 1;
-- Do NOT COMMIT yet. This transaction holds a row lock.
-- Now run SESSION B in the second window (see below).
