"""
bonaid/cli.py
The terminal application entrypoint - `bonaid <command>`.
Phase 1: status, init-db, ping (graph), llm-check.
Phase 3 (first agent): analyze - runs the Technical Agent end-to-end.
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


@app.command()
def analyze(ticker: str, synthetic: bool = typer.Option(False, help="Use synthetic data (offline testing)")):
    """Run the Technical Agent on a ticker and print a recommendation."""
    from bonaid.models import AgentDecision

    with console.status(f"Analyzing {ticker}..."):
        result = graph_mod.run_technical_analysis(ticker, use_synthetic=synthetic)

    action_color = {"BUY": "green", "SELL": "red", "WATCH": "yellow", "HOLD": "white"}.get(result["action"], "white")
    console.print(f"\nRecommendation: [{action_color}]{result['action']} {result['ticker']}[/{action_color}]")
    console.print(f"Confidence: {result['confidence']}%")
    console.print("Reasons:")
    for r in result["reasons"]:
        console.print(f"  - {r}")
    if result.get("llm_summary"):
        console.print(f"\n[dim]{result['llm_summary']}[/dim]")

    try:
        with get_session() as s:
            s.add(AgentDecision(
                ticker=result["ticker"],
                action=result["action"],
                confidence=result["confidence"],
                reasons=result["reasons"],
                signal_breakdown=result["signal_breakdown"],
                llm_summary=result.get("llm_summary"),
            ))
        console.print("\n[dim]Logged to decision history.[/dim]")
    except Exception as e:
        console.print(f"\n[yellow]Warning: could not log to database ({e})[/yellow]")


@app.command()
def version():
    console.print(f"{settings.app_name} - Phase 1+ (Foundation + Technical Agent) - environment={settings.environment}")


if __name__ == "__main__":
    app()
