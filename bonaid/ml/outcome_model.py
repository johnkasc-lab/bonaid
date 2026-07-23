"""
bonaid/ml/outcome_model.py
The self-learning piece: predicts win probability for a fresh decision,
trained on bonaid's OWN accumulated track record (closed paper trades and
the decisions that opened them). Improves as more trades close - literally
learns from the system's own history, not a pre-trained external model.

Deliberately plain logistic regression via numpy gradient descent, not
scikit-learn/xgboost:
  1. No new heavy dependency - numpy is already required everywhere else,
     avoids adding a ~30MB+ library on a machine with known RAM/disk
     constraints (see earlier session notes on the 8GB Windows machine).
  2. The learned weights are directly human-readable - "confidence
     mattered this much, technical-long-ratio mattered this much" - a
     human can look at bonaid_ml.py's output and understand exactly why
     the model predicts what it predicts. Consistent with the "legible
     over black box" rule already followed by Supervisor and Macro Agent.

INFORMATIONAL ONLY, same precedent as Macro before it was wired in: with
essentially zero real closed trades today, any prediction would be
statistically meaningless. This is why MIN_TRADES_FOR_ML exists and is
enforced strictly - "not enough data yet" is the correct, honest answer
until there's a real track record, not a number dressed up as one.
"""
from dataclasses import dataclass, field
import numpy as np

MIN_TRADES_FOR_ML = 20  # below this, a trained model is fitting noise, not signal - training refuses outright

FEATURE_NAMES = [
    "confidence",              # Supervisor's confidence, 0-1 (normalized from 0-100)
    "technical_long_ratio",    # fraction of the 11 strategies signaling long at decision time
    "news_score",              # News Agent's sentiment_score, normalized to -1..1
    "social_score",            # Sentiment Agent's sentiment_score, normalized to -1..1
    "overridden",              # 1.0 if Supervisor overrode Technical's raw action, else 0.0
]


@dataclass
class TrainedModel:
    weights: list       # one per FEATURE_NAMES entry
    bias: float
    train_accuracy: float
    trade_count: int
    feature_names: list = field(default_factory=lambda: list(FEATURE_NAMES))


@dataclass
class PredictionResult:
    available: bool             # False if no model trained yet / not enough data
    win_probability: float | None = None
    model_trade_count: int | None = None
    reason: str | None = None   # explains why unavailable, if it is


def extract_features(decision: dict) -> dict:
    """decision: an AgentDecision-shaped dict with signal_breakdown,
    news_assessment, sentiment_assessment, supervisor_decision. Pure
    function - no DB access, easy to test with hand-built fixtures."""
    confidence = (decision.get("confidence") or 0.0) / 100.0

    breakdown = decision.get("signal_breakdown") or []
    valid = [b for b in breakdown if b.get("signal") in ("LONG", "FLAT")]
    long_count = sum(1 for b in valid if b.get("signal") == "LONG")
    technical_long_ratio = (long_count / len(valid)) if valid else 0.5  # 0.5 = neutral prior when unknown

    news = decision.get("news_assessment") or {}
    news_score = (news.get("sentiment_score") or 0.0) / 100.0

    sentiment = decision.get("sentiment_assessment") or {}
    social_score = (sentiment.get("sentiment_score") or 0.0) / 100.0

    supervisor = decision.get("supervisor_decision") or {}
    overridden = 1.0 if supervisor.get("overridden") else 0.0

    return {
        "confidence": confidence,
        "technical_long_ratio": technical_long_ratio,
        "news_score": news_score,
        "social_score": social_score,
        "overridden": overridden,
    }


def _to_vector(features: dict) -> list:
    return [features[name] for name in FEATURE_NAMES]


def _sigmoid(z):
    return 1.0 / (1.0 + np.exp(-np.clip(z, -500, 500)))  # clip avoids overflow warnings on extreme inputs


def train_logistic_regression(X: list, y: list, lr: float = 0.1, epochs: int = 1000) -> tuple:
    """Plain batch-gradient-descent logistic regression. Returns
    (weights: list, bias: float, train_accuracy: float). No external ML
    library - see module docstring for why."""
    X_arr = np.array(X, dtype=float)
    y_arr = np.array(y, dtype=float)
    n_samples, n_features = X_arr.shape

    weights = np.zeros(n_features)
    bias = 0.0

    for _ in range(epochs):
        z = X_arr @ weights + bias
        predictions = _sigmoid(z)
        error = predictions - y_arr
        grad_w = (X_arr.T @ error) / n_samples
        grad_b = np.mean(error)
        weights -= lr * grad_w
        bias -= lr * grad_b

    final_predictions = _sigmoid(X_arr @ weights + bias)
    accuracy = float(np.mean((final_predictions >= 0.5).astype(float) == y_arr))
    return weights.tolist(), float(bias), round(accuracy, 3)


