"""
bonaid/cli.py
The terminal application entrypoint - `bonaid <command>`.
Phase 1: status, init-db, ping (graph), llm-check.
Agents so far: Technical (signal), News (headline sentiment), Risk (position sizing).
"""
import typer
from rich.console import Console
from rich.table import Table

from bonaid.config import settings
from bonaid.db import init_db, get_session
from bonaid import cache, llm, graph as graph_mod

app = typer.Typer(help="Bonaid - open-source multi-agent trading research system")
console = Console()


@app.command()
def status():
    """Check health of every subsystem: Postgres, Redis, Ollama, orchestration graph."""
    table = Table(title=f"{settings.app_name} - System Status")
    table.add_column("Component")
    table.add_column("Status")
    table.add_column("Detail")

    try:
        with get_session() as s:
            s.execute(__import__("sqlalchemy").text("SELECT 1"))
        pg_status, pg_detail = "[green]OK[/green]", settings.postgres_url.split("@")[-1]
    except Exception as e:
        pg_status, pg_detail = "[red]DOWN[/red]", str(e)[:60]
    table.add_row("PostgreSQL", pg_status, pg_detail)

    redis_ok = cache.ping()
    table.add_row("Redis", "[green]OK[/green]" if redis_ok else "[red]DOWN[/red]", settings.redis_url)

    ollama_ok = llm.is_available()
    models = llm.list_models() if ollama_ok else []
    table.add_row(
        "Ollama (local LLM)",
        "[green]OK[/green]" if ollama_ok else "[yellow]NOT RUNNING[/yellow]",
        f"models: {', '.join(models) if models else 'none pulled yet'}",
    )

    try:
        result = graph_mod.run_ping()
        table.add_row("Orchestration (LangGraph)", "[green]OK[/green]", result)
    except Exception as e:
        table.add_row("Orchestration (LangGraph)", "[red]DOWN[/red]", str(e)[:60])

    console.print(table)


@app.command("init-db")
def init_db_cmd():
    """Create all database tables."""
    init_db()
    console.print("[green]Database tables created/verified.[/green]")


@app.command("ping")
def ping(query: str = "healthcheck", ticker: str = None):
    """Send a test message through the orchestration graph."""
    console.print(graph_mod.run_ping(query=query, ticker=ticker))


@app.command("llm-check")
def llm_check():
    """Verify Ollama connectivity and list available local models."""
    if not llm.is_available():
        console.print(f"[red]Ollama not reachable at {settings.ollama_host}[/red]")
        console.print("Start it with: `ollama serve` (or via docker-compose up ollama)")
        raise typer.Exit(1)

    models = llm.list_models()
    if models:
        console.print(f"[green]Ollama is reachable.[/green] Models available: {models}")
    else:
        console.print(
            f"[green]Ollama is reachable.[/green] No models pulled yet. "
            f"Run: ollama pull {settings.ollama_model}"
        )


def _run_and_execute(ticker: str, synthetic: bool = False, manual: bool = False, capital: float | None = None) -> dict:
    """Core pipeline used by both `analyze` (single ticker, verbose) and
    `scan` (many tickers, compact summary). Runs the full agent chain,
    auto-executes a paper trade on a sized BUY (unless manual=True), and
    persists the decision. Returns the combined result dict plus a
    'paper_trade_message' key - no printing here, callers decide how to
    display it."""
    from bonaid.models import AgentDecision

    combined = graph_mod.run_technical_analysis(ticker, use_synthetic=synthetic, capital=capital)
    technical = combined["technical_analysis"]
    news = combined["news_assessment"]
    sentiment = combined["sentiment_assessment"]
    decision = combined["supervisor_decision"]
    risk = combined["risk_assessment"]

    paper_trade_message = None
    if risk["tradeable"]:
        if manual:
            paper_trade_message = "--manual set: not auto-executing."
        else:
            from bonaid.agents.paper_trading import open_position
            _, paper_trade_message = open_position(
                ticker=decision["ticker"],
                shares=risk["position_shares"],
                entry_price=risk["entry_price"],
                stop_loss=risk["stop_loss"],
                take_profit=risk["take_profit"],
                entry_confidence=decision["confidence"],
            )

    db_error = None
    try:
        with get_session() as s:
            s.add(AgentDecision(
                ticker=decision["ticker"],
                action=decision["action"],
                confidence=decision["confidence"],
                reasons=technical["reasons"],
                signal_breakdown=technical["signal_breakdown"],
                llm_summary=technical.get("llm_summary"),
                news_assessment=news,
                sentiment_assessment=sentiment,
                supervisor_decision=decision,
                risk_assessment=risk,
            ))
    except Exception as e:
        db_error = str(e)

    combined["paper_trade_message"] = paper_trade_message
    combined["db_error"] = db_error
    return combined


