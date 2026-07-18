"""
bonaid/graph.py
The orchestration layer. Five real nodes:
  technical -> news -> sentiment -> supervisor -> risk

Technical, News, and Sentiment each analyze independently. Supervisor
reconciles their outputs into one final action (see
bonaid/agents/supervisor.py for the reconciliation rules). Risk sizes a
position off the SUPERVISOR's action, not Technical's raw action directly.

LLM narration (the plain-English paragraphs) is gated behind
settings.enable_llm_narration, OFF by default - confirmed hallucinating
(fabricating events, inverting sentiment polarity) on qwen2.5:0.5b/1.5b in
testing. The structured decision data never depends on the LLM either way.
"""
from typing import TypedDict
from langgraph.graph import StateGraph, END


class BonaidState(TypedDict, total=False):
    query: str
    ticker: str | None
    messages: list
    result: str
    technical_analysis: dict | None
    news_assessment: dict | None
    sentiment_assessment: dict | None
    supervisor_decision: dict | None
    risk_assessment: dict | None
    use_synthetic: bool
    capital: float | None
    _df_cache: object | None


def _ping_node(state: BonaidState) -> BonaidState:
    """Healthcheck node - proves the orchestration layer itself is alive,
    independent of any real analysis (used by `bonaid status` and `bonaid ping`)."""
    ticker = state.get("ticker", "N/A")
    state["result"] = f"Bonaid orchestration graph is alive. (query='{state.get('query')}', ticker='{ticker}')"
    return state


def _fetch_df(ticker: str, use_synthetic: bool):
    if use_synthetic:
        from bonaid.analysis.synthetic_data import generate_universe
        return generate_universe([ticker], years=5)[ticker]
    else:
        from bonaid.analysis.data_fetcher import fetch_ohlcv
        return fetch_ohlcv(ticker, years=5)


def _technical_node(state: BonaidState) -> BonaidState:
    """Runs the Technical Agent, storing a structured result back into state."""
    from bonaid.agents.technical_agent import analyze_ticker, summarize_with_llm
    from bonaid.config import settings

    ticker = state["ticker"]
    df = _fetch_df(ticker, state.get("use_synthetic", False))
    analysis = analyze_ticker(ticker, df)
    llm_summary = summarize_with_llm(analysis) if settings.enable_llm_narration else None

    state["technical_analysis"] = {
        "ticker": analysis.ticker,
        "action": analysis.action,
        "confidence": analysis.confidence,
        "reasons": analysis.reasons,
        "signal_breakdown": analysis.signal_breakdown,
        "llm_summary": llm_summary,
    }
    state["_df_cache"] = df  # passed to the risk node in-memory, not persisted
    return state


def _news_node(state: BonaidState) -> BonaidState:
    """Runs the News Agent. Skipped entirely for synthetic runs since
    there's no synthetic news source (and no live tickers to look up)."""
    if state.get("use_synthetic"):
        state["news_assessment"] = {
            "ticker": state["ticker"], "sentiment_label": "No Data", "sentiment_score": 0.0,
            "headline_count": 0, "reasons": ["Skipped - synthetic mode has no real ticker to fetch news for."],
            "headlines": [], "llm_summary": None,
        }
        return state

    from bonaid.agents.news_agent import fetch_headlines, analyze_news, summarize_with_llm
    from bonaid.config import settings

    ticker = state["ticker"]
    headlines = fetch_headlines(ticker)
    analysis = analyze_news(ticker, headlines)
    llm_summary = summarize_with_llm(analysis) if settings.enable_llm_narration else None

    state["news_assessment"] = {
        "ticker": analysis.ticker,
        "sentiment_label": analysis.sentiment_label,
        "sentiment_score": analysis.sentiment_score,
        "headline_count": analysis.headline_count,
        "reasons": analysis.reasons,
        "headlines": analysis.headlines,
        "llm_summary": llm_summary,
    }
    return state


