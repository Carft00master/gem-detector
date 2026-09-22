"""
Tests for LearningDatasetBuilder and associated schemas (v1.0.0 Frozen).
"""

import unittest
from src.learning.dataset_builder import (
    EntryDatasetRow,
    ExitDatasetRow,
    LearningDataset,
    LearningDatasetBuilder,
    MIN_ENTRY_OBSERVATIONS,
    MIN_EXIT_OBSERVATIONS,
    MIN_SELECTION_OBSERVATIONS,
    SelectionDatasetRow,
)


class TestLearningDatasetBuilder(unittest.TestCase):
    def test_selection_dataset_row_creation(self):
        row = SelectionDatasetRow(
            token_address="Token123456789",
            symbol="TEST",
            chain="solana",
            venue="pumpfun",
            discovery_timestamp="2026-08-25T12:00:00Z",
            market_cap_usd=15000.0,
            liquidity_usd=4000.0,
            token_age_minutes=5.0,
            volume_5m_usd=2500.0,
            volume_1h_usd=8000.0,
            effective_vol_mc_ratio=0.16,
            effective_buy_pressure=2.5,
            buyer_quality=0.85,
            liquidity_quality=0.90,
            holder_quality=0.80,
            breakout_quality=0.75,
            wallet_independence=0.95,
            wash_trade_risk=0.05,
            cabal_risk_score=0.10,
            dev_risk_score=0.05,
            contract_risk=0.02,
            liquidity_risk=0.04,
            scanner_selected=True,
            scanner_probability_3m=0.18,
            scanner_score=82.5,
            market_regime="NORMAL",
            target_100k=1,
            target_500k=1,
            target_1m=0,
            target_3m=0,
            outcome_status="FAILURE",
            is_mature=True,
        )
        self.assertEqual(row.token_address, "Token123456789")
        self.assertTrue(row.is_mature)
        self.assertEqual(row.target_100k, 1)

    def test_entry_quality_labeler(self):
        # HIGH_SLIPPAGE_ENTRY
        self.assertEqual(
            LearningDatasetBuilder._label_entry_quality(mfe_pct=60.0, mae_pct=-10.0, slippage_pct=6.0, time_to_target_min=10.0),
            "HIGH_SLIPPAGE_ENTRY",
        )
        # FALSE_BREAKOUT_ENTRY
        self.assertEqual(
            LearningDatasetBuilder._label_entry_quality(mfe_pct=10.0, mae_pct=-45.0, slippage_pct=1.5, time_to_target_min=0.0),
            "FALSE_BREAKOUT_ENTRY",
        )
        # GOOD_ENTRY
        self.assertEqual(
            LearningDatasetBuilder._label_entry_quality(mfe_pct=60.0, mae_pct=-15.0, slippage_pct=2.0, time_to_target_min=15.0),
            "GOOD_ENTRY",
        )
        # EARLY_ENTRY
        self.assertEqual(
            LearningDatasetBuilder._label_entry_quality(mfe_pct=40.0, mae_pct=-35.0, slippage_pct=2.0, time_to_target_min=30.0),
            "EARLY_ENTRY",
        )
        # LATE_ENTRY
        self.assertEqual(
            LearningDatasetBuilder._label_entry_quality(mfe_pct=15.0, mae_pct=-10.0, slippage_pct=1.0, time_to_target_min=5.0),
            "LATE_ENTRY",
        )

    def test_exit_quality_labeler(self):
        # MISSED_EXTENSION
        self.assertEqual(
            LearningDatasetBuilder._label_exit_quality(realized_return_pct=80.0, mfe_pct=600.0, max_drawdown_pct=20.0),
            "MISSED_EXTENSION",
        )
        # EXIT_TOO_EARLY
        self.assertEqual(
            LearningDatasetBuilder._label_exit_quality(realized_return_pct=40.0, mfe_pct=150.0, max_drawdown_pct=15.0),
            "EXIT_TOO_EARLY",
        )
        # EXIT_TOO_LATE
        self.assertEqual(
            LearningDatasetBuilder._label_exit_quality(realized_return_pct=-10.0, mfe_pct=80.0, max_drawdown_pct=40.0),
            "EXIT_TOO_LATE",
        )
        # RUG_PROTECTED
        self.assertEqual(
            LearningDatasetBuilder._label_exit_quality(realized_return_pct=-25.0, mfe_pct=10.0, max_drawdown_pct=-75.0),
            "RUG_PROTECTED",
        )
        # CORRECT_EXIT
        self.assertEqual(
            LearningDatasetBuilder._label_exit_quality(realized_return_pct=180.0, mfe_pct=200.0, max_drawdown_pct=15.0),
            "CORRECT_EXIT",
        )

    def test_learning_dataset_builder_builds(self):
        builder = LearningDatasetBuilder()
        all_datasets = builder.build_all_datasets()

        self.assertIn("SELECTION", all_datasets)
        self.assertIn("ENTRY", all_datasets)
        self.assertIn("EXIT", all_datasets)

        sel_ds = all_datasets["SELECTION"]
        self.assertIsInstance(sel_ds, LearningDataset)
        self.assertEqual(sel_ds.dataset_type, "SELECTION")
        self.assertEqual(sel_ds.feature_count, 12)
        self.assertGreater(len(sel_ds.feature_schema_hash), 0)
        self.assertIn(sel_ds.readiness_status, ("READY", "INSUFFICIENT_TRAINING_DATA"))

        ent_ds = all_datasets["ENTRY"]
        self.assertIsInstance(ent_ds, LearningDataset)
        self.assertEqual(ent_ds.dataset_type, "ENTRY")

        ext_ds = all_datasets["EXIT"]
        self.assertIsInstance(ext_ds, LearningDataset)
        self.assertEqual(ext_ds.dataset_type, "EXIT")


if __name__ == "__main__":
    unittest.main()