@app.command()
def analyze(
    ticker: str,
    synthetic: bool = typer.Option(False, help="Use synthetic data (offline testing)"),
    manual: bool = typer.Option(False, "--manual", help="Don't auto-execute a paper trade even if BUY - just show the recommendation"),
):
    """Run Technical + News + Sentiment + Supervisor + Risk on a ticker,
    print the final recommendation, and (unless --manual) auto-execute a
    paper trade if the final decision is a sized BUY."""
    with console.status(f"Analyzing {ticker}..."):
        combined = _run_and_execute(ticker, synthetic=synthetic, manual=manual)

    technical = combined["technical_analysis"]
    news = combined["news_assessment"]
    sentiment = combined["sentiment_assessment"]
    decision = combined["supervisor_decision"]
    risk = combined["risk_assessment"]

    # --- Supervisor's final decision leads the output - this is the actual answer ---
    action_color = {"BUY": "green", "SELL": "red", "WATCH": "yellow", "HOLD": "white"}.get(decision["action"], "white")
    console.print(f"\nRecommendation: [{action_color}]{decision['action']} {decision['ticker']}[/{action_color}]")
    console.print(f"Confidence: {decision['confidence']}%")
    if decision["overridden"]:
        console.print(f"[yellow](Overridden from Technical's raw {decision['technical_action']} signal - see reasoning below)[/yellow]")
    console.print("Reasoning:")
    for r in decision["reasoning"]:
        console.print(f"  - {r}")

    # --- Supporting detail: Technical Agent's raw signal ---
    console.print(f"\n[bold]Technical signal:[/bold] {technical['action']} ({technical['confidence']}% confidence)")
    for r in technical["reasons"]:
        console.print(f"  - {r}")
    if technical.get("llm_summary"):
        console.print(f"  [dim]{technical['llm_summary']}[/dim]")

    # --- Supporting detail: News Agent's sentiment ---
    news_color = {"Positive": "green", "Negative": "red", "Mixed": "yellow", "Neutral": "white", "No Data": "dim"}.get(news["sentiment_label"], "white")
    console.print(f"\n[bold]News sentiment:[/bold] [{news_color}]{news['sentiment_label']}[/{news_color}] (score: {news['sentiment_score']})")
    for r in news["reasons"]:
        console.print(f"  - {r}")
    if news.get("llm_summary"):
        console.print(f"  [dim]{news['llm_summary']}[/dim]")

    # --- Supporting detail: Sentiment Agent's social sentiment (StockTwits primary, Reddit fallback) ---
    social_color = {"Positive": "green", "Negative": "red", "Mixed": "yellow", "Neutral": "white", "No Data": "dim"}.get(sentiment["sentiment_label"], "white")
    console.print(f"\n[bold]Social sentiment:[/bold] [{social_color}]{sentiment['sentiment_label']}[/{social_color}] (score: {sentiment['sentiment_score']})")
    for r in sentiment["reasons"]:
        console.print(f"  - {r}")
    if sentiment.get("llm_summary"):
        console.print(f"  [dim]{sentiment['llm_summary']}[/dim]")

    # --- Risk Agent's position sizing, based on the Supervisor's final action ---
    console.print()
    if risk["tradeable"]:
        console.print(f"[bold]Position sizing:[/bold]")
        console.print(f"  Shares: {risk['position_shares']} @ ~${risk['entry_price']}")
        console.print(f"  Position value: ${risk['position_value']:,.2f} ({risk['position_pct_of_capital']}% of capital)")
        console.print(f"  Stop-loss: ${risk['stop_loss']}  |  Take-profit: ${risk['take_profit']}")
        console.print(f"  Risk: ${risk['risk_amount']:,.2f}  |  Potential reward: ${risk['reward_amount']:,.2f}")
    else:
        console.print("[dim]No position sized.[/dim]")
    for n in risk["notes"]:
        console.print(f"  [dim]- {n}[/dim]")

    if combined.get("paper_trade_message"):
        console.print(f"\n[bold cyan]Paper Trading:[/bold cyan] {combined['paper_trade_message']}")

    if combined.get("db_error"):
        console.print(f"\n[yellow]Warning: could not log to database ({combined['db_error']})[/yellow]")
    else:
        console.print("\n[dim]Logged to decision history.[/dim]")