def _sentiment_node(state: BonaidState) -> BonaidState:
    """Runs the Sentiment Agent (Reddit-based). Skipped for synthetic runs
    for the same reason News is - no synthetic social data source."""
    if state.get("use_synthetic"):
        state["sentiment_assessment"] = {
            "ticker": state["ticker"], "sentiment_label": "No Data", "sentiment_score": 0.0,
            "mention_count": 0, "reasons": ["Skipped - synthetic mode has no real ticker to fetch mentions for."],
            "posts": [], "llm_summary": None,
        }
        return state

    from bonaid.agents.sentiment_agent import fetch_mentions, analyze_sentiment, summarize_with_llm
    from bonaid.config import settings

    ticker = state["ticker"]
    posts = fetch_mentions(ticker)
    analysis = analyze_sentiment(ticker, posts)
    llm_summary = summarize_with_llm(analysis) if settings.enable_llm_narration else None

    state["sentiment_assessment"] = {
        "ticker": analysis.ticker,
        "sentiment_label": analysis.sentiment_label,
        "sentiment_score": analysis.sentiment_score,
        "mention_count": analysis.mention_count,
        "reasons": analysis.reasons,
        "posts": analysis.posts,
        "llm_summary": llm_summary,
    }
    return state


def _supervisor_node(state: BonaidState) -> BonaidState:
    """Reconciles Technical + News + Sentiment into one final action. This
    is what Risk sizes off - not technical_analysis directly."""
    from bonaid.agents.supervisor import reconcile

    ticker = state["ticker"]
    decision = reconcile(ticker, state["technical_analysis"], state["news_assessment"], state["sentiment_assessment"])

    state["supervisor_decision"] = {
        "ticker": decision.ticker,
        "action": decision.action,
        "confidence": decision.confidence,
        "overridden": decision.overridden,
        "technical_action": decision.technical_action,
        "technical_confidence": decision.technical_confidence,
        "news_sentiment": decision.news_sentiment,
        "social_sentiment": decision.social_sentiment,
        "reasoning": decision.reasoning,
    }
    return state


def _risk_node(state: BonaidState) -> BonaidState:
    """Runs the Risk Agent on the SUPERVISOR's final decision (not raw
    Technical output - see module docstring)."""
    from bonaid.agents.risk_agent import assess_risk

    ticker = state["ticker"]
    decision = state["supervisor_decision"]
    df = state.get("_df_cache")
    if df is None:
        df = _fetch_df(ticker, state.get("use_synthetic", False))

    risk = assess_risk(
        ticker=ticker,
        df=df,
        action=decision["action"],
        confidence=decision["confidence"],
        capital=state.get("capital"),
    )
    state["risk_assessment"] = {
        "tradeable": risk.tradeable,
        "position_shares": risk.position_shares,
        "position_value": risk.position_value,
        "position_pct_of_capital": risk.position_pct_of_capital,
        "entry_price": risk.entry_price,
        "stop_loss": risk.stop_loss,
        "take_profit": risk.take_profit,
        "risk_amount": risk.risk_amount,
        "reward_amount": risk.reward_amount,
        "notes": risk.notes,
    }
    state["result"] = f"{decision['action']} {ticker} ({decision['confidence']}% confidence) -> {risk.position_shares} shares"
    return state


def build_graph():
    graph = StateGraph(BonaidState)
    graph.add_node("ping", _ping_node)
    graph.set_entry_point("ping")
    graph.add_edge("ping", END)
    return graph.compile()


def build_analysis_graph():
    """technical -> news -> sentiment -> supervisor -> risk"""
    graph = StateGraph(BonaidState)
    graph.add_node("technical", _technical_node)
    graph.add_node("news", _news_node)
    graph.add_node("sentiment", _sentiment_node)
    graph.add_node("supervisor", _supervisor_node)
    graph.add_node("risk", _risk_node)
    graph.set_entry_point("technical")
    graph.add_edge("technical", "news")
    graph.add_edge("news", "sentiment")
    graph.add_edge("sentiment", "supervisor")
    graph.add_edge("supervisor", "risk")
    graph.add_edge("risk", END)
    return graph.compile()


def run_ping(query: str = "healthcheck", ticker: str | None = None) -> str:
    app = build_graph()
    out = app.invoke({"query": query, "ticker": ticker, "messages": []})
    return out["result"]


def run_technical_analysis(ticker: str, use_synthetic: bool = False, capital: float | None = None) -> dict:
    """Returns {'technical_analysis', 'news_assessment', 'sentiment_assessment', 'supervisor_decision', 'risk_assessment'}"""
    app = build_analysis_graph()
    out = app.invoke({
        "ticker": ticker,
        "messages": [],
        "use_synthetic": use_synthetic,
        "capital": capital,
    })
    return {
        "technical_analysis": out["technical_analysis"],
        "news_assessment": out["news_assessment"],
        "sentiment_assessment": out["sentiment_assessment"],
        "supervisor_decision": out["supervisor_decision"],
        "risk_assessment": out["risk_assessment"],
    }
