# Upgrade to v0.2.0 without losing local evidence

1. Stop the running app with `Ctrl+C`.
2. Back up `.env` and `data/incident_intelligence.sqlite3` (also retain the `-wal`/`-shm` files if present, or make a SQLite online backup while the database is closed).
3. Extract `PostgreSQL_Incident_Intelligence_v0.2.0.zip` into the parent directory of your existing project folder and overwrite code files.
4. Do not replace or remove `.env` or `data/`.
5. Activate the same virtual environment and run `python -m incident_intelligence`.
6. Open an existing incident and confirm the investigation workspace loads. Older incidents can show limited baseline or post-incident context if samples were never retained around them.

The v0.2.0 update adds application-side analysis of existing evidence. It does not change the PostgreSQL collector schema or SQLite evidence schema and does not require a destructive migration.