@app.command()
def scan(
    synthetic: bool = typer.Option(False, help="Use synthetic data (offline testing)"),
    manual: bool = typer.Option(False, "--manual", help="Don't auto-execute paper trades even on a sized BUY"),
    sector: str = typer.Option(None, help="Only scan one sector (see `bonaid sectors` for names). Omit to scan the full universe."),
):
    """Run the full agent pipeline across the diversified universe (~46
    instruments spanning tech, healthcare, aerospace, crypto, forex,
    financials, energy, consumer, industrials, broad-market ETFs, and
    India/NSE) instead of one ticker at a time. Auto-executes paper trades
    on sized BUYs unless --manual is passed - same behavior as `analyze`,
    just looped across the whole universe in one command."""
    from bonaid.universe import all_tickers, tickers_for_sector, sector_of

    tickers = tickers_for_sector(sector) if sector else all_tickers()
    if not tickers:
        console.print(f"[red]No tickers found for sector '{sector}'. Run `bonaid sectors` to see valid names.[/red]")
        raise typer.Exit(1)

    console.print(f"Scanning {len(tickers)} tickers...\n")

    results = []
    table = Table()
    table.add_column("Ticker")
    table.add_column("Sector")
    table.add_column("Action")
    table.add_column("Confidence", justify="right")
    table.add_column("Note")

    for ticker in tickers:
        try:
            with console.status(f"Analyzing {ticker}..."):
                combined = _run_and_execute(ticker, synthetic=synthetic, manual=manual)
            decision = combined["supervisor_decision"]
            action_color = {"BUY": "green", "SELL": "red", "WATCH": "yellow", "HOLD": "white"}.get(decision["action"], "white")
            note = combined.get("paper_trade_message") or ""

            # Categorize the paper-trade outcome so the summary can break
            # down BUY signals into what actually happened, not just count
            # them - "8 BUY signals" was hiding that most were duplicates/
            # refusals, not new executions.
            if note.startswith("REFUSED"):
                outcome = "refused_exposure"
                note_display = f"[red]{note[:55]}[/red]"
            elif note.startswith("Position already open"):
                outcome = "duplicate"
                note_display = f"[dim]{note[:55]}[/dim]"
            elif note.startswith("Opened paper position"):
                outcome = "opened"
                note_display = f"[green]{note[:55]}[/green]"
            elif note.startswith("--manual"):
                outcome = "manual_skip"
                note_display = note[:55]
            else:
                outcome = None
                note_display = note[:55]

            table.add_row(
                ticker, sector_of(ticker),
                f"[{action_color}]{decision['action']}[/{action_color}]",
                f"{decision['confidence']}%",
                note_display,
            )
            results.append({"ticker": ticker, "action": decision["action"], "confidence": decision["confidence"], "outcome": outcome})
        except Exception as e:
            table.add_row(ticker, sector_of(ticker), "[red]ERROR[/red]", "-", str(e)[:60])
            console.print(f"[dim][{ticker}] scan error (continuing): {e}[/dim]")

    console.print(table)

    buys = [r for r in results if r["action"] == "BUY"]
    opened = [r for r in buys if r["outcome"] == "opened"]
    refused = [r for r in buys if r["outcome"] == "refused_exposure"]
    duplicates = [r for r in buys if r["outcome"] == "duplicate"]

    console.print(f"\n[bold]Scan complete.[/bold] {len(results)}/{len(tickers)} succeeded, {len(buys)} BUY signal(s).")
    if buys:
        summary_parts = [f"[green]{len(opened)} opened[/green]"]
        if duplicates:
            summary_parts.append(f"[dim]{len(duplicates)} already open[/dim]")
        if refused:
            summary_parts.append(f"[red]{len(refused)} refused (exposure cap)[/red]")
        console.print("  " + ", ".join(summary_parts))
        if refused:
            console.print(
                f"  [yellow]Note: {len(refused)} signal(s) were refused because total portfolio exposure "
                f"would have exceeded the {settings.max_total_exposure_pct}% cap. Run `bonaid portfolio` "
                f"to review, or close positions to free up room.[/yellow]"
            )


