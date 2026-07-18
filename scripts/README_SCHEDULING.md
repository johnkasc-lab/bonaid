# 24/7 Position Monitoring Setup (Windows Task Scheduler)

## Why Task Scheduler, not GitHub Actions

The standalone `trading_system` project's market scanner used GitHub
Actions cron, which works fine for pure market-scanning (no state to
persist between runs). But `bonaid`'s paper-trading positions live in a
Postgres database inside a **local Docker volume on your machine** - a
GitHub Actions runner is a fresh, empty environment every single run, with
no access to that data. Running the check on YOUR machine via Task
Scheduler is what lets it see and update the same persistent state your
manual `bonaid` commands use.

**Real limitation to know about:** this only runs while your PC is on,
awake, and Docker Desktop is running. For true always-on server hosting
independent of your PC, the actual fix would be moving Postgres to a free
cloud instance (Supabase, Neon, Railway all have free tiers) - that's a
bigger change, not done here. This Task Scheduler approach is the correct,
honest solution for "runs automatically on my machine," not "runs on a
server I don't have to keep on."

## Setup steps

### 1. Confirm the script works manually first
```powershell
cd F:\bonaid
powershell -File scripts\run_check_positions.ps1
```
You should see log output print, and a new file appear under
`scripts\logs\`. If you get a Docker error, make sure Docker Desktop is
running and the stack is up (`docker compose up -d` from `F:\bonaid\docker`).

### 2. Open Task Scheduler
Press `Win + R`, type `taskschd.msc`, hit Enter.

### 3. Create a new task (not "Basic Task" - use the full wizard for more control)
1. Right-click **Task Scheduler Library** → **Create Task...**
2. **General tab:**
   - Name: `Bonaid Position Check`
   - Check **"Run whether user is logged on or not"** (so it works even if
     you're locked/away)
   - Check **"Run with highest privileges"**
3. **Triggers tab** → **New...**
   - Begin the task: **On a schedule**
   - Settings: **Daily**, recur every 1 day
   - Advanced settings: check **"Repeat task every"** → `30 minutes` → for
     a duration of **1 day** (this makes it fire every 30 min, all day,
     every day)
4. **Actions tab** → **New...**
   - Action: **Start a program**
   - Program/script: `powershell.exe`
   - Add arguments: `-ExecutionPolicy Bypass -File "F:\bonaid\scripts\run_check_positions.ps1"`
5. **Conditions tab:**
   - Uncheck **"Start the task only if the computer is on AC power"**
     (unless you specifically want it to skip runs on battery)
6. **Settings tab:**
   - Check **"Run task as soon as possible after a scheduled start is missed"**
   - Check **"If the task fails, restart every"** → 5 minutes, up to 3 times
7. Click **OK**, enter your Windows password if prompted.

### 4. Test it
Right-click the task in the list → **Run**. Check
`F:\bonaid\scripts\logs\` for a new log file confirming it worked.

## Adjust the schedule frequency
30 minutes is a reasonable default. To change it, edit the task's Trigger
→ Advanced settings → "Repeat task every" value. More frequent checks
catch stop-loss/take-profit hits sooner but call the data source more
often - `data_fetcher.py`'s parquet caching means same-day repeat fetches
for the same ticker are cheap, so frequent checks aren't wasteful.

## Verify it's actually running over time
```powershell
Get-Content F:\bonaid\scripts\logs\check_positions_$(Get-Date -Format 'yyyyMMdd').log -Tail 20
```
Or check `bonaid positions` / `bonaid pnl` periodically to confirm
positions are actually closing when they should.

## Also consider scheduling `bonaid scan`
The same pattern works for automatically running the diversified-universe
scan on a schedule too (e.g. once per day, market open), not just position
checks. Copy `run_check_positions.ps1`, change the `bonaid` subcommand to
`scan`, and set up a second Task Scheduler entry with a daily (not every-30-
minutes) trigger.
