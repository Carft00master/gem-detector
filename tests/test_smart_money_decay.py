"""
Tests for Smart Wallet Skill Decay and Regime Conditioning.
"""

from datetime import datetime, timedelta, timezone
import pytest
from src.learning.smart_money.skill_decay import WalletSkillDecayCalculator


def test_wallet_skill_decay_and_trend_classification():
    """Verify 7D, 30D, 90D skill calculation and decay trend classification."""
    ref_time = datetime(2026, 8, 26, 12, 0, 0, tzinfo=timezone.utc)
    ref_iso = ref_time.isoformat()

    # Create wallet with high historical win rate (60d ago) but low recent win rate (last 7d)
    txs = []
    # 20 old winning trades (45 days ago)
    t_old = (ref_time - timedelta(days=45)).isoformat()
    for _ in range(20):
        txs.append({"timestamp": t_old, "entry_timestamp": t_old, "target_100k": True, "realized_return": 150.0, "market_regime": "NORMAL"})

    # 10 recent losing trades (last 5 days)
    t_recent = (ref_time - timedelta(days=5)).isoformat()
    for _ in range(10):
        txs.append({"timestamp": t_recent, "entry_timestamp": t_recent, "target_100k": False, "realized_return": -35.0, "market_regime": "COLD"})

    decay = WalletSkillDecayCalculator.evaluate_wallet_decay("DecayingWallet", txs, reference_timestamp=ref_iso)

    assert decay.skill_all_time_win_rate > 60.0   # Lifetime win rate ~66.7%
    assert decay.skill_7d_win_rate == 0.0          # Recent 7d win rate 0.0%
    assert decay.skill_trend == "DECLINING"
    assert decay.is_actively_decaying is True

    # Check regime breakdown
    assert "NORMAL" in decay.regime_profiles
    assert "COLD" in decay.regime_profiles
    assert decay.regime_profiles["NORMAL"].win_rate_pct == 100.0
    assert decay.regime_profiles["COLD"].win_rate_pct == 0.0