@app.command()
def sectors():
    """List available sectors for `bonaid scan --sector <name>`."""
    from bonaid.universe import UNIVERSE
    for name, tickers in UNIVERSE.items():
        console.print(f"[bold]{name}[/bold]: {', '.join(tickers)}")


@app.command("fix-position-precision")
def fix_position_precision():
    """One-off maintenance command: rounds entry_price/stop_loss/take_profit
    to 2 decimals on any existing OPEN positions that were created before
    the rounding fix (e.g. a position showing $754.8099975585938 instead
    of $754.81). Safe to run anytime - a no-op if everything's already rounded."""
    from bonaid.models import PaperPosition

    fixed = 0
    with get_session() as s:
        positions = s.query(PaperPosition).filter(PaperPosition.status == "OPEN").all()
        for p in positions:
            new_entry = round(p.entry_price, 2)
            new_stop = round(p.stop_loss, 2)
            new_target = round(p.take_profit, 2)
            if (p.entry_price, p.stop_loss, p.take_profit) != (new_entry, new_stop, new_target):
                p.entry_price, p.stop_loss, p.take_profit = new_entry, new_stop, new_target
                fixed += 1

    console.print(f"Fixed precision on {fixed} position(s)." if fixed else "Nothing to fix - all positions already rounded.")


@app.command("alert-check")
def alert_check():
    """Send a test notification to every configured channel (Telegram/
    email) so you can confirm alerting actually works before relying on it
    during real trading events."""
    from bonaid.notifier import notify

    console.print("[bold]Alert configuration:[/bold]")
    console.print(f"  Telegram: {'configured' if settings.telegram_bot_token and settings.telegram_chat_id else '[dim]not configured[/dim]'}")
    console.print(f"  Email:    {'configured' if settings.smtp_host and settings.smtp_user else '[dim]not configured[/dim]'}")
    console.print(f"  Alerts enabled: {settings.alerts_enabled}")

    if not settings.telegram_bot_token and not settings.smtp_host:
        console.print("\n[yellow]No channels configured - nothing to test. Set TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID "
                       "and/or SMTP_HOST/SMTP_USER/SMTP_PASS/ALERT_EMAIL_TO in .env.[/yellow]")
        raise typer.Exit(1)

    console.print("\nSending test notification...")
    result = notify("Bonaid: Test Alert", "This is a test notification from `bonaid alert-check`. If you received this, alerting is working correctly.")

    for channel, ok in result.items():
        status = "[green]sent[/green]" if ok else "[dim]skipped/failed (see above for detail if configured)[/dim]"
        console.print(f"  {channel}: {status}")


