"""
bonaid/graph.py
The orchestration layer. Phase 1 proved the wiring with a single "ping"
node. This now adds the first REAL node: "technical" - which runs the
Technical Agent. Future phases add more nodes (news, sentiment, macro, risk,
portfolio) and a real "supervisor" node that aggregates all of them; today,
with only one analysis agent, the supervisor step is a pass-through, but the
graph shape is already correct for when it isn't.
"""
from typing import TypedDict
from langgraph.graph import StateGraph, END


class BonaidState(TypedDict, total=False):
    query: str
    ticker: str | None
    messages: list
    result: str
    technical_analysis: dict | None
    use_synthetic: bool


def _ping_node(state: BonaidState) -> BonaidState:
    """Healthcheck node - proves the orchestration layer itself is alive,
    independent of any real analysis (used by `bonaid status` and `bonaid ping`)."""
    ticker = state.get("ticker", "N/A")
    state["result"] = f"Bonaid orchestration graph is alive. (query='{state.get('query')}', ticker='{ticker}')"
    return state


def _technical_node(state: BonaidState) -> BonaidState:
    """Real analysis node: fetches data for state['ticker'] and runs the
    Technical Agent, storing a structured result back into state."""
    from bonaid.agents.technical_agent import analyze_ticker, summarize_with_llm

    ticker = state["ticker"]
    if state.get("use_synthetic"):
        from bonaid.analysis.synthetic_data import generate_universe
        data = generate_universe([ticker], years=5)
    else:
        from bonaid.analysis.data_fetcher import fetch_ohlcv
        data = {ticker: fetch_ohlcv(ticker, years=5)}

    df = data[ticker]
    analysis = analyze_ticker(ticker, df)
    llm_summary = summarize_with_llm(analysis)

    state["technical_analysis"] = {
        "ticker": analysis.ticker,
        "action": analysis.action,
        "confidence": analysis.confidence,
        "reasons": analysis.reasons,
        "signal_breakdown": analysis.signal_breakdown,
        "llm_summary": llm_summary,
    }
    state["result"] = f"{analysis.action} {ticker} ({analysis.confidence}% confidence)"
    return state


def build_graph():
    graph = StateGraph(BonaidState)
    graph.add_node("ping", _ping_node)
    graph.add_node("technical", _technical_node)
    graph.set_entry_point("ping")
    graph.add_edge("ping", END)
    return graph.compile()


def build_analysis_graph():
    """Separate compiled graph whose entry point is the technical node.
    Kept separate from build_graph() (ping) so `bonaid status` stays a fast,
    dependency-free healthcheck while `bonaid analyze` goes through the real
    analysis path. Phase 3+ merges these into one supervisor-routed graph."""
    graph = StateGraph(BonaidState)
    graph.add_node("technical", _technical_node)
    graph.set_entry_point("technical")
    graph.add_edge("technical", END)
    return graph.compile()


def run_ping(query: str = "healthcheck", ticker: str | None = None) -> str:
    app = build_graph()
    out = app.invoke({"query": query, "ticker": ticker, "messages": []})
    return out["result"]


def run_technical_analysis(ticker: str, use_synthetic: bool = False) -> dict:
    app = build_analysis_graph()
    out = app.invoke({"ticker": ticker, "messages": [], "use_synthetic": use_synthetic})
    return out["technical_analysis"]
