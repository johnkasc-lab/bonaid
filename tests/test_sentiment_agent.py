"""
tests/test_sentiment_agent.py
Tests the Sentiment Agent's engagement-weighted scorer (lexicon + StockTwits
native tags) and graceful degradation, without needing live network access.
"""
from bonaid.agents.sentiment_agent import analyze_sentiment, fetch_mentions, _score_post


def test_score_post_positive_lexicon():
    post = {"title": "This stock is mooning, calls printing", "sentiment_tag": None}
    assert _score_post(post) == 1


def test_score_post_negative_lexicon():
    post = {"title": "Bagholder here, should have bought puts", "sentiment_tag": None}
    assert _score_post(post) == -1


def test_score_post_neutral_lexicon():
    post = {"title": "What time does the market open today", "sentiment_tag": None}
    assert _score_post(post) == 0


def test_stocktwits_native_tag_used_directly_over_lexicon():
    # StockTwits' own Bullish/Bearish tag should be trusted directly, even
    # if the text itself reads ambiguous/neutral to the lexicon.
    bullish_post = {"title": "just a regular update", "sentiment_tag": "Bullish"}
    assert _score_post(bullish_post) == 1

    bearish_post = {"title": "just a regular update", "sentiment_tag": "Bearish"}
    assert _score_post(bearish_post) == -1


def test_engagement_weighting_favors_high_engagement_posts():
    posts = [
        {"title": "This is mooning, huge calls", "score": 500, "permalink": "", "subreddit": "stocktwits", "sentiment_tag": None},
        {"title": "Bagholder, bought puts too late", "score": 2, "permalink": "", "subreddit": "stocktwits", "sentiment_tag": None},
    ]
    result = analyze_sentiment("TEST", posts)
    # Raw count is 1 positive vs 1 negative, but the positive post has vastly
    # more engagement - aggregate should reflect that, not a naive 50/50 split.
    assert result.sentiment_score > 0
    assert result.sentiment_label == "Positive"


def test_analyze_sentiment_handles_no_posts_gracefully():
    result = analyze_sentiment("TEST", [])
    assert result.sentiment_label == "No Data"
    assert result.sentiment_score == 0.0
    assert result.mention_count == 0


def test_fetch_mentions_never_raises():
    # Should degrade to an empty list, not throw, on network failure -
    # this is what makes it safe to call unconditionally from the graph node.
    result = fetch_mentions("THISISNOTAREALTICKERXYZ123")
    assert isinstance(result, list)


def test_most_engaged_post_surfaced_in_reasons():
    posts = [
        {"title": "Small mention of the stock", "score": 3, "permalink": "", "subreddit": "stocktwits", "sentiment_tag": None},
        {"title": "This is going to the moon, huge rocket", "score": 999, "permalink": "", "subreddit": "stocktwits", "sentiment_tag": None},
    ]
    result = analyze_sentiment("TEST", posts)
    assert any("999" in r for r in result.reasons)