def build_training_data(trades_with_decisions: list) -> tuple:
    """trades_with_decisions: [{"realized_pnl": float, "signal_breakdown":,
    "news_assessment":, "sentiment_assessment":, "supervisor_decision":,
    "confidence": float}, ...]. Returns (X, y) ready for training."""
    X, y = [], []
    for t in trades_with_decisions:
        features = extract_features(t)
        X.append(_to_vector(features))
        y.append(1.0 if t["realized_pnl"] > 0 else 0.0)
    return X, y


def train_model(trades_with_decisions: list) -> TrainedModel | None:
    """Returns None (not an exception) if there isn't enough data yet -
    the honest answer, not a model trained on noise."""
    if len(trades_with_decisions) < MIN_TRADES_FOR_ML:
        return None

    X, y = build_training_data(trades_with_decisions)
    if len(set(y)) < 2:
        # All wins or all losses so far - logistic regression can't learn
        # a meaningful boundary from a single class. Also an honest "not
        # ready", not a crash.
        return None

    weights, bias, accuracy = train_logistic_regression(X, y)
    return TrainedModel(weights=weights, bias=bias, train_accuracy=accuracy, trade_count=len(trades_with_decisions))


def predict(decision: dict, model: TrainedModel | None) -> PredictionResult:
    """decision: same shape as one element of trades_with_decisions above
    (minus realized_pnl, since we're predicting a NEW decision, not a
    closed one)."""
    if model is None:
        return PredictionResult(
            available=False,
            reason=f"Not enough closed trades yet to train a model (need at least {MIN_TRADES_FOR_ML}).",
        )

    features = extract_features(decision)
    vector = np.array(_to_vector(features))
    z = float(np.dot(vector, model.weights) + model.bias)
    probability = round(float(_sigmoid(z)), 3)

    return PredictionResult(
        available=True,
        win_probability=probability,
        model_trade_count=model.trade_count,
    )


def feature_importance(model: TrainedModel) -> list:
    """Returns [(feature_name, weight), ...] sorted by absolute weight -
    the human-readable payoff of using plain logistic regression instead
    of a black-box model. A positive weight means higher values of that
    feature push toward predicting a win; negative pushes toward a loss."""
    pairs = list(zip(model.feature_names, model.weights))
    return sorted(pairs, key=lambda p: abs(p[1]), reverse=True)


# --- DB-backed layer: gathers real closed trades + their linked decisions,
# trains, persists, and loads the latest model. The pure functions above
# never touch the DB - these are the thin plumbing around them. ---

def gather_training_data_from_db() -> list:
    """Pulls every CLOSED PaperPosition that has a linked AgentDecision
    (source_decision_id) and assembles training-ready dicts. Trades opened
    before source_decision_id existed are silently excluded - they simply
    can't be attributed, same as the analytics attribution feature."""
    from bonaid.db import get_session
    from bonaid.models import PaperPosition, AgentDecision

    with get_session() as s:
        closed = s.query(PaperPosition).filter(
            PaperPosition.status == "CLOSED",
            PaperPosition.source_decision_id.isnot(None),
        ).all()
        decision_ids = [p.source_decision_id for p in closed]
        decisions_by_id = {}
        if decision_ids:
            for d in s.query(AgentDecision).filter(AgentDecision.id.in_(decision_ids)).all():
                decisions_by_id[d.id] = d

        trades = []
        for p in closed:
            d = decisions_by_id.get(p.source_decision_id)
            if d is None:
                continue
            trades.append({
                "realized_pnl": p.realized_pnl,
                "confidence": d.confidence,
                "signal_breakdown": d.signal_breakdown,
                "news_assessment": d.news_assessment,
                "sentiment_assessment": d.sentiment_assessment,
                "supervisor_decision": d.supervisor_decision,
            })
        return trades


def train_and_store_model() -> TrainedModel | None:
    """Gathers real data, trains, and persists a new MLModel row. Returns
    None (not an exception) if there isn't enough data - the caller (CLI)
    is responsible for displaying that honestly."""
    from bonaid.db import get_session
    from bonaid.models import MLModel

    trades = gather_training_data_from_db()
    model = train_model(trades)
    if model is None:
        return None

    with get_session() as s:
        s.add(MLModel(
            feature_names=model.feature_names,
            weights=model.weights,
            bias=model.bias,
            train_accuracy=model.train_accuracy,
            trade_count=model.trade_count,
        ))
    return model


def load_latest_model() -> TrainedModel | None:
    """Loads the most recently trained model from the DB, or None if
    none has been trained yet."""
    from bonaid.db import get_session
    from bonaid.models import MLModel

    with get_session() as s:
        row = s.query(MLModel).order_by(MLModel.trained_at.desc()).first()
        if row is None:
            return None
        return TrainedModel(
            weights=row.weights, bias=row.bias, train_accuracy=row.train_accuracy,
            trade_count=row.trade_count, feature_names=row.feature_names,
        )
