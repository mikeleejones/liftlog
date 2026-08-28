# Deploying liftlog

liftlog runs on a shared OVH VPS (alias `mrradcl` in `~/.ssh/config`) alongside
several other personal projects (ReelLog, Rental Radar, etc.), behind **Caddy**
(not nginx) and managed by **pm2**. This file previously described an ultra.cc
deployment — that was the original v0.4 target and has since moved; this is
the corrected version (see `CLAUDE.md`'s Server access section).

Deployment is by **rsync**, not git — the server directories
(`/home/ubuntu/apps/liftlog` and `/home/ubuntu/apps/liftlog-staging`) are
plain rsync targets, not git checkouts.

## Environments

| | Host | Directory | Port | pm2 process |
|---|---|---|---|---|
| Production | `liftlog.mrradcl.com` | `/home/ubuntu/apps/liftlog` | 8001 | `liftlog` |
| Staging | `liftlog-staging.mrradcl.com` | `/home/ubuntu/apps/liftlog-staging` | 8011 | `liftlog-staging` |

Both are real, already-running environments. **Always deploy to staging
first**, verify it end-to-end, then promote the same change to production.

## 1. First-time setup (already done, documented for reference)

```sh
ssh mrradcl
mkdir -p ~/apps/liftlog   # or liftlog-staging
cd ~/apps/liftlog
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

**Current staging exception:** `liftlog-staging` intentionally uses the
production app directory's interpreter (`/home/ubuntu/apps/liftlog/venv`) with
its own working directory and SQLite file. Its pm2 process is configured that
way today, so staging dependency and Alembic commands must use the shared path
until this is deliberately changed; do not assume `~/apps/liftlog-staging/venv`
exists.

`~/apps/<env>/.env` (gitignored, never rsynced) holds:

```sh
LIFTLOG_SECRET=<a long random string>       # openssl rand -hex 24
LIFTLOG_DB=/home/ubuntu/apps/<env>/liftlog.db
LIFTLOG_PORT=<8001 for production, 8011 for staging>
ANTHROPIC_API_KEY=<key, used by app/ai.py for AI substitution suggestions>
```

There is currently no subpath/root-path deployment (`LIFTLOG_ROOT_PATH`) —
each environment gets its own subdomain, so that code path is being removed
as part of the v0.6 frontend migration (decision #15).

## 2. Run under pm2

Defined by the version-controlled `ecosystem.config.js` in the repo root
(reads `LIFTLOG_PORT` from `.env`):

```sh
pm2 start ecosystem.config.js
pm2 save
```

`autorestart` is on with `min_uptime: 10s` / `max_restarts: 10`, so a process
that keeps crashing within 10s of start is retried 10 times then left
stopped rather than crash-looping forever.

## 3. Caddy

Config lives at `/etc/caddy/Caddyfile` on the server (not in this repo).
**Current state** (pre-migration, FastAPI serves Jinja2-rendered HTML
directly):

```
liftlog.mrradcl.com {
    reverse_proxy localhost:8001
}
liftlog-staging.mrradcl.com {
    reverse_proxy 127.0.0.1:8011
}
```

**Target state after the v0.6 frontend migration** (React SPA build served
directly by Caddy, API calls proxied through) — mirrors the
`rentalradar.mrradcl.com` block already live on this same VPS:

```
liftlog.mrradcl.com {
    root * /home/ubuntu/apps/liftlog/frontend/dist
    encode gzip

    handle /api/* {
        reverse_proxy localhost:8001
    }

    handle {
        try_files {path} /index.html
        file_server
    }
}
```

(Same pattern for `liftlog-staging.mrradcl.com` → port 8011.) This change
lands in Phase 6 of the migration, only after the SPA has full functional and
design parity verified on staging.

After editing the Caddyfile: `sudo caddy reload --config /etc/caddy/Caddyfile`
(or `systemctl reload caddy`).

## 4. Deploying an update (current, pre-migration)

From the repo root on your Mac, rsync the working tree up — excluding the
live database, secret, and local venv:

```sh
rsync -av --delete \
  --exclude='.venv' --exclude='venv' --exclude='liftlog.db*' \
  --exclude='.env' --exclude='.git' --exclude='frontend' \
  ./ mrradcl:~/apps/liftlog-staging/    # staging first
```

Then on the server:

```sh
ssh mrradcl
cd ~/apps/liftlog-staging
/home/ubuntu/apps/liftlog/venv/bin/pip install -r requirements.txt   # shared staging interpreter
pm2 restart liftlog-staging
```

Verify on `https://liftlog-staging.mrradcl.com`, then repeat the rsync target
and pm2 process name for production (`~/apps/liftlog`, `pm2 restart liftlog`).

## 5. Deploying after the frontend migration lands (Phase 6+)

Build the frontend locally before rsyncing, then ship the build output
alongside the Python app:

```sh
cd frontend && npm run build && cd ..
rsync -av --delete \
  --exclude='.venv' --exclude='venv' --exclude='liftlog.db*' \
  --exclude='.env' --exclude='.git' --exclude='frontend/node_modules' \
  ./ mrradcl:~/apps/liftlog-staging/
ssh mrradcl 'cd ~/apps/liftlog-staging && /home/ubuntu/apps/liftlog/venv/bin/pip install -r requirements.txt && pm2 restart liftlog-staging'
```

No `--exclude='frontend'` this time — `frontend/dist` needs to reach the
server since Caddy serves it directly (see section 3).

## Schema / database

Schema changes migrate via Alembic. Existing databases created before v0.6
already match baseline `20260827_01`; after deploying Phase 1, mark each once
with `venv/bin/alembic stamp 20260827_01` (or the shared interpreter path for
staging; this creates only Alembic's version record, not a schema/data
migration). Future releases use `venv/bin/alembic upgrade head` after
rsyncing. New empty databases use `upgrade head` directly. Back up first with
the **EXPORT JSON** button on Profile, or just copy `liftlog.db`. Never run
destructive database commands on production without explicit confirmation (see
`CLAUDE.md`'s Server access section).
