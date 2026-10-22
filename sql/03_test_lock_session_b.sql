-- SESSION B: run after Session A has executed its UPDATE and left the transaction open.
-- This UPDATE should wait for Session A's row lock. Leave it waiting while you click Run diagnostics.
UPDATE demo_accounts SET balance = balance + 20 WHERE account_id = 1;
