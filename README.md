# liftlog

Personal workout tracker. See `CLAUDE.md` and `docs/` for the design authority.

## Run locally

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
echo 'LIFTLOG_SECRET=pick-a-secret' > .env
# New empty database:
.venv/bin/alembic upgrade head
# Existing database created before v0.6 (run once instead of upgrade):
# .venv/bin/alembic stamp 20260827_01
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8321
```

Open http://localhost:8321 on the Mac, or `http://<mac-lan-ip>:8321` from the
iPhone on the same network. The SQLite database lives next to this file as
`liftlog.db` (gitignored); override with `LIFTLOG_DB`. Alembic creates the
schema for a new file; the application itself never runs schema DDL at startup.