@app.command("reddit-check")
def reddit_check():
    """Diagnose Reddit OAuth setup - shows masked credentials as actually
    loaded, then attempts the token request with full error detail. Use
    this to isolate credential/whitespace issues from network issues."""
    from bonaid.config import settings
    import requests

    def mask(s: str | None) -> str:
        if not s:
            return "(not set)"
        if len(s) <= 6:
            return f"({len(s)} chars, too short to mask safely - check for truncation)"
        return f"{s[:3]}...{s[-3:]} ({len(s)} chars)"

    console.print("[bold]Reddit credentials as loaded from .env:[/bold]")
    console.print(f"  REDDIT_CLIENT_ID:     {mask(settings.reddit_client_id)}")
    console.print(f"  REDDIT_CLIENT_SECRET: {mask(settings.reddit_client_secret)}")
    console.print(f"  REDDIT_USERNAME:      {settings.reddit_username or '(not set)'}")

    if settings.reddit_client_id and (settings.reddit_client_id != settings.reddit_client_id.strip()):
        console.print("[red]  WARNING: REDDIT_CLIENT_ID has leading/trailing whitespace![/red]")
    if settings.reddit_client_secret and (settings.reddit_client_secret != settings.reddit_client_secret.strip()):
        console.print("[red]  WARNING: REDDIT_CLIENT_SECRET has leading/trailing whitespace![/red]")

    if not settings.reddit_client_id or not settings.reddit_client_secret:
        console.print("\n[yellow]Credentials not configured - nothing further to test.[/yellow]")
        raise typer.Exit(1)

    console.print("\n[bold]Attempting OAuth token request...[/bold]")
    user_agent = f"bonaid-research-agent/0.2 by u/{settings.reddit_username or 'unknown-user'} (personal free/open-source trading research tool)"
    console.print(f"  User-Agent: {user_agent}")

    try:
        resp = requests.post(
            "https://www.reddit.com/api/v1/access_token",
            auth=(settings.reddit_client_id, settings.reddit_client_secret),
            data={"grant_type": "client_credentials"},
            headers={"User-Agent": user_agent},
            timeout=10,
        )
        console.print(f"  HTTP status: {resp.status_code}")
        console.print(f"  Response headers: {dict(resp.headers)}")
        console.print(f"  Response body: {resp.text}")
        if resp.status_code == 200:
            console.print("\n[green]SUCCESS - token obtained.[/green]")
        else:
            console.print("\n[red]FAILED - see status/body above.[/red]")
    except Exception as e:
        console.print(f"[red]Request raised {type(e).__name__}: {e}[/red]")


@app.command("check-positions")
def check_positions(synthetic: bool = typer.Option(False, help="Use synthetic data (offline testing)")):
    """Check every open paper position against its latest price, closing
    any that hit stop-loss or take-profit. Safe to run anytime/on a schedule."""
    from bonaid.agents.paper_trading import check_all_positions

    with console.status("Checking open positions..."):
        events = check_all_positions(use_synthetic=synthetic)

    if not events:
        console.print("[dim]No open positions to check.[/dim]")
        return

    for e in events:
        if e["event"] == "closed":
            color = "green" if e["pnl"] > 0 else "red"
            console.print(
                f"[{color}]CLOSED[/{color}] {e['ticker']}: {e['shares']} shares, exit ${e['exit_price']} "
                f"({e['reason']}) - P&L: ${e['pnl']:,.2f}"
            )
        elif e["event"] == "held":
            console.print(
                f"[dim]HELD[/dim] {e['ticker']}: price ${e['current_price']} "
                f"(stop ${e['stop_loss']}, target ${e['take_profit']})"
            )
        elif e["event"] == "price_fetch_failed":
            console.print(f"[yellow]WARNING[/yellow] {e['ticker']}: could not fetch price - {e['detail']}")


@app.command()
def positions():
    """Show all currently open paper positions."""
    from bonaid.db import get_session
    from bonaid.models import PaperPosition

    with get_session() as s:
        open_positions = s.query(PaperPosition).filter(PaperPosition.status == "OPEN").all()
        if not open_positions:
            console.print("[dim]No open positions.[/dim]")
            return

        table = Table(title="Open Paper Positions")
        table.add_column("Ticker")
        table.add_column("Shares", justify="right")
        table.add_column("Entry", justify="right")
        table.add_column("Stop-Loss", justify="right")
        table.add_column("Take-Profit", justify="right")
        table.add_column("Entry Date")
        for p in open_positions:
            table.add_row(p.ticker, str(p.shares), f"${p.entry_price}", f"${p.stop_loss}", f"${p.take_profit}", p.entry_date.strftime("%Y-%m-%d %H:%M"))
        console.print(table)


@app.command()
def close(ticker: str, exit_price: float = typer.Argument(..., help="Price to close the position at")):
    """Manually close an open position at a given price, regardless of stop/take-profit."""
    from bonaid.agents.paper_trading import close_position_manually
    msg = close_position_manually(ticker, exit_price)
    console.print(msg)


@app.command()
def pnl():
    """Show aggregate realized P&L across all closed paper trades."""
    from bonaid.agents.paper_trading import get_pnl_summary
    summary = get_pnl_summary()

    if summary["trade_count"] == 0:
        console.print("[dim]No closed trades yet.[/dim]")
        return

    pnl_color = "green" if summary["total_pnl"] > 0 else "red"
    console.print(f"\n[bold]Realized P&L Summary[/bold]")
    console.print(f"Trades closed: {summary['trade_count']}")
    console.print(f"Total P&L: [{pnl_color}]${summary['total_pnl']:,.2f}[/{pnl_color}]")
    console.print(f"Win rate: {summary['win_rate']}% ({summary['wins']} wins, {summary['losses']} losses)")


