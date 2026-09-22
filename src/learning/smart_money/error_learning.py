"""
Smart Money Error Learning & Missed Winner Diagnostics
Performs post-mortem error classification on mature token outcomes:
- TRUE POSITIVE (TP): Selected by scanner & validated smart wallets participated -> Reached 3M
- FALSE POSITIVE (FP): Selected by scanner but failed (were smart wallets absent or deceived?)
- FALSE NEGATIVE (FN): Missed winner (did validated smart wallets enter early before breakout?)
- TRUE NEGATIVE (TN): Correctly filtered low-conviction noise

Produces:
- MISSED_WINNER_REPORT
- FALSE_POSITIVE_REPORT
"""

from dataclasses import asdict, dataclass, field
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class SmartMoneyErrorDiagnosticRecord:
    token_address: str
    symbol: str
    error_class: str                    # TRUE_POSITIVE, FALSE_POSITIVE, FALSE_NEGATIVE, TRUE_NEGATIVE
    scanner_p3m: float
    actual_outcome_reached_3m: bool
    smart_wallets_participated: bool
    participating_wallets_count: int
    smart_wallet_match_score: float
    primary_failure_reason: Optional[str] = None
    actionable_insight: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class SmartMoneyErrorLearner:
    """
    Diagnoses prediction errors to identify smart wallet predictive efficacy.
    """

    @classmethod
    def analyze_token_outcomes(
        cls,
        outcomes: List[Dict[str, Any]],
    ) -> List[SmartMoneyErrorDiagnosticRecord]:
        """
        Classify mature outcomes into error diagnostic quadrants.
        """
        records: List[SmartMoneyErrorDiagnosticRecord] = []

        for out in outcomes:
            p3m = float(out.get("p_reach_3m", 0.0) or 0.0)
            reached = bool(out.get("target_reached_3m") or out.get("reached_3m") or out.get("outcome_label") == "SUCCESS")
            selected = p3m >= 0.15

            wallet_count = int(out.get("smart_wallets_count", 0) or 0)
            has_wallets = wallet_count > 0
            match_score = float(out.get("smart_wallet_match_score", 0.5) or 0.5)

            if selected and reached:
                e_class = "TRUE_POSITIVE"
                insight = "High model conviction aligned with smart wallet participation" if has_wallets else "Organic breakout without tracked smart money"
                reason = None
            elif selected and not reached:
                e_class = "FALSE_POSITIVE"
                if not has_wallets and match_score < 0.55:
                    insight = "False breakout: no smart wallet participation or setup match present"
                    reason = "ABSENT_SMART_MONEY_CONFIRMATION"
                else:
                    insight = "Late dev dump or liquidity exhaustion after smart entry"
                    reason = "UNANTICIPATED_RUG_OR_DUMP"
            elif not selected and reached:
                e_class = "FALSE_NEGATIVE"
                if has_wallets:
                    insight = "Missed winner: validated smart wallets entered early before scanner threshold"
                    reason = "EARLY_SMART_WALLET_LEAD"
                else:
                    insight = "Stealth breakout with organic retail accumulation"
                    reason = "STEALTH_ORGANIC_TRACTION"
            else:
                e_class = "TRUE_NEGATIVE"
                insight = "Correctly filtered low-conviction noise"
                reason = None

            records.append(SmartMoneyErrorDiagnosticRecord(
                token_address=str(out.get("token_address", "Unknown")),
                symbol=str(out.get("symbol", "UNKNOWN")),
                error_class=e_class,
                scanner_p3m=round(p3m, 4),
                actual_outcome_reached_3m=reached,
                smart_wallets_participated=has_wallets,
                participating_wallets_count=wallet_count,
                smart_wallet_match_score=round(match_score, 4),
                primary_failure_reason=reason,
                actionable_insight=insight,
            ))

        return records
