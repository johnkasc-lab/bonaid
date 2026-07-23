"""
tests/test_ml_outcome_model.py
Tests bonaid/ml/outcome_model.py's pure functions - feature extraction,
the honesty guardrails (refuses to train on too little/single-class data),
and confirms the model can actually learn a real pattern from separable
synthetic data. No DB needed - gather_training_data_from_db/
train_and_store_model/load_latest_model are thin DB plumbing tested
separately (or implicitly via the CLI), not here.
"""
import random
from bonaid.ml.outcome_model import (
    extract_features, train_model, predict, feature_importance,
    MIN_TRADES_FOR_ML, FEATURE_NAMES,
)


def _decision(confidence=50.0, long_count=5, news_score=0.0, social_score=0.0, overridden=False):
    return {
        "confidence": confidence,
        "signal_breakdown": [{"signal": "LONG"}] * long_count + [{"signal": "FLAT"}] * (11 - long_count),
        "news_assessment": {"sentiment_score": news_score},
        "sentiment_assessment": {"sentiment_score": social_score},
        "supervisor_decision": {"overridden": overridden},
    }


def test_extract_features_normalizes_correctly():
    d = _decision(confidence=80.0, long_count=8, news_score=50.0, social_score=-20.0, overridden=True)
    features = extract_features(d)
    assert features["confidence"] == 0.8
    assert features["technical_long_ratio"] == 8 / 11
    assert features["news_score"] == 0.5
    assert features["social_score"] == -0.2
    assert features["overridden"] == 1.0


def test_extract_features_handles_missing_data_gracefully():
    # Empty/missing decision fields shouldn't crash - should use sane defaults.
    features = extract_features({})
    assert features["confidence"] == 0.0
    assert features["technical_long_ratio"] == 0.5  # neutral prior
    assert features["overridden"] == 0.0


def test_train_model_refuses_below_minimum_trades():
    trades = [{"realized_pnl": 100, **_decision()} for _ in range(MIN_TRADES_FOR_ML - 1)]
    assert train_model(trades) is None


def test_train_model_refuses_single_class_data():
    # All wins - no losses to learn a boundary against.
    trades = [{"realized_pnl": 100, **_decision()} for _ in range(MIN_TRADES_FOR_ML + 5)]
    assert train_model(trades) is None


def test_predict_unavailable_without_a_model():
    result = predict(_decision(), None)
    assert result.available is False
    assert "Not enough" in result.reason


def test_model_learns_a_real_separable_pattern():
    random.seed(7)
    trades = []
    for i in range(50):
        good = i % 2 == 0
        conf = random.uniform(70, 90) if good else random.uniform(10, 30)
        longs = random.randint(8, 11) if good else random.randint(0, 3)
        pnl = random.uniform(100, 500) if good else random.uniform(-500, -100)
        trades.append({"realized_pnl": pnl, **_decision(confidence=conf, long_count=longs)})

    model = train_model(trades)
    assert model is not None
    assert model.train_accuracy > 0.85  # should learn the obvious pattern well

    high_quality = predict(_decision(confidence=85, long_count=10), model)
    low_quality = predict(_decision(confidence=15, long_count=1), model)
    assert high_quality.win_probability > 0.7
    assert low_quality.win_probability < 0.3


def test_feature_importance_returns_all_features_sorted():
    random.seed(1)
    trades = []
    for i in range(30):
        good = i % 2 == 0
        pnl = 100 if good else -100
        conf = 80 if good else 20
        trades.append({"realized_pnl": pnl, **_decision(confidence=conf)})
    model = train_model(trades)
    importance = feature_importance(model)
    assert len(importance) == len(FEATURE_NAMES)
    weights = [abs(w) for _, w in importance]
    assert weights == sorted(weights, reverse=True)  # confirms sorted by magnitude
