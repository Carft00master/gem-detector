"""
Unit tests for ModelRegistry and Model Provenance Store
"""

import tempfile
from pathlib import Path
import unittest

from src.learning.model_registry import (
    ChallengerModelManifest,
    ModelRegistry,
    ModelRollbackEvent,
    PromotionAuditRecord,
)


class TestModelRegistry(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_model_registry.db"
        self.registry = ModelRegistry(db_path=self.db_path)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_bootstrap_default_champions(self) -> None:
        """Verify baseline v1.0.0 champions are automatically registered for all model types."""
        for m_type in ("SELECTION", "ENTRY", "EXIT"):
            champ = self.registry.get_current_champion(m_type)
            self.assertIsNotNone(champ)
            self.assertEqual(champ.model_type, m_type)
            self.assertEqual(champ.status, "CHAMPION")
            self.assertEqual(champ.training_dataset_version, "v1.0.0")
            self.assertTrue(len(champ.metrics) > 0)
            self.assertTrue(champ.model_id)

    def test_register_and_get_model(self) -> None:
        """Verify model registration and exact retrieval."""
        manifest = ChallengerModelManifest(
            model_version="v1.1_candidate_001",
            model_type="SELECTION",
            algorithm="gradient_boosting",
            training_dataset_version="v1.1.0",
            feature_schema_version="v1.1.0",
            calibration_version="v1.1.0",
            training_period="2025-01-01T00:00:00Z/2025-08-01T00:00:00Z",
            validation_period="2025-08-01T00:00:00Z/2025-10-01T00:00:00Z",
            test_period="2025-10-01T00:00:00Z/2025-12-01T00:00:00Z",
            training_sample_size=100000,
            validation_sample_size=25000,
            test_sample_size=25000,
            git_commit="git789xyz",
            model_hash="sha256_mock_hash",
            status="CANDIDATE",
            metrics={"roc_auc": 0.88, "brier_score": 0.08},
            promotion_scorecard={"score": 95},
        )
        self.registry.register_model(manifest)

        fetched = self.registry.get_model(manifest.model_id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.model_id, manifest.model_id)
        self.assertEqual(fetched.model_version, "v1.1_candidate_001")
        self.assertEqual(fetched.algorithm, "gradient_boosting")
        self.assertEqual(fetched.metrics["roc_auc"], 0.88)
        self.assertEqual(fetched.promotion_scorecard["score"], 95)

    def test_list_models_with_filters(self) -> None:
        """Verify listing models with type and status filters."""
        m1 = ChallengerModelManifest(
            model_version="cand1",
            model_type="ENTRY",
            status="CANDIDATE",
        )
        m2 = ChallengerModelManifest(
            model_version="cand2",
            model_type="EXIT",
            status="SHADOW",
        )
        self.registry.register_model(m1)
        self.registry.register_model(m2)

        entry_candidates = self.registry.list_models(model_type="ENTRY", status="CANDIDATE")
        self.assertEqual(len(entry_candidates), 1)
        self.assertEqual(entry_candidates[0].model_id, m1.model_id)

        shadow_models = self.registry.list_models(status="SHADOW")
        self.assertEqual(len(shadow_models), 1)
        self.assertEqual(shadow_models[0].model_id, m2.model_id)

    def test_promotion_lifecycle(self) -> None:
        """Verify model promotion lifecycle, retiring old champion and recording audit record."""
        current_champ = self.registry.get_current_champion("SELECTION")
        self.assertIsNotNone(current_champ)

        new_candidate = ChallengerModelManifest(
            model_version="v2.0_champion_selection",
            model_type="SELECTION",
            status="CANDIDATE",
            metrics={"roc_auc": 0.90, "brier_score": 0.07},
        )
        self.registry.register_model(new_candidate)

        audit = PromotionAuditRecord(
            old_champion_id=current_champ.model_id,
            new_champion_id=new_candidate.model_id,
            metrics_before=current_champ.metrics,
            metrics_after=new_candidate.metrics,
            promotion_reason="Passed all gates with >+0.05 ROC-AUC delta",
            validation_period="2025-08-01 to 2025-10-01",
            sample_size=30000,
            confidence_intervals={"roc_auc": (0.885, 0.915)},
            operator_approval=True,
        )
        self.registry.record_promotion(audit)

        # Verify new champion is returned
        active_champ = self.registry.get_current_champion("SELECTION")
        self.assertEqual(active_champ.model_id, new_candidate.model_id)
        self.assertEqual(active_champ.status, "CHAMPION")

        # Verify old champion is RETIRED
        old_champ_model = self.registry.get_model(current_champ.model_id)
        self.assertEqual(old_champ_model.status, "RETIRED")

        # Verify promotion history
        history = self.registry.get_promotion_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].new_champion_id, new_candidate.model_id)
        self.assertEqual(history[0].confidence_intervals["roc_auc"], (0.885, 0.915))
        self.assertTrue(history[0].operator_approval)

    def test_rollback_lifecycle(self) -> None:
        """Verify rollback restores previous champion and updates failure details."""
        orig_champ = self.registry.get_current_champion("ENTRY")
        self.assertIsNotNone(orig_champ)

        bad_cand = ChallengerModelManifest(
            model_version="v1.5_bad_entry",
            model_type="ENTRY",
            status="CHAMPION",
            metrics={"roc_auc": 0.65},
        )
        self.registry.register_model(bad_cand)

        rollback_evt = ModelRollbackEvent(
            old_champion_id=orig_champ.model_id,
            failed_model_id=bad_cand.model_id,
            rollback_reason="Severe drift detected in paper trading",
            metrics_at_failure={"roc_auc": 0.61, "brier_score": 0.28},
        )
        self.registry.record_rollback(rollback_evt)

        # Bad model is ROLLED_BACK
        failed_model = self.registry.get_model(bad_cand.model_id)
        self.assertEqual(failed_model.status, "ROLLED_BACK")
        self.assertEqual(failed_model.rollback_reason, "Severe drift detected in paper trading")

        # Previous champion restored
        restored = self.registry.get_current_champion("ENTRY")
        self.assertEqual(restored.model_id, orig_champ.model_id)
        self.assertEqual(restored.status, "CHAMPION")

        # History check
        rb_history = self.registry.get_rollback_history()
        self.assertEqual(len(rb_history), 1)
        self.assertEqual(rb_history[0].failed_model_id, bad_cand.model_id)


if __name__ == "__main__":
    unittest.main()
