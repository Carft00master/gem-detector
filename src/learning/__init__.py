"""
Adaptive Learning Engine (RESEARCH_ONLY Mode)
Implements controlled self-learning: dataset building, challenger training, calibration,
walk-forward validation, error analysis, counterfactual simulation, champion-challenger
comparison, promotion policy gating, model registry, and operational drift detection.
"""

from src.learning.dataset_builder import (
    LearningDataset,
    LearningDatasetBuilder,
    SelectionDatasetRow,
    EntryDatasetRow,
    ExitDatasetRow,
)
from src.learning.trainer import (
    ChallengerTrainer,
    TrainedChallengerModel,
)
from src.learning.calibrator import (
    CalibrationResult,
    ChallengerCalibrator,
)
from src.learning.feature_selector import (
    FeatureImportanceRecord,
    FeatureSelectionReport,
    FeatureSelector,
)
from src.learning.walk_forward import (
    WalkForwardFold,
    WalkForwardReport,
    WalkForwardResult,
    WalkForwardValidator,
)
from src.learning.error_learning import (
    ErrorAnalysisReport,
    ErrorAnalyzer,
    ErrorClassification,
    MissedWinnerProfile,
)
from src.learning.entry_optimizer import (
    ContextualEntryResult,
    EntryOptimizationReport,
    EntryPolicyEvaluation,
    EntryPolicyOptimizer,
)
from src.learning.exit_optimizer import (
    ExitOptimizationReport,
    ExitPolicyEvaluation,
    ExitPolicyOptimizer,
)
from src.learning.counterfactuals import (
    CounterfactualEngine,
    CounterfactualReport,
    EntryCounterfactual,
    ExitCounterfactual,
)
from src.learning.champion_challenger import (
    ChampionChallengerEngine,
    ComparisonScorecard,
    ScorecardMetric,
    ShadowPredictionRecord,
)
from src.learning.promotion_policy import (
    PromotionDecision,
    PromotionPolicy,
    PromotionThresholds,
)
from src.learning.model_registry import (
    ChallengerModelManifest,
    ModelRegistry,
    ModelRollbackEvent,
    PromotionAuditRecord,
)
from src.learning.drift_detector import (
    DriftDimension,
    LearningDriftDetector,
    LearningHealthReport,
)

__all__ = [
    # Dataset Builder
    "LearningDataset", "LearningDatasetBuilder", "SelectionDatasetRow",
    "EntryDatasetRow", "ExitDatasetRow",
    # Trainer
    "ChallengerTrainer", "TrainedChallengerModel",
    # Calibrator
    "CalibrationResult", "ChallengerCalibrator",
    # Feature Selector
    "FeatureImportanceRecord", "FeatureSelectionReport", "FeatureSelector",
    # Walk Forward
    "WalkForwardFold", "WalkForwardReport", "WalkForwardResult", "WalkForwardValidator",
    # Error Learning
    "ErrorAnalysisReport", "ErrorAnalyzer", "ErrorClassification", "MissedWinnerProfile",
    # Entry Optimizer
    "ContextualEntryResult", "EntryOptimizationReport", "EntryPolicyEvaluation", "EntryPolicyOptimizer",
    # Exit Optimizer
    "ExitOptimizationReport", "ExitPolicyEvaluation", "ExitPolicyOptimizer",
    # Counterfactuals
    "CounterfactualEngine", "CounterfactualReport", "EntryCounterfactual", "ExitCounterfactual",
    # Champion Challenger
    "ChampionChallengerEngine", "ComparisonScorecard", "ScorecardMetric", "ShadowPredictionRecord",
    # Promotion Policy
    "PromotionDecision", "PromotionPolicy", "PromotionThresholds",
    # Model Registry
    "ChallengerModelManifest", "ModelRegistry", "ModelRollbackEvent", "PromotionAuditRecord",
    # Drift Detector
    "DriftDimension", "LearningDriftDetector", "LearningHealthReport",
]

