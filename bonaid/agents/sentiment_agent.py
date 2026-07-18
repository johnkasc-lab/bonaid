"""
bonaid/agents/sentiment_agent.py
Fifth real agent. Pulls recent public posts mentioning a ticker and scores
retail sentiment.

PRIMARY source: StockTwits' public API - purpose-built for stock sentiment
(users self-tag posts as Bullish/Bearish), no OAuth app registration, no
account verification step. Used first, always.

SECONDARY source: Reddit (OAuth) - only tried if StockTwits returns nothing
AND Reddit credentials are configured in .env. Kept as a fallback since the
code already exists and works once Reddit-side account issues are resolved,
but no longer required for this agent to function out of the box.

Sentiment scoring: when a post has StockTwits' own Bullish/Bearish tag, that
tag is used directly (a human already labeled it - more reliable than any
lexicon). Posts without a tag (and all Reddit posts) fall back to the same
lexicon-based scoring as before, tuned for retail/social trading slang.

Upvote/like-weighted: a highly-engaged post represents more community
agreement than a single obscure one, so each post's contribution to the
aggregate score is weighted (and capped) by its engagement count - this
stops one viral post from single-handedly deciding the aggregate.
"""
from dataclasses import dataclass, field
from urllib.parse import quote
import re
import requests

from bonaid.config import settings

STOCKTWITS_URL = "https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json"
REDDIT_OAUTH_TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
REDDIT_OAUTH_SEARCH_URL = "https://oauth.reddit.com/r/{subreddit}/search"
SUBREDDITS = ["wallstreetbets", "stocks", "investing"]


def _build_user_agent() -> str:
    """Reddit's API rules require a descriptive User-Agent referencing a
    real account - a placeholder/fake username is more likely to be
    flagged/blocked. Uses REDDIT_USERNAME from settings if configured."""
    username = settings.reddit_username or "unknown-user"
    return f"bonaid-research-agent/0.2 by u/{username} (personal free/open-source trading research tool)"


USER_AGENT = _build_user_agent()

# Retail/social slang lexicon - intentionally different vocabulary from
# News Agent's (formal financial press) word list. Transparent and
# auditable, same philosophy as News Agent: a human can read this and know
# exactly why a post scored the way it did.
POSITIVE_WORDS = {
    "moon", "mooning", "rocket", "rockets", "tendies", "bullish", "calls",
    "squeeze", "breakout", "undervalued", "buy", "buying", "long", "gains",
    "printing", "yolo", "diamond", "hands", "strong", "beat", "beats",
    "rip", "pump", "pumping", "green", "up", "winning",
}
NEGATIVE_WORDS = {
    "bagholder", "bagholders", "bags", "puts", "bearish", "dump", "dumping",
    "rug", "crash", "crashing", "overvalued", "sell", "selling", "short",
    "shorting", "losses", "loss", "rip", "red", "down", "tank", "tanking",
    "scam", "fraud", "delisted", "bankruptcy", "drilled", "rekt",
}
# note: "rip" appears in both lists deliberately - "RIP my portfolio"
# (negative) vs "stock is ripping" (positive) are genuinely ambiguous out
# of context; treated as a wash (cancels out) rather than guessed wrong.


@dataclass
class SentimentAnalysis:
    ticker: str
    sentiment_label: str          # "Positive" | "Negative" | "Neutral" | "Mixed" | "No Data"
    sentiment_score: float        # -100 to +100, upvote-weighted
    mention_count: int
    reasons: list = field(default_factory=list)
    posts: list = field(default_factory=list)  # [{title, score, sentiment, permalink}, ...]
    llm_summary: str | None = None


def _get_oauth_token() -> str | None:
    """Client-credentials OAuth (app-only, no user login needed) - the
    correct free auth flow for read-only public data access. Returns None
    (not an exception) if credentials aren't configured or the token
    request fails, so callers can degrade gracefully."""
    if not settings.reddit_client_id or not settings.reddit_client_secret:
        print(
            "[sentiment_agent] Reddit not configured - set REDDIT_CLIENT_ID and "
            "REDDIT_CLIENT_SECRET in .env (free, see https://www.reddit.com/prefs/apps). "
            "Skipping Sentiment Agent for this run."
        )
        return None

    try:
        resp = requests.post(
            REDDIT_OAUTH_TOKEN_URL,
            auth=(settings.reddit_client_id, settings.reddit_client_secret),
            data={"grant_type": "client_credentials"},
            headers={"User-Agent": USER_AGENT},
            timeout=10,
        )
        if resp.status_code != 200:
            print(f"[sentiment_agent] Reddit OAuth token request failed: HTTP {resp.status_code} - {resp.text[:200]!r}")
            return None
        return resp.json().get("access_token")
    except Exception as e:
        print(f"[sentiment_agent] Reddit OAuth token request raised {type(e).__name__}: {e}")
        return None


