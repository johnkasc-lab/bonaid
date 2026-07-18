"""
bonaid/agents/news_agent.py
Third real agent. Free, no API key: pulls recent headlines for a ticker from
Google News RSS, scores sentiment with a deterministic keyword lexicon (fast,
zero external dependency beyond the fetch itself, works even if Ollama is
down), and optionally asks the local LLM for a one-paragraph narrative
summary - same graceful-degradation pattern as the Technical Agent.

This agent does NOT yet change the BUY/SELL decision - it runs alongside
Technical and its output is surfaced for the human to read. Reconciling
"Technical says BUY, News sentiment is very negative" is the Supervisor's
job once a second/third opinion-generating agent (Sentiment) also exists -
building that logic properly with only one voice to weigh would mean
guessing at weights with nothing to calibrate them against.
"""
from dataclasses import dataclass, field
from urllib.parse import quote
import re

import feedparser

GOOGLE_NEWS_RSS = "https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"

# Deliberately simple, transparent, and auditable - a human can read this
# list and understand exactly why a headline scored the way it did, unlike
# a black-box model. Good enough for a first pass; swap for a proper
# finance-tuned sentiment model later if this proves too coarse in practice.
POSITIVE_WORDS = {
    "beat", "beats", "surge", "surges", "soar", "soars", "rally", "rallies",
    "upgrade", "upgraded", "outperform", "record", "growth", "profit",
    "gain", "gains", "bullish", "strong", "boost", "boosts", "jump", "jumps",
    "win", "wins", "expansion", "buy", "raises", "raised", "positive",
    "exceeds", "breakthrough", "partnership", "approval", "approved",
}
NEGATIVE_WORDS = {
    "miss", "misses", "plunge", "plunges", "crash", "crashes", "downgrade",
    "downgraded", "underperform", "loss", "losses", "decline", "declines",
    "bearish", "weak", "cut", "cuts", "fall", "falls", "drop", "drops",
    "lawsuit", "investigation", "recall", "layoffs", "layoff", "fraud",
    "sell-off", "selloff", "warning", "concern", "concerns", "delay",
    "delayed", "negative", "probe", "scandal", "bankruptcy",
}


@dataclass
class NewsAnalysis:
    ticker: str
    sentiment_label: str          # "Positive" | "Negative" | "Neutral" | "Mixed" | "No Data"
    sentiment_score: float        # -100 to +100
    headline_count: int
    reasons: list = field(default_factory=list)
    headlines: list = field(default_factory=list)  # [{title, sentiment, link}, ...]
    llm_summary: str | None = None


def _clean_query_ticker(ticker: str) -> str:
    """Strip exchange suffixes (.NS, .BO) for a cleaner news search - 'RELIANCE.NS'
    searches much worse than 'RELIANCE' on a general news search engine."""
    return re.sub(r"\.(NS|BO)$", "", ticker, flags=re.IGNORECASE)


def fetch_headlines(ticker: str, max_items: int = 15, timeout: int = 10) -> list:
    """Returns a list of {title, link, published, source} dicts. Returns an
    empty list (not an exception) on any fetch failure - the agent still
    produces a valid 'No Data' result rather than crashing the whole
    analyze pipeline over a flaky news source."""
    query = quote(f"{_clean_query_ticker(ticker)} stock")
    url = GOOGLE_NEWS_RSS.format(query=query)
    try:
        feed = feedparser.parse(url)
        items = []
        for entry in feed.entries[:max_items]:
            items.append({
                "title": entry.get("title", ""),
                "link": entry.get("link", ""),
                "published": entry.get("published", ""),
                "source": entry.get("source", {}).get("title", "") if entry.get("source") else "",
            })
        return items
    except Exception:
        return []


def _score_headline(title: str) -> int:
    """+1 / -1 / 0 for a single headline, based on lexicon word overlap."""
    words = set(re.findall(r"[a-z']+", title.lower()))
    pos = len(words & POSITIVE_WORDS)
    neg = len(words & NEGATIVE_WORDS)
    if pos > neg:
        return 1
    if neg > pos:
        return -1
    return 0


def analyze_news(ticker: str, headlines: list) -> NewsAnalysis:
    """Core logic: pure function, no I/O - takes headlines already fetched,
    easy to unit test with synthetic headline lists."""
    if not headlines:
        return NewsAnalysis(
            ticker=ticker,
            sentiment_label="No Data",
            sentiment_score=0.0,
            headline_count=0,
            reasons=["No recent headlines found - news feed may be sparse for this ticker, or fetch failed."],
        )

    scored = []
    total = 0
    for h in headlines:
        s = _score_headline(h["title"])
        total += s
        scored.append({**h, "sentiment": {1: "Positive", -1: "Negative", 0: "Neutral"}[s]})

    n = len(headlines)
    sentiment_score = round((total / n) * 100, 1)  # -100..100

    pos_count = sum(1 for h in scored if h["sentiment"] == "Positive")
    neg_count = sum(1 for h in scored if h["sentiment"] == "Negative")
    neu_count = n - pos_count - neg_count

    if sentiment_score >= 25:
        label = "Positive"
    elif sentiment_score <= -25:
        label = "Negative"
    elif pos_count > 0 and neg_count > 0 and abs(pos_count - neg_count) <= 1:
        label = "Mixed"
    else:
        label = "Neutral"

    reasons = [
        f"{n} recent headlines analyzed: {pos_count} positive, {neg_count} negative, {neu_count} neutral",
    ]
    if neg_count > 0:
        worst = next(h for h in scored if h["sentiment"] == "Negative")
        reasons.append(f"Notable negative: \"{worst['title']}\"")
    if pos_count > 0:
        best = next(h for h in scored if h["sentiment"] == "Positive")
        reasons.append(f"Notable positive: \"{best['title']}\"")

    return NewsAnalysis(
        ticker=ticker,
        sentiment_label=label,
        sentiment_score=sentiment_score,
        headline_count=n,
        reasons=reasons,
        headlines=scored,
    )


def summarize_with_llm(analysis: NewsAnalysis) -> str | None:
    """Optional: ask Ollama to narrate the news picture in plain English.
    Returns None if Ollama isn't reachable or there's no data to summarize."""
    from bonaid import llm
    if not llm.is_available() or analysis.headline_count == 0:
        return None

    headline_lines = "\n".join(f"- {h['title']} ({h['sentiment']})" for h in analysis.headlines[:10])
    prompt = (
        f"You are a financial news summarizer. Given these recent headlines for {analysis.ticker} "
        f"(aggregate sentiment: {analysis.sentiment_label}, score {analysis.sentiment_score}), "
        f"write ONE short plain-English paragraph (3-4 sentences max) summarizing what's happening. "
        f"Be factual and measured, not hyped. Do not give financial advice.\n\n"
        f"Headlines:\n{headline_lines}"
    )
    try:
        return llm.generate(prompt).strip()
    except Exception:
        return None
