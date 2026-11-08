-- Run ONLY in a dedicated test database such as incident_intelligence_lab.
-- This creates a small, isolated schema for reproducing lock/transaction scenarios.
CREATE SCHEMA IF NOT EXISTS ii_test;

CREATE TABLE IF NOT EXISTS ii_test.accounts (
    account_id integer PRIMARY KEY,
    account_name text NOT NULL,
    balance numeric(12,2) NOT NULL CHECK (balance >= 0),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

INSERT INTO ii_test.accounts (account_id, account_name, balance)
VALUES
    (1, 'test-account-a', 1000.00),
    (2, 'test-account-b', 2000.00)
ON CONFLICT (account_id) DO NOTHING;

SELECT * FROM ii_test.accounts ORDER BY account_id;
