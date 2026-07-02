# liftlog

Personal workout tracker. See `CLAUDE.md` and `docs/` for the design authority.

## Run locally

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
echo 'LIFTLOG_SECRET=pick-a-secret' > .env
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8321
```

Open http://localhost:8321 on the Mac, or `http://<mac-lan-ip>:8321` from the
iPhone on the same network. The SQLite database is created next to this file
as `liftlog.db` (gitignored); override with `LIFTLOG_DB`.
