"""
bonaid/graph.py
Phase 1 goal here is narrow: prove the LangGraph wiring works end-to-end with
a real, runnable graph - not build the real agents yet (that's Phase 3-4).
This graph has exactly one node ("ping") so `bonaid status` can prove the
orchestration layer is alive. Later phases add nodes: technical, news,
sentiment, macro, risk, portfolio - all feeding into a "supervisor" node
that aggregates them, matching the architecture in the project plan.
"""
from typing import TypedDict
from langgraph.graph import StateGraph, END


class BonaidState(TypedDict, total=False):
    query: str
    ticker: str | None
    messages: list
    result: str


def _ping_node(state: BonaidState) -> BonaidState:
    """Placeholder node. Phase 3 replaces/extends this with real agent nodes
    (technical_node, news_node, sentiment_node, macro_node, risk_node,
    portfolio_node) all wired into this same graph."""
    ticker = state.get("ticker", "N/A")
    state["result"] = f"Bonaid orchestration graph is alive. (query='{state.get('query')}', ticker='{ticker}')"
    return state


def build_graph():
    graph = StateGraph(BonaidState)
    graph.add_node("ping", _ping_node)
    graph.set_entry_point("ping")
    graph.add_edge("ping", END)
    return graph.compile()


def run_ping(query: str = "healthcheck", ticker: str | None = None) -> str:
    app = build_graph()
    out = app.invoke({"query": query, "ticker": ticker, "messages": []})
    return out["result"]
