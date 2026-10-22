# Troubleshooting

## `connection refused` or cannot connect to PostgreSQL

- Confirm the PostgreSQL service is running.
- Check `.env`: `DB_HOST=127.0.0.1`, `DB_PORT=5432`, `DB_NAME=incident_lab`.
- Confirm PostgreSQL is listening on the configured port.
- Try connecting with pgAdmin or `psql` using the same database and role.

## `password authentication failed`

- Confirm `.env`'s `DB_USER` and `DB_PASSWORD` match the role created in `sql/01_setup.sql`.
- If you changed the role password, update `.env` too.
- Restart the API after editing `.env`.
- Never paste the password into a public GitHub issue or screenshot.

## `role does not exist` / `database does not exist`

- Run `CREATE DATABASE incident_lab;` separately as a local administrator.
- Connect to `incident_lab`, then run the remaining setup SQL beginning at `CREATE ROLE`.
- Check spelling and the database name in `.env`.

## Blocking relationship is missing from the dashboard

- Confirm Session B is still waiting before refreshing diagnostics.
- Confirm both sessions are connected to the same database and updating the same `account_id`.
- Confirm Session A has not committed or rolled back.
- Verify independently with `pg_blocking_pids()` and `pg_stat_activity`.
- Confirm the reader role has the required monitoring privileges, including the grant used in this lab (`pg_read_all_stats`). Follow least privilege and do not apply grants on production without approval.

## `No module named uvicorn` / `fastapi` / database driver

Activate the virtual environment, then run:

```bash
python3 -m pip install -r requirements.txt
```

On macOS/Linux use `source .venv/bin/activate`. On Windows use the appropriate PowerShell or Command Prompt activation command.

## `Address already in use` on port 8000

Stop the previous Uvicorn process with `Control + C`, or start locally on another port, for example:

```bash
python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

Then open `http://127.0.0.1:8001`.

## Dashboard loads but diagnostics fail

- Read the error in the terminal where Uvicorn is running.
- Confirm `.env` exists in the project root and the API was restarted after changes.
- Confirm the API and database are local and available.
- Share only sanitized errors; remove passwords, hostnames, customer names and SQL literals that contain sensitive data.