def fetch_stocktwits_mentions(ticker: str, timeout: int = 10) -> list:
    """Returns a list of {title, score, permalink, subreddit, sentiment_tag}
    dicts from StockTwits' public symbol stream. sentiment_tag is
    'Bullish'/'Bearish'/None - StockTwits lets users self-tag posts, which
    is used directly when present instead of lexicon-guessing. No API key,
    no OAuth, no account registration needed. Returns an empty list (not an
    exception) on any failure."""
    url = STOCKTWITS_URL.format(ticker=quote(ticker))
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
        if resp.status_code != 200:
            print(
                f"[sentiment_agent] StockTwits fetch for '{ticker}' returned "
                f"HTTP {resp.status_code} (not 200). Response snippet: {resp.text[:200]!r}"
            )
            return []
        data = resp.json()
        posts = []
        for msg in data.get("messages", []):
            sentiment_entity = (msg.get("entities") or {}).get("sentiment")
            sentiment_tag = sentiment_entity.get("basic") if sentiment_entity else None
            posts.append({
                "title": msg.get("body", ""),
                "score": int(msg.get("likes", {}).get("total", 0)) if msg.get("likes") else 0,
                "permalink": f"https://stocktwits.com/symbol/{ticker}",
                "subreddit": "stocktwits",  # kept as the field name for compatibility with the rest of the module
                "sentiment_tag": sentiment_tag,
            })
        return posts
    except Exception as e:
        print(f"[sentiment_agent] StockTwits fetch for '{ticker}' raised {type(e).__name__}: {e}")
        return []


def fetch_mentions(ticker: str, limit_per_subreddit: int = 15, timeout: int = 10) -> list:
    """Top-level dispatcher: tries StockTwits first (no setup required).
    Only falls back to Reddit if StockTwits returns nothing AND Reddit
    credentials are configured - Reddit is no longer required for this
    agent to work out of the box."""
    posts = fetch_stocktwits_mentions(ticker, timeout=timeout)
    if posts:
        return posts

    if settings.reddit_client_id and settings.reddit_client_secret:
        return fetch_reddit_mentions(ticker, limit_per_subreddit=limit_per_subreddit, timeout=timeout)

    return []


def fetch_reddit_mentions(ticker: str, limit_per_subreddit: int = 15, timeout: int = 10) -> list:
    """Returns a list of {title, score, permalink, subreddit} dicts from
    Reddit's OAuth-authenticated search API. Returns an empty list (not an
    exception) on any fetch failure or missing credentials, so this is
    always safe to call unconditionally. Secondary source - see
    fetch_mentions() above, which is what the graph node actually calls."""
    token = _get_oauth_token()
    if token is None:
        return []

    headers = {"Authorization": f"Bearer {token}", "User-Agent": USER_AGENT}
    query = quote(f"{ticker}")
    posts = []
    for subreddit in SUBREDDITS:
        url = REDDIT_OAUTH_SEARCH_URL.format(subreddit=subreddit)
        try:
            resp = requests.get(
                url,
                params={"q": query, "restrict_sr": 1, "sort": "new", "limit": limit_per_subreddit, "t": "week"},
                headers=headers,
                timeout=timeout,
            )
            if resp.status_code != 200:
                print(
                    f"[sentiment_agent] r/{subreddit} fetch for '{ticker}' returned "
                    f"HTTP {resp.status_code} (not 200). Response snippet: {resp.text[:200]!r}"
                )
                continue
            data = resp.json()
            for child in data.get("data", {}).get("children", []):
                d = child.get("data", {})
                posts.append({
                    "title": d.get("title", ""),
                    "score": int(d.get("score", 0)),
                    "permalink": d.get("permalink", ""),
                    "subreddit": subreddit,
                    "sentiment_tag": None,
                })
        except Exception as e:
            print(f"[sentiment_agent] r/{subreddit} fetch for '{ticker}' raised {type(e).__name__}: {e}")
            continue  # one subreddit failing shouldn't kill the whole fetch
    return posts


