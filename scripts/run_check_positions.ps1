# scripts/run_check_positions.ps1
#
# Runs `bonaid check-positions` against the ALREADY-RUNNING Docker Compose
# stack. Designed to be triggered by Windows Task Scheduler on a recurring
# schedule (e.g. every 30 minutes during market hours) so paper positions
# actually get checked against live prices and closed on stop-loss/
# take-profit automatically, instead of only when someone remembers to run
# the command manually.
#
# IMPORTANT ARCHITECTURAL NOTE: this deliberately does NOT use GitHub
# Actions (unlike the standalone trading_system project's market scanner).
# GitHub Actions runners are ephemeral - a fresh container every run, with
# no access to your local Postgres volume where all paper-trading state
# (open positions, decision history) actually lives. Running on YOUR
# machine via Task Scheduler is what lets this share the same persistent
# Postgres data as your manual `bonaid` commands. If you want genuine
# server-hosted 24/7 (not dependent on your PC being on), the real fix is
# moving Postgres to a persistent cloud instance (Supabase/Neon/Railway all
# have free tiers) - flagged here as a known limitation, not solved by this
# script alone.

$ErrorActionPreference = "Stop"
$LogDir = "$PSScriptRoot\logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogFile = "$LogDir\check_positions_$(Get-Date -Format 'yyyyMMdd').log"

function Write-Log {
    param([string]$Message)
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    "$timestamp - $Message" | Tee-Object -FilePath $LogFile -Append
}

Write-Log "Starting scheduled position check..."

try {
    # Confirm the app container is actually running before trying to exec
    # into it - Task Scheduler running unattended shouldn't silently fail
    # with a confusing Docker error if Docker Desktop wasn't started yet.
    $running = docker compose -f "$PSScriptRoot\..\docker\docker-compose.yml" ps app --status running --format json 2>$null
    if (-not $running) {
        Write-Log "ERROR: bonaid-app container is not running. Is Docker Desktop started? Skipping this run."
        exit 1
    }

    $output = docker compose -f "$PSScriptRoot\..\docker\docker-compose.yml" exec -T app bonaid check-positions 2>&1
    Write-Log $output

    Write-Log "Position check complete."
} catch {
    Write-Log "ERROR: $($_.Exception.Message)"
    exit 1
}
