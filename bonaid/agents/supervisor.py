"""
bonaid/agents/supervisor.py
Reconciles Technical, News, and (now) Sentiment into one final decision.

Reconciliation rules (deliberately simple and legible - a black-box scoring
formula here would be worse than no supervisor at all, since the whole
point is being able to explain WHY the final call differs from Technical
alone):

  1. Technical's action is the baseline - News/Sentiment can only adjust
     it, never invent a BUY on their own. A confidence-scored technical
     signal is still the only thing that can initiate a position.

  2. DOWNGRADE (caution is asymmetric - easier to trigger than upgrade):
     Technical says BUY, but EITHER News OR Sentiment is Negative ->
     downgrade to WATCH. Only one bearish channel needs to confirm to
     justify pausing before entry - the cost of a false pause is small,
     the cost of buying into a real negative catalyst is not.

  3. UPGRADE (requires broader confirmation than downgrade):
     Technical says HOLD, but BOTH News AND Sentiment are Positive ->
     upgrade to WATCH (never all the way to BUY - see rule 1). Requiring
     agreement from both channels (formal press AND retail sentiment)
     before bothering to escalate attention is intentionally more
     conservative than the downgrade path above.

  4. Everything else (including "Mixed"/"No Data" on either channel) ->
     Technical's action passes through unchanged, with News/Sentiment
     shown as supporting context.

Uses each agent's actual sentiment vocabulary (sentiment_label:
"Positive" | "Negative" | "Neutral" | "Mixed" | "No Data") so this stays in
sync with bonaid/agents/news_agent.py and bonaid/agents/sentiment_agent.py.
"""
from dataclasses import dataclass, field


@dataclass
class SupervisorDecision:
    ticker: str
    action: str                  # final action - what Risk Agent sizes off
    confidence: float
    overridden: bool             # True if this differs from Technical's raw action
    technical_action: str
    technical_confidence: float
    news_sentiment: str
    social_sentiment: str
    reasoning: list = field(default_factory=list)


def reconcile(ticker: str, technical: dict, news: dict, sentiment: dict) -> SupervisorDecision:
    technical_action = technical["action"]
    technical_confidence = technical["confidence"]
    news_sentiment = news["sentiment_label"]
    news_score = news["sentiment_score"]
    social_sentiment = sentiment["sentiment_label"]
    social_score = sentiment["sentiment_score"]

    action = technical_action
    confidence = technical_confidence
    overridden = False
    reasoning = []

    bearish_channels = [name for name, label in
                         [("News", news_sentiment), ("Sentiment", social_sentiment)]
                         if label == "Negative"]
    bullish_both = news_sentiment == "Positive" and social_sentiment == "Positive"

    if technical_action == "BUY" and bearish_channels:
        action = "WATCH"
        overridden = True
        confidence = round(technical_confidence * 0.7, 1)  # meaningfully less confident given the conflict
        channel_desc = " and ".join(bearish_channels)
        reasoning.append(
            f"Technical signaled BUY ({technical_confidence}% confidence), but {channel_desc} "
            f"sentiment is Negative (News score {news_score}, Sentiment score {social_score}) - "
            f"downgraded to WATCH pending confirmation. Risk Agent will not size a position for WATCH."
        )
    elif technical_action == "HOLD" and bullish_both:
        action = "WATCH"
        overridden = True
        reasoning.append(
            f"Technical signaled HOLD ({technical_confidence}% confidence), and BOTH News and "
            f"Sentiment are Positive (News score {news_score}, Sentiment score {social_score}) - "
            f"upgraded to WATCH for closer monitoring. Not upgraded to BUY - sentiment alone does "
            f"not create a technical entry signal."
        )
    else:
        reasoning.append(
            f"Technical signal ({technical_action}, {technical_confidence}% confidence) unchanged - "
            f"News ({news_sentiment}, {news_score}) and Sentiment ({social_sentiment}, {social_score}) "
            f"did not meet an override condition."
        )

    return SupervisorDecision(
        ticker=ticker,
        action=action,
        confidence=confidence,
        overridden=overridden,
        technical_action=technical_action,
        technical_confidence=technical_confidence,
        news_sentiment=news_sentiment,
        social_sentiment=social_sentiment,
        reasoning=reasoning,
    )