@app.command("drawdown")
def drawdown_status(synthetic: bool = typer.Option(False, help="Use synthetic data (offline testing)")):
    """Show TOTAL unrealized P&L across all open positions and whether it
    has breached the portfolio-level drawdown guideline - the check
    individual per-position stop-losses don't catch (every position can be
    above its own stop while the portfolio is still down badly overall)."""
    from bonaid.db import get_session
    from bonaid.models import PaperPosition
    from bonaid.agents.paper_trading import evaluate_portfolio_drawdown

    if synthetic:
        from bonaid.analysis.synthetic_data import generate_universe
    else:
        from bonaid.analysis.data_fetcher import fetch_ohlcv

    with get_session() as s:
        open_positions = s.query(PaperPosition).filter(PaperPosition.status == "OPEN").all()
        if not open_positions:
            console.print("[dim]No open positions.[/dim]")
            return

        positions_with_price = []
        with console.status("Fetching current prices..."):
            for pos in open_positions:
                try:
                    df = generate_universe([pos.ticker], years=1)[pos.ticker] if synthetic else fetch_ohlcv(pos.ticker, years=1)
                    current_price = round(float(df["Close"].iloc[-1]), 2)
                    positions_with_price.append({
                        "ticker": pos.ticker, "shares": pos.shares,
                        "entry_price": pos.entry_price, "current_price": current_price,
                    })
                except Exception as e:
                    console.print(f"[yellow]Could not fetch price for {pos.ticker}: {e}[/yellow]")

    result = evaluate_portfolio_drawdown(positions_with_price, settings.default_capital, settings.max_portfolio_drawdown_pct)

    pnl_color = "green" if result["total_unrealized_pnl"] >= 0 else "red"
    console.print(f"\n[bold]Portfolio Drawdown Status[/bold]")
    console.print(f"Unrealized P&L: [{pnl_color}]${result['total_unrealized_pnl']:,.2f}[/{pnl_color}] ({result['drawdown_pct']}% of capital)")
    console.print(f"Guideline: -{settings.max_portfolio_drawdown_pct}%")
    if result["breached"]:
        console.print(f"[red bold]BREACHED[/red bold] - {'auto-close would trigger on next `check-positions` run' if settings.auto_close_on_drawdown else 'alert-only (AUTO_CLOSE_ON_DRAWDOWN is False)'}")
    else:
        console.print("[green]Within guideline.[/green]")


@app.command()
def portfolio(capital: float = typer.Option(None, help="Override total capital (defaults to settings.default_capital)")):
    """Show aggregate exposure across the decision history - implied open
    positions, total capital deployed, and concentration warnings."""
    from bonaid.agents.portfolio_agent import get_portfolio_snapshot

    with console.status("Building portfolio snapshot..."):
        snap = get_portfolio_snapshot(capital=capital)

    console.print(f"\n[bold]Portfolio Snapshot[/bold]")
    console.print(f"Total capital: ${snap.total_capital:,.2f}")
    console.print(f"Deployed: ${snap.deployed_capital:,.2f} ({snap.deployed_pct}%)")
    console.print(f"Open positions (implied from latest decisions): {snap.position_count}")

    if snap.positions:
        table = Table()
        table.add_column("Ticker")
        table.add_column("Shares", justify="right")
        table.add_column("Value", justify="right")
        table.add_column("% of Capital", justify="right")
        table.add_column("Confidence", justify="right")
        for p in snap.positions:
            table.add_row(p.ticker, str(p.shares), f"${p.position_value:,.2f}", f"{p.pct_of_capital}%", f"{p.confidence}%")
        console.print(table)

    if snap.warnings:
        console.print("\n[yellow bold]Warnings:[/yellow bold]")
        for w in snap.warnings:
            console.print(f"  [yellow]- {w}[/yellow]")


@app.command()
def version():
    console.print(f"{settings.app_name} - Foundation + Technical + News + Risk Agents - environment={settings.environment}")


if __name__ == "__main__":
    app()
