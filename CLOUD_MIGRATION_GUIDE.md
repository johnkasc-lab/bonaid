# Bonaid — Cloud Migration Guide (Supabase + Render)

Moves your Postgres database to a free cloud host and deploys a
publicly-reachable copy of the dashboard, so you can check positions from
your phone anywhere. Your local setup (`docker/docker-compose.yml`) is
untouched throughout this - if anything goes wrong, you can keep using it
exactly as before.

**Time estimate:** 30-45 minutes.

---

## Part 1 — Create your free Supabase Postgres

1. Go to https://supabase.com -> Sign up (free, no card required).
2. **New Project** -> name it `bonaid` -> set a strong database password
   (save it - you'll need it below) -> choose the nearest region ->
   **Create new project**. Takes ~2 minutes to provision.
3. Go to **Project Settings -> Database -> Connection String**.
   **Use the "Session pooler" tab, NOT "Direct connection".** The direct
   hostname (`db.<project>.supabase.co`) resolves to IPv6 only, which most
   Docker Desktop/WSL2 setups can't route to - this causes exactly the
   "Network unreachable" error if you hit it. The Session Pooler uses a
   different hostname (`aws-0-<region>.pooler.supabase.com`, port 5432)
   that works correctly from Docker.
4. Copy these four values from the Session Pooler tab - you'll need them
   twice (once for migration below, once for `.env.cloud` in Part 3):
   - Host (looks like `aws-0-us-east-1.pooler.supabase.com`)
   - Port (`5432`)
   - User (looks like `postgres.abcdefghijklmnop` - NOT just `postgres`)
   - Password (what you set in step 2)

## Part 2 — Migrate your existing data (your 8 real positions + history)

```powershell
# 1. Dump your LOCAL database to a file (unchanged from before)
docker compose -f F:\bonaid\docker\docker-compose.yml exec postgres pg_dump -U bonaid -d bonaid --no-owner --no-privileges -F c -f /tmp/bonaid_backup.dump
docker compose -f F:\bonaid\docker\docker-compose.yml cp postgres:/tmp/bonaid_backup.dump F:\bonaid\bonaid_backup.dump
```

```powershell
# 2. Copy the dump into the container, then restore into Supabase's Session
# Pooler. Replace the four values below with your ACTUAL values from Part 1
# step 4 - do not include angle brackets, and do not type $env: lines as
# literal text, just edit the values on the right of each = sign.
docker compose -f F:\bonaid\docker\docker-compose.yml cp F:\bonaid\bonaid_backup.dump postgres:/tmp/bonaid_backup.dump

$SUPABASE_HOST = "aws-0-us-east-1.pooler.supabase.com"
$SUPABASE_USER = "postgres.abcdefghijklmnop"

docker compose -f F:\bonaid\docker\docker-compose.yml exec postgres pg_restore --no-owner --no-privileges -h $SUPABASE_HOST -p 5432 -U $SUPABASE_USER -d postgres --clean --if-exists /tmp/bonaid_backup.dump
```
It will prompt for the database password you set in Part 1 step 2.

**If this feels like too much for now:** skip migration entirely and
start fresh in the cloud - run `bonaid init-db` against Supabase instead
(Part 4 below) and let new positions accumulate there going forward. Your
local data stays exactly as-is in `docker/docker-compose.yml`'s setup, you
just won't see the historical 8 positions in the cloud copy.

## Part 3 — Set up `.env.cloud`

```powershell
cd F:\bonaid
copy .env.cloud.example .env.cloud
notepad .env.cloud
```
Fill in (same Session Pooler values from Part 1 step 4):
- `POSTGRES_HOST` -> the pooler hostname (`aws-0-...pooler.supabase.com`)
- `POSTGRES_USER` -> the pooler username (`postgres.abc...`, not just `postgres`)
- `POSTGRES_PASSWORD` -> your database password
- `POSTGRES_PORT` -> `5432`, `POSTGRES_DB` -> `postgres` (already correct
  as defaults, just confirm you didn't change them)
- `DASHBOARD_USERNAME` / `DASHBOARD_PASSWORD` -> pick your own, don't
  leave blank - this is what protects your dashboard once it's public.
- Copy over Telegram/email/Reddit/FRED values from your existing `.env`
  if you want those working in cloud mode too.
- Leave `REDIS_HOST` blank unless you've set up Upstash separately.

**Important file location:** save this as `F:\bonaid\.env.cloud` (repo
root, next to your existing `.env`) - NOT inside the `docker` folder.

## Part 4 — Run the cloud stack locally first (sanity check before deploying)

The cloud compose file lives inside the `docker` folder, same as your
original one - always reference it with that path:

```powershell
cd F:\bonaid
docker compose -f docker\docker-compose.cloud.yml up -d --build
docker compose -f docker\docker-compose.cloud.yml exec app bonaid init-db
docker compose -f docker\docker-compose.cloud.yml exec app bonaid status
```
`status` should show Postgres as OK, connecting to Supabase instead of
your local container. Then:
```powershell
docker compose -f docker\docker-compose.cloud.yml exec app bonaid positions
```
If you migrated data in Part 2, your real 8 positions should appear here,
now being read from Supabase - compare against your local
`bonaid positions` output to confirm they match exactly.

Open `http://localhost:8000` - your dashboard, now running against the
cloud database (still only reachable from your own machine at this
point). Confirm it asks for a username/password, and your real data shows
up correctly.

## Part 5 — Deploy the dashboard publicly (Render)

1. Push your `bonaid` folder to a GitHub repo if you haven't already.
2. Go to https://render.com -> sign up free -> **New -> Web Service** ->
   connect your GitHub repo.
3. Configure:
   - **Root Directory**: leave blank (repo root)
   - **Dockerfile Path**: `docker/Dockerfile`
   - **Docker Command** (override): `uvicorn bonaid.dashboard.main:app --host 0.0.0.0 --port 10000`
   - **Instance Type**: Free
4. Under **Environment Variables**, add every value from your
   `.env.cloud` file (Render doesn't read `.env` files - paste each
   key/value pair into their dashboard directly).
5. **Create Web Service**. First deploy takes a few minutes.
6. Once live, Render gives you a public URL like
   `https://bonaid-dashboard.onrender.com`. Open it, log in with your
   dashboard credentials, confirm your real data shows up.

**Known free-tier behavior, not a bug:** Render's free web services spin
down after ~15 minutes idle and take 30-60 seconds to wake up on the next
request.

## Part 6 — Point local scheduled tasks at the cloud database too (optional)

Update `scripts/run_check_positions.ps1` to reference
`docker\docker-compose.cloud.yml` instead of `docker\docker-compose.yml`
if you want `check-positions` writing to the same cloud database the
public dashboard reads from. Your PC still needs to be on for that
specific script to run - only the dashboard itself is reachable when your
PC is off, not new trading activity.

## Troubleshooting

| Error | Cause | Fix |
|---|---|---|
| `pg_restore: ... Network unreachable` | Used the direct-connection hostname, which is IPv6-only | Use the Session Pooler hostname instead (Part 1 step 3) |
| `env file F:\.env.cloud not found` | Ran the compose command from the wrong location, or referenced the wrong compose file path | Always use `docker compose -f docker\docker-compose.cloud.yml ...` from `F:\bonaid` |
| PowerShell "reserved for future use" error on `<` | Angle brackets in a guide are placeholder notation, not literal syntax | Replace the whole `<PLACEHOLDER>` including both brackets with your real value |

## Rollback / staying local

Nothing here removes or breaks your original setup.
`docker\docker-compose.yml` and your local Postgres container keep
working exactly as before - `docker\docker-compose.cloud.yml` is a
completely separate, additional way to run the same code. To stop using
cloud mode: `docker compose -f docker\docker-compose.cloud.yml down` and
continue with your original local commands.