def _score_post(post: dict) -> int:
    """+1 / -1 / 0 for a single post. Uses StockTwits' own Bullish/Bearish
    tag directly when present (a human already labeled it) - falls back to
    lexicon word-overlap scoring on the title/body text otherwise."""
    tag = post.get("sentiment_tag")
    if tag == "Bullish":
        return 1
    if tag == "Bearish":
        return -1

    words = set(re.findall(r"[a-z']+", post.get("title", "").lower()))
    pos = len(words & POSITIVE_WORDS)
    neg = len(words & NEGATIVE_WORDS)
    if pos > neg:
        return 1
    if neg > pos:
        return -1
    return 0


def analyze_sentiment(ticker: str, posts: list) -> SentimentAnalysis:
    """Core logic: pure function, no I/O - takes posts already fetched,
    easy to unit test with synthetic post lists."""
    if not posts:
        return SentimentAnalysis(
            ticker=ticker,
            sentiment_label="No Data",
            sentiment_score=0.0,
            mention_count=0,
            reasons=["No recent social mentions found (StockTwits/Reddit) - ticker may not be actively discussed, or fetch failed."],
        )

    scored = []
    weighted_total = 0.0
    weight_sum = 0.0
    for p in posts:
        s = _score_post(p)
        # Engagement weighting, capped so one viral post can't dominate: weight
        # ranges 1 (0 engagement) up to 5 (100+ likes/upvotes), log-ish scale.
        weight = 1.0 + min(max(p["score"], 0), 500) / 125.0  # caps around 5.0 at 500
        weighted_total += s * weight
        weight_sum += weight
        scored.append({**p, "sentiment": {1: "Positive", -1: "Negative", 0: "Neutral"}[s]})

    n = len(posts)
    sentiment_score = round((weighted_total / weight_sum) * 100, 1) if weight_sum > 0 else 0.0

    pos_count = sum(1 for p in scored if p["sentiment"] == "Positive")
    neg_count = sum(1 for p in scored if p["sentiment"] == "Negative")
    neu_count = n - pos_count - neg_count

    if sentiment_score >= 25:
        label = "Positive"
    elif sentiment_score <= -25:
        label = "Negative"
    elif pos_count > 0 and neg_count > 0 and abs(pos_count - neg_count) <= 1:
        label = "Mixed"
    else:
        label = "Neutral"

    source = scored[0]["subreddit"] if scored else "social"
    reasons = [
        f"{n} recent mentions analyzed (source: {source}): "
        f"{pos_count} positive, {neg_count} negative, {neu_count} neutral, engagement-weighted",
    ]
    top_post = max(scored, key=lambda p: p["score"], default=None)
    if top_post:
        reasons.append(f"Most-engaged mention ({top_post['score']}, {top_post['subreddit']}): \"{top_post['title']}\"")

    return SentimentAnalysis(
        ticker=ticker,
        sentiment_label=label,
        sentiment_score=sentiment_score,
        mention_count=n,
        reasons=reasons,
        posts=scored,
    )


def summarize_with_llm(analysis: SentimentAnalysis) -> str | None:
    """Optional: ask Ollama to narrate the social sentiment picture in plain
    English. Returns None if Ollama isn't reachable or there's no data."""
    from bonaid import llm
    if not llm.is_available() or analysis.mention_count == 0:
        return None

    post_lines = "\n".join(f"- {p['title']} ({p['sentiment']}, {p['score']} upvotes)" for p in analysis.posts[:10])
    prompt = (
        f"You are a social media sentiment summarizer. Given these recent Reddit post titles "
        f"mentioning {analysis.ticker} (aggregate sentiment: {analysis.sentiment_label}, "
        f"score {analysis.sentiment_score}), write ONE short plain-English paragraph (3-4 sentences "
        f"max) summarizing the retail investor mood. Be factual - only reference what is actually "
        f"in the post titles below, do not invent events, companies, or details not present. "
        f"Do not give financial advice.\n\n"
        f"Posts:\n{post_lines}"
    )
    try:
        return llm.generate(prompt).strip()
    except Exception:
        return None
