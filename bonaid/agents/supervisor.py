"""
bonaid/agents/supervisor.py
Reconciles Technical, News, Sentiment, and (now) Macro into one final decision.

Reconciliation rules (deliberately simple and legible - a black-box scoring
formula here would be worse than no supervisor at all, since the whole
point is being able to explain WHY the final call differs from Technical
alone):

  1. Technical's action is the baseline - News/Sentiment/Macro can only
     adjust it, never invent a BUY on their own. A confidence-scored
     technical signal is still the only thing that can initiate a position.

  2. DOWNGRADE (caution is asymmetric - easier to trigger than upgrade):
     Technical says BUY, but News is Negative, OR Sentiment is Negative,
     OR the Macro regime is Tightening -> downgrade to WATCH. Any ONE
     bearish channel is enough to justify pausing before entry - the cost
     of a false pause is small, the cost of buying into a real negative
     catalyst (news, sentiment, OR a tightening rate environment) is not.
     Macro is included here deliberately even though it's market-wide, not
     ticker-specific - a rising-rate environment is a real headwind for
     ANY new long entry, so it earns the same single-channel veto weight
     as a bearish news/sentiment reading on this specific ticker.

  3. UPGRADE (requires broader confirmation than downgrade, and Macro does
     NOT count toward this bar):
     Technical says HOLD, but BOTH News AND Sentiment are Positive ->
     upgrade to WATCH (never all the way to BUY - see rule 1). Macro is
     deliberately excluded from the upgrade trigger - "the Fed isn't
     raising rates" is not evidence FOR any specific ticker, it's just the
     absence of one specific headwind, so it shouldn't help push toward
     more attention the way two ticker-specific bullish signals agreeing
     would.

  4. Everything else (including "Mixed"/"No Data" on News/Sentiment, or
     "Neutral"/"Easing"/"No Data" Macro) -> Technical's action passes
     through unchanged, with all channels shown as supporting context.

Uses each agent's actual vocabulary (News/Sentiment sentiment_label:
"Positive" | "Negative" | "Neutral" | "Mixed" | "No Data"; Macro regime:
"Tightening" | "Easing" | "Neutral" | "No Data") so this stays in sync with
bonaid/agents/news_agent.py, sentiment_agent.py, and macro_agent.py.
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
    macro_regime: str
    reasoning: list = field(default_factory=list)


def reconcile(ticker: str, technical: dict, news: dict, sentiment: dict, macro: dict | None = None) -> SupervisorDecision:
    technical_action = technical["action"]
    technical_confidence = technical["confidence"]
    news_sentiment = news["sentiment_label"]
    news_score = news["sentiment_score"]
    social_sentiment = sentiment["sentiment_label"]
    social_score = sentiment["sentiment_score"]
    macro_regime = (macro or {}).get("regime", "No Data")

    action = technical_action
    confidence = technical_confidence
    overridden = False
    reasoning = []

    bearish_channels = [name for name, label in
                         [("News", news_sentiment), ("Sentiment", social_sentiment)]
                         if label == "Negative"]
    if macro_regime == "Tightening":
        bearish_channels.append("Macro")
    bullish_both = news_sentiment == "Positive" and social_sentiment == "Positive"  # Macro deliberately excluded - see rule 3

    if technical_action == "BUY" and bearish_channels:
        action = "WATCH"
        overridden = True
        confidence = round(technical_confidence * 0.7, 1)  # meaningfully less confident given the conflict
        channel_desc = " and ".join(bearish_channels)
        macro_note = f", Macro is {macro_regime}" if "Macro" in bearish_channels else ""
        reasoning.append(
            f"Technical signaled BUY ({technical_confidence}% confidence), but {channel_desc} "
            f"raised caution (News score {news_score}, Sentiment score {social_score}{macro_note}) - "
            f"downgraded to WATCH pending confirmation. Risk Agent will not size a position for WATCH."
        )
    elif technical_action == "HOLD" and bullish_both:
        action = "WATCH"
        overridden = True
        reasoning.append(
            f"Technical signaled HOLD ({technical_confidence}% confidence), and BOTH News and "
            f"Sentiment are Positive (News score {news_score}, Sentiment score {social_score}) - "
            f"upgraded to WATCH for closer monitoring. Not upgraded to BUY - sentiment alone does "
            f"not create a technical entry signal. (Macro regime '{macro_regime}' noted but does not "
            f"count toward this upgrade - market-wide conditions aren't ticker-specific evidence.)"
        )
    else:
        reasoning.append(
            f"Technical signal ({technical_action}, {technical_confidence}% confidence) unchanged - "
            f"News ({news_sentiment}, {news_score}), Sentiment ({social_sentiment}, {social_score}), "
            f"and Macro ({macro_regime}) did not meet an override condition."
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
        macro_regime=macro_regime,
        reasoning=reasoning,
    )
