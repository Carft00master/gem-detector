"""
Unit tests for CounterfactualEngine and dataclasses in src/learning/counterfactuals.py
"""

import os
from pathlib import Path
import tempfile
import unittest
from typing import List

from src.learning.counterfactuals import (
    CounterfactualEngine,
    CounterfactualReport,
    EntryCounterfactual,
    ExitCounterfactual,
    ENTRY_SCENARIOS,
    EXIT_SCENARIOS,
    SCENARIO_ENTERED_AFTER_CONFIRMATION,
    SCENARIO_ENTERED_AFTER_PULLBACK,
    SCENARIO_ENTERED_IMMEDIATELY,
    SCENARIO_EXITED_AT_2X,
    SCENARIO_EXITED_AT_5X,
    SCENARIO_EXITED_AT_10X,
    SCENARIO_EXITED_RISK_INVALIDATION,
    SCENARIO_EXITED_TRAILING_STOP,
)


class TestCounterfactualEngine(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp_dir.name) / "test_counterfactuals.db"
        self.engine = CounterfactualEngine(db_path=self.db_path)

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_database_initialization(self) -> None:
        """Verify that SQLite tables and indices are created upon initialization."""
        self.assertTrue(self.db_path.exists())
        entries = self.engine.load_all_entry_counterfactuals()
        exits = self.engine.load_all_exit_counterfactuals()
        self.assertEqual(len(entries), 0)
        self.assertEqual(len(exits), 0)

    def test_generate_entry_counterfactuals_triggered(self) -> None:
        """Test entry counterfactuals when both confirmation and pullback scenarios trigger."""
        entries = self.engine.generate_entry_counterfactuals(
            token_address="0xabc123",
            symbol="TEST",
            signal_timestamp="2026-08-25T12:00:00Z",
            alert_price=10.0,
            alert_mc=50000.0,
            peak_price=20.0,
            trough_price=8.0,
            actual_entry_price=10.2,
            actual_return=50.0,
        )
        self.assertEqual(len(entries), 3)

        scenarios = [e.scenario for e in entries]
        self.assertEqual(
            scenarios,
            [
                SCENARIO_ENTERED_IMMEDIATELY,
                SCENARIO_ENTERED_AFTER_CONFIRMATION,
                SCENARIO_ENTERED_AFTER_PULLBACK,
            ],
        )

        # 1. Immediate: entry = 10 * 1.015 = 10.15, slippage = 1.5%
        imm = entries[0]
        self.assertAlmostEqual(imm.hypothetical_entry_price, 10.15, places=4)
        self.assertAlmostEqual(imm.hypothetical_entry_mc, 50750.0, places=2)
        expected_imm_return = ((20.0 - 10.15) / 10.15 * 100.0) - 1.5
        self.assertAlmostEqual(imm.hypothetical_net_return_pct, expected_imm_return, places=4)
        self.assertAlmostEqual(imm.improvement_vs_actual_pct, expected_imm_return - 50.0, places=4)

        # 2. Confirmation: peak=20 >= 10*1.05=10.5 -> triggered
        conf = entries[1]
        self.assertAlmostEqual(conf.hypothetical_entry_price, 10.5, places=4)
        self.assertAlmostEqual(conf.hypothetical_entry_mc, 52500.0, places=2)
        expected_conf_return = ((20.0 - 10.5) / 10.5 * 100.0) - 0.8
        self.assertAlmostEqual(conf.hypothetical_net_return_pct, expected_conf_return, places=4)
        self.assertAlmostEqual(conf.improvement_vs_actual_pct, expected_conf_return - 50.0, places=4)

        # 3. Pullback: trough=8 <= 10*0.90=9.0 -> triggered
        pb = entries[2]
        self.assertAlmostEqual(pb.hypothetical_entry_price, 9.0, places=4)
        self.assertAlmostEqual(pb.hypothetical_entry_mc, 45000.0, places=2)
        expected_pb_return = ((20.0 - 9.0) / 9.0 * 100.0) - 0.5
        self.assertAlmostEqual(pb.hypothetical_net_return_pct, expected_pb_return, places=4)
        self.assertAlmostEqual(pb.improvement_vs_actual_pct, expected_pb_return - 50.0, places=4)

    def test_generate_entry_counterfactuals_untriggered(self) -> None:
        """Test confirmation and pullback when price thresholds are not met."""
        entries = self.engine.generate_entry_counterfactuals(
            token_address="0xabc123",
            symbol="TEST",
            signal_timestamp="2026-08-25T12:00:00Z",
            alert_price=10.0,
            alert_mc=50000.0,
            peak_price=10.2,   # Below confirmation 10.5
            trough_price=9.5,  # Above pullback 9.0
            actual_entry_price=10.0,
            actual_return=-5.0,
        )
        self.assertEqual(len(entries), 3)

        # Confirmation untriggered -> net return = 0.0
        conf = entries[1]
        self.assertEqual(conf.hypothetical_net_return_pct, 0.0)
        self.assertAlmostEqual(conf.improvement_vs_actual_pct, 5.0, places=4)  # 0.0 - (-5.0)

        # Pullback untriggered -> net return = 0.0
        pb = entries[2]
        self.assertEqual(pb.hypothetical_net_return_pct, 0.0)
        self.assertAlmostEqual(pb.improvement_vs_actual_pct, 5.0, places=4)

    def test_generate_exit_counterfactuals(self) -> None:
        """Test 5 exit counterfactual scenarios."""
        exits = self.engine.generate_exit_counterfactuals(
            token_address="0xabc123",
            symbol="TEST",
            entry_timestamp="2026-08-25T12:00:00Z",
            entry_price=10.0,
            peak_price=35.0,          # Reaches 2x (20.0) and 3x, but not 5x (50.0) or 10x (100.0)
            trough_after_peak=7.0,    # Invalidation exit
            actual_exit_price=15.0,
            actual_return=50.0,
            entry_mc=100000.0,
            time_in_trade_min=60.0,
        )
        self.assertEqual(len(exits), 5)
        scenarios = [x.scenario for x in exits]
        self.assertEqual(
            scenarios,
            [
                SCENARIO_EXITED_AT_2X,
                SCENARIO_EXITED_AT_5X,
                SCENARIO_EXITED_AT_10X,
                SCENARIO_EXITED_TRAILING_STOP,
                SCENARIO_EXITED_RISK_INVALIDATION,
            ],
        )

        # 1. 2X Exit: peak=35 >= 20 -> exit at 20.0 (return = +100%)
        x_2x = exits[0]
        self.assertAlmostEqual(x_2x.hypothetical_exit_price, 20.0, places=4)
        self.assertAlmostEqual(x_2x.hypothetical_return_pct, 100.0, places=4)
        self.assertAlmostEqual(x_2x.improvement_vs_actual_pct, 50.0, places=4)

        # 2. 5X Exit: peak=35 < 50 -> exit at trough=7.0 (return = -30%)
        x_5x = exits[1]
        self.assertAlmostEqual(x_5x.hypothetical_exit_price, 7.0, places=4)
        self.assertAlmostEqual(x_5x.hypothetical_return_pct, -30.0, places=4)
        self.assertAlmostEqual(x_5x.improvement_vs_actual_pct, -80.0, places=4)

        # 3. 10X Exit: peak=35 < 100 -> exit at trough=7.0 (return = -30%)
        x_10x = exits[2]
        self.assertAlmostEqual(x_10x.hypothetical_exit_price, 7.0, places=4)
        self.assertAlmostEqual(x_10x.hypothetical_return_pct, -30.0, places=4)

        # 4. Trailing Stop: 35 * 0.75 = 26.25 -> return = ((26.25-10)/10)*100 = 162.5%
        x_ts = exits[3]
        self.assertAlmostEqual(x_ts.hypothetical_exit_price, 26.25, places=4)
        self.assertAlmostEqual(x_ts.hypothetical_return_pct, 162.5, places=4)
        self.assertAlmostEqual(x_ts.improvement_vs_actual_pct, 112.5, places=4)

        # 5. Invalidation: exit at trough=7.0 -> return = -30%
        x_inv = exits[4]
        self.assertAlmostEqual(x_inv.hypothetical_exit_price, 7.0, places=4)
        self.assertAlmostEqual(x_inv.hypothetical_return_pct, -30.0, places=4)

    def test_sqlite_persistence_and_loading(self) -> None:
        """Test persistence across multiple calls and filtering by token."""
        self.engine.generate_entry_counterfactuals(
            token_address="0xTokenA",
            symbol="A",
            signal_timestamp="2026-08-25T12:00:00Z",
            alert_price=1.0,
            alert_mc=10000.0,
            peak_price=2.0,
            trough_price=0.9,
        )
        self.engine.generate_entry_counterfactuals(
            token_address="0xTokenB",
            symbol="B",
            signal_timestamp="2026-08-25T13:00:00Z",
            alert_price=2.0,
            alert_mc=20000.0,
            peak_price=4.0,
            trough_price=1.8,
        )

        all_entries = self.engine.load_all_entry_counterfactuals()
        self.assertEqual(len(all_entries), 6)

        token_a_entries = self.engine.load_entry_counterfactuals_for_token("0xTokenA")
        self.assertEqual(len(token_a_entries), 3)
        self.assertEqual(token_a_entries[0].symbol, "A")

    def test_build_counterfactual_report(self) -> None:
        """Test report calculation and best scenario identification."""
        entries = self.engine.generate_entry_counterfactuals(
            token_address="0xToken1",
            symbol="TOK1",
            signal_timestamp="2026-08-25T12:00:00Z",
            alert_price=1.0,
            alert_mc=10000.0,
            peak_price=5.0,
            trough_price=0.8,
            actual_entry_price=1.0,
            actual_return=100.0,
        )
        exits = self.engine.generate_exit_counterfactuals(
            token_address="0xToken1",
            symbol="TOK1",
            entry_timestamp="2026-08-25T12:00:00Z",
            entry_price=1.0,
            peak_price=5.0,
            trough_after_peak=0.5,
            actual_exit_price=2.0,
            actual_return=100.0,
        )

        report = self.engine.build_counterfactual_report(entries, exits)
        self.assertEqual(report.total_signals_evaluated, 1)
        self.assertEqual(report.entry_scenarios_generated, 3)
        self.assertEqual(report.exit_scenarios_generated, 5)
        self.assertIn(report.best_entry_scenario, ENTRY_SCENARIOS)
        self.assertIn(report.best_exit_scenario, EXIT_SCENARIOS)

        report_dict = report.to_dict()
        self.assertIn("best_entry_scenario", report_dict)
        self.assertIn("best_exit_scenario", report_dict)
        self.assertEqual(len(report_dict["entry_counterfactuals"]), 3)
        self.assertEqual(len(report_dict["exit_counterfactuals"]), 5)


if __name__ == "__main__":
    unittest.main()
