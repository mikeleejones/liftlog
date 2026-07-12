# Deploying liftlog to ultra.cc

liftlog is a single Python process (uvicorn) behind ultra.cc's nginx reverse
proxy. Develop and run locally first (see `README.md`); this is the last step
of v0.4. The app-specific commands below are exact; the steps that happen in
the ultra.cc panel are described generically — adapt them to your panel.

## 1. Get the code onto the server

SSH in, then clone into your home directory:

```sh
cd ~
git clone <your-remote-url> liftlog   # or rsync the working tree up
cd liftlog
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## 2. Pick a port and set the secret

ultra.cc assigns each custom app a free port. Reserve one from your panel
(or `Apps → Port` — whatever your plan exposes). Note it as `PORT` below.

Put the secret and DB path in the process environment, never in the repo:

```sh
# ~/liftlog/.env  (already gitignored)
LIFTLOG_SECRET=<a long random string>
LIFTLOG_DB=/home/<user>/liftlog/liftlog.db
```

Use a real random secret, e.g. `openssl rand -hex 24`. The SQLite file lives
outside the repo tree only if you point `LIFTLOG_DB` elsewhere; the default
sits next to the code and is gitignored.

## 3. Run it under a process manager

Bind to localhost on the assigned port — nginx reaches it, the outside world
does not:

```sh
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port <PORT>
```

Keep it alive across reboots. ultra.cc ships **pm2**. The process is defined
by the version-controlled `ecosystem.config.js` in the repo root rather than an
ad-hoc shell string, so restart limits are explicit. It reads the port (and the
optional subpath) from the gitignored `.env`, so add those there first:

```sh
# ~/liftlog/.env  (alongside LIFTLOG_SECRET)
LIFTLOG_PORT=<PORT>
# LIFTLOG_ROOT_PATH=/liftlog     # ONLY for the subpath layout (see section 4)
```

Then start it from the config file:

```sh
pm2 start ecosystem.config.js
pm2 save
pm2 startup   # follow the printed instruction once (survives a reboot)
```

The config enables auto-restart on crash (pm2's default) but bounds it:
`min_uptime: 10s` + `max_restarts: 10` mean a process that keeps dying within
10s of start is retried 10 times, then left stopped instead of hammering the
slot in a crash-loop. `.env` is read by both the config (for the port) and the
app itself, so pm2 needs no extra env config. If you prefer systemd --user, an
equivalent unit works the same way.

**Cap the logs** so crash output can't fill the slot's disk quota. Install the
pm2 log-rotate module once (idempotent — safe to re-run):

```sh
pm2 install pm2-logrotate
pm2 set pm2-logrotate:max_size 10M
pm2 set pm2-logrotate:retain 7
pm2 set pm2-logrotate:compress true
```

## 4. Expose it through nginx

In the panel, add a reverse-proxy / custom-app entry that forwards a public
URL to `http://127.0.0.1:<PORT>`. Both layouts are supported:

- **Subdomain** (`https://liftlog.<user>.usbx.me`): nothing extra to do.
- **Subpath** (`https://<user>.usbx.me/liftlog/`): set `LIFTLOG_ROOT_PATH=/liftlog`
  in `.env` (the config passes it to uvicorn as `--root-path`), and configure nginx to strip the prefix before
  forwarding (a `proxy_pass http://127.0.0.1:<PORT>/;` with the trailing
  slash under `location /liftlog/ { ... }`). The app reads the incoming root
  path and prefixes every link, redirect, form action, static asset, and JS
  fetch accordingly, so URLs resolve to paths nginx actually proxies. The
  auth cookie is scoped to the prefix. The web-app manifest uses relative
  URLs, so Add-to-Home-Screen works under either layout.

Make sure the proxy passes `X-Forwarded-*` headers and allows the cookie
through (it's a normal first-party cookie, HttpOnly, SameSite=Lax).

To sanity-check the subpath build locally before redeploying:

```sh
.venv/bin/uvicorn app.main:app --port 8321 --root-path /liftlog
# GET / should 303 to /liftlog/login (not /login)
curl -sI localhost:8321/ | grep -i location
```

## 5. First load

Open the URL, enter the secret once (the cookie lasts a year), and confirm
Home renders. The database and its tables are created automatically on first
start; any existing `liftlog.db` you copied up is migrated in place.

## Updating later

Deployment is by **rsync**, not git. From the repo root on your Mac, push the
working tree up — excluding the live database, the secret, and the local venv so
they're never overwritten:

```sh
rsync -av --delete \
  --exclude='.venv' --exclude='liftlog.db*' --exclude='.env' --exclude='.git' \
  ./ <user>@<host>:~/liftlog/
```

`--delete` prunes files on the server that no longer exist locally (so removed
modules like `app/catalog.py` go away too); the excludes keep `liftlog.db`,
`.env`, and `.venv` intact. Then on the server:

```sh
ssh <user>@<host>
cd ~/liftlog
.venv/bin/pip install -r requirements.txt   # only when requirements changed (e.g. anthropic added in v0.5 item 4)
pm2 restart liftlog
```

**One-time migration to the config file** (only if liftlog is still running from
the old inline `pm2 start ".venv/bin/uvicorn ..."` string). Add `LIFTLOG_PORT`
to `.env` (see section 3), then re-create the process from the config once:

```sh
pm2 delete liftlog
pm2 start ecosystem.config.js
pm2 save
```

After that, plain `pm2 restart liftlog` picks up the version-controlled
definition on every deploy.

Schema changes migrate on start (see `app/db.py`). Back up first with the
**EXPORT JSON** button on the Settings screen, or just copy `liftlog.db`.
