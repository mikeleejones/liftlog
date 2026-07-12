// pm2 process definition for liftlog (see DEPLOY.md section 3).
//
// This replaces the old ad-hoc `pm2 start ".venv/bin/uvicorn ..."` shell
// string so restart behaviour is explicit and version-controlled.
//
// Deploy-specific values (port, optional subpath) are NOT hardcoded here —
// they live in the gitignored `.env` alongside LIFTLOG_SECRET, and are read
// below the same way app/config.py reads it. On the server, add to ~/liftlog/.env:
//
//   LIFTLOG_PORT=<the port ultra.cc assigned>
//   LIFTLOG_ROOT_PATH=/liftlog      # ONLY for the subpath layout; omit for a subdomain
//
// Then:  pm2 start ecosystem.config.js  &&  pm2 save
//
const fs = require("fs");
const path = require("path");

// Mirror app/config.py's minimal .env parser so the port stays in one
// gitignored place. Real shell env wins over .env (setdefault semantics).
function loadEnv() {
  const envfile = path.join(__dirname, ".env");
  if (!fs.existsSync(envfile)) return;
  for (const raw of fs.readFileSync(envfile, "utf8").split("\n")) {
    const line = raw.trim();
    if (!line || line.startsWith("#") || !line.includes("=")) continue;
    const idx = line.indexOf("=");
    const key = line.slice(0, idx).trim();
    const value = line.slice(idx + 1).trim();
    if (process.env[key] === undefined) process.env[key] = value;
  }
}
loadEnv();

const host = process.env.LIFTLOG_HOST || "127.0.0.1";
const port = process.env.LIFTLOG_PORT || "8321";
const rootPath = process.env.LIFTLOG_ROOT_PATH || "";

const args = ["app.main:app", "--host", host, "--port", port];
if (rootPath) args.push("--root-path", rootPath);

module.exports = {
  apps: [
    {
      name: "liftlog",
      cwd: __dirname,
      script: ".venv/bin/uvicorn",
      args,
      interpreter: "none", // uvicorn is a native executable, not a node script

      // Keep it alive across crashes (pm2's default), but don't spin forever
      // in a crash-restart loop if the app is genuinely broken: a process must
      // stay up 10s to count as "started"; after 10 such quick failures pm2
      // stops retrying and leaves it stopped/errored instead of looping.
      autorestart: true,
      min_uptime: "10s",
      max_restarts: 10,
      restart_delay: 2000,
    },
  ],
};
