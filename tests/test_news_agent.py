"""
tests/test_news_agent.py
Tests the News Agent's scoring logic in isolation using synthetic headline
lists - no live network fetch needed, no Ollama dependency.
"""
from bonaid.agents.news_agent import analyze_news, _score_headline


def test_score_headline_positive():
    assert _score_headline("Company stock surges after strong earnings beat") == 1


def test_score_headline_negative():
    assert _score_headline("Company stock plunges after major lawsuit filed") == -1


def test_score_headline_neutral():
    assert _score_headline("Company to hold annual shareholder meeting") == 0


def test_analyze_news_no_headlines():
    result = analyze_news("TEST", [])
    assert result.sentiment_label == "No Data"
    assert result.sentiment_score == 0.0
    assert result.headline_count == 0


def test_analyze_news_mixed_headlines():
    headlines = [
        {"title": "Stock surges after earnings beat", "link": "", "published": "", "source": ""},
        {"title": "Company faces lawsuit over patent", "link": "", "published": "", "source": ""},
    ]
    result = analyze_news("TEST", headlines)
    assert result.headline_count == 2
    assert result.sentiment_label in {"Mixed", "Neutral", "Positive", "Negative"}
    assert len(result.headlines) == 2


def test_analyze_news_all_positive():
    headlines = [
        {"title": "Stock surges on record profit growth", "link": "", "published": "", "source": ""},
        {"title": "Analysts upgrade rating after strong beat", "link": "", "published": "", "source": ""},
        {"title": "Company announces breakthrough partnership", "link": "", "published": "", "source": ""},
    ]
    result = analyze_news("TEST", headlines)
    assert result.sentiment_label == "Positive"
    assert result.sentiment_score > 0
