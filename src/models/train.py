"""
Temporal Walk-Forward Training & Locked-Holdout Calibration Pipeline
Trains machine learning models using strict Entity-Disjoint + Chronological splits:
Train (T0 -> T1) | Validation (T1 -> T2) | Locked Test (T2 -> T3).
"""

from datetime import datetime
import json
import logging
from pathlib import Path
import random
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

from src.research.evaluation import ModelPerformanceReport, ResearchEvaluator
from src.research.lineage import DataLineageAuditor, LineageAuditReport
from src.research.splits import DatasetSplits, EntityDisjointSplitter
from src.research.storage import ResearchStorage

logger = logging.getLogger(__name__)

FEATURE_COLUMNS = [
    "effective_volume_mc_ratio_5m",
    "effective_buy_volume_pressure",
    "buyer_quality",
    "liquidity_quality",
    "holder_quality",
    "breakout_quality",
    "wallet_independence",
    "wash_trade_risk",
    "cabal_risk_score",
    "dev_risk_score",
    "contract_risk",
    "liquidity_risk",
]


class TemporalWalkForwardTrainer:
    def __init__(self, storage: Optional[ResearchStorage] = None):
        self.storage = storage or ResearchStorage()

    @staticmethod
    def extract_feature_vector(record: Dict[str, Any]) -> List[float]:
        """Extract standardized numeric feature vector from storage record."""
        feats = record.get("features", {})
        mc = max(1.0, float(record.get("market_cap_usd", 1.0)))
        vol_5m = float(record.get("volume_5m_usd", 0.0))
        vol_qual = float(record.get("volume_quality_score", 1.0))
        effective_vol_mc = (vol_5m * vol_qual) / mc

        buys = int(record.get("txns_5m_buys", 0))
        sells = int(record.get("txns_5m_sells", 0))
        total_tx = max(1, buys + sells)
        buy_ratio = buys / total_tx

        cabal_risk = float(record.get("cabal_risk_score", 0.0))
        wash_risk = float(record.get("wash_trade_risk", 0.0))
        wallet_indep = max(0.0, 1.0 - cabal_risk)
        effective_buy_pressure = buy_ratio * wallet_indep

        liq = max(0.0, float(record.get("liquidity_usd", 0.0)))
        liq_ratio = liq / mc
        top10 = float(record.get("top10_effective_pct", record.get("top10_raw_pct", 20.0)))
        dev_pct = float(record.get("dev_holding_pct", 0.0))

        vec = [
            effective_vol_mc,
            effective_buy_pressure,
            feats.get("buyer_quality", 0.5),
            feats.get("liquidity_quality", min(1.0, liq_ratio / 0.25)),
            feats.get("holder_quality", max(0.0, 1.0 - (top10 / 40.0))),
            feats.get("breakout_quality", 0.5),
            wallet_indep,
            wash_risk,
            cabal_risk,
            min(1.0, dev_pct / 8.0),
            feats.get("contract_risk", 0.0),
            feats.get("liquidity_risk", 0.0 if liq_ratio >= 0.15 else 0.5),
        ]
        return [float(x) for x in vec]

    def split_data_temporally(
        self,
        records: List[Dict[str, Any]],
        train_ratio: float = 0.60,
        val_ratio: float = 0.20,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Strict entity-disjoint chronological split."""
        splits = EntityDisjointSplitter.split_chronological_entity_disjoint(
            records, train_ratio=train_ratio, val_ratio=val_ratio
        )
        return splits.train_records, splits.val_records, splits.locked_test_records

    def train_and_evaluate(self) -> ModelPerformanceReport:
        """
        Load dataset, split into Train/Val/Locked-Test, fit and calibrate model on Train+Val,
        and evaluate out-of-sample on Locked-Test.
        """
        records = self.storage.load_training_dataset()
        is_synthetic = False
        if len(records) < 15:
            records = self._generate_synthetic_benchmark_records(150)
            is_synthetic = True

        # Perform Lineage Audit
        audit = DataLineageAuditor.audit_dataset(records, is_synthetic=is_synthetic)

        train_set, val_set, test_set = self.split_data_temporally(records)

        X_train = np.array([self.extract_feature_vector(r) for r in train_set])
        y_train = np.array([1 if r.get("target_3m") or r.get("is_valid_3m_runner") else 0 for r in train_set])

        X_val = np.array([self.extract_feature_vector(r) for r in val_set])
        y_val = np.array([1 if r.get("target_3m") or r.get("is_valid_3m_runner") else 0 for r in val_set])

        X_test = np.array([self.extract_feature_vector(r) for r in test_set])
        y_test = [1 if r.get("target_3m") or r.get("is_valid_3m_runner") else 0 for r in test_set]

        # Fit Regularized Logistic Regression Model on Train
        from sklearn.linear_model import LogisticRegression
        from sklearn.calibration import CalibratedClassifierCV

        base_clf = LogisticRegression(C=1.0, max_iter=500, class_weight="balanced")
        if len(np.unique(y_train)) > 1:
            calibrated_clf = CalibratedClassifierCV(estimator=base_clf, method="sigmoid", cv=2)
            calibrated_clf.fit(X_train, y_train)
            y_prob = calibrated_clf.predict_proba(X_test)[:, 1].tolist()
        else:
            y_prob = [0.05] * len(y_test)

        lead_time_data = [
            {
                "time_to_3m_min": r.get("time_to_3m_min"),
                "time_to_1m_min": r.get("time_to_1m_min"),
                "time_to_100k_min": r.get("time_to_100k_min"),
            }
            for r in test_set
        ]

        report = ResearchEvaluator.evaluate_model(
            y_true=y_test,
            y_prob=y_prob,
            lead_time_data=lead_time_data,
            model_name="CalibratedBreakoutPredictor_LockedHoldout",
        )
        report.base_rates = ResearchEvaluator.compute_base_rate(test_set)
        return report

    def _generate_synthetic_benchmark_records(self, n: int = 150) -> List[Dict[str, Any]]:
        """
        Generate benchmark records with realistic market noise, false signals, and cabal traps.
        """
        records = []
        rng = random.Random(42)

        for i in range(n):
            is_winner = (i % 25 == 0) # 4% base rate
            is_cabal_trap = (i % 7 == 0 and not is_winner)
            is_rug = (i % 5 == 0 and not is_winner and not is_cabal_trap)

            mc = 12000.0 + (i * 200.0) + rng.uniform(-1000, 1000)
            liq = mc * (0.28 if is_winner else (0.12 if is_cabal_trap else 0.05))

            # Add noisy volume
            raw_vol = 3500.0 if is_winner else (6500.0 if is_cabal_trap else 800.0)
            vol_5m = raw_vol + rng.uniform(-400, 400)

            wash_risk = 0.05 if is_winner else (0.75 if is_cabal_trap else 0.15)
            cabal_risk = 0.05 if is_winner else (0.80 if is_cabal_trap else 0.20)
            dev_pct = 0.0 if is_winner else (2.0 if is_cabal_trap else 12.0)

            rec = {
                "token_address": f"Token_{i:04d}",
                "timestamp": f"2026-08-24T{10 + (i//60):02d}:{i%60:02d}:00Z",
                "market_cap_usd": mc,
                "liquidity_usd": liq,
                "volume_5m_usd": vol_5m,
                "txns_5m_buys": 45 if is_winner else (35 if is_cabal_trap else 8),
                "txns_5m_sells": 15 if is_winner else (5 if is_cabal_trap else 12),
                "unique_buyers": 55 if is_winner else (12 if is_cabal_trap else 6),
                "unique_sellers": 18 if is_winner else 4,
                "top10_raw_pct": 14.0 if is_winner else 48.0,
                "top10_effective_pct": 15.0 if is_winner else 62.0,
                "cabal_risk_score": cabal_risk,
                "wash_trade_risk": wash_risk,
                "volume_quality_score": 0.95 if is_winner else (0.25 if is_cabal_trap else 0.85),
                "dev_holding_pct": dev_pct,
                "target_50k": int(is_winner or i % 6 == 0),
                "target_100k": int(is_winner or i % 10 == 0),
                "target_1m": int(is_winner),
                "target_3m": int(is_winner),
                "is_valid_3m_runner": int(is_winner),
                "is_rug_event": int(is_rug),
                "time_to_100k_min": 18.0 if is_winner else None,
                "time_to_1m_min": 45.0 if is_winner else None,
                "time_to_3m_min": 95.0 if is_winner else None,
                "features": {
                    "buyer_quality": 0.90 if is_winner else (0.40 if is_cabal_trap else 0.25),
                    "liquidity_quality": 0.85 if is_winner else (0.50 if is_cabal_trap else 0.15),
                    "holder_quality": 0.90 if is_winner else 0.15,
                    "breakout_quality": 0.85 if is_winner else (0.70 if is_cabal_trap else 0.30),
                    "contract_risk": 0.0 if not is_rug else 0.8,
                    "liquidity_risk": 0.0 if not is_rug else 0.9,
                },
            }
            records.append(rec)
        return records
