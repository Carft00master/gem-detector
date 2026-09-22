"""
Smart Wallet Entry Similarity & Setup Matching Engine
Compares candidate token market conditions against validated smart wallet entry fingerprints.
Computes SMART_WALLET_MATCH_SCORE (0.0 to 1.0) and SMART_WALLET_CONFIDENCE (0.0 to 1.0).

Note: Measures whether the opportunity matches the structural characteristics of historical winning setups,
without requiring that the wallet currently traded this specific token.
"""

from dataclasses import asdict, dataclass
import math
from typing import Any, Dict, List, Optional
from src.learning.smart_money.wallet_fingerprint import WalletEntryFingerprint


@dataclass
class WalletEntryMatchResult:
    token_address: str
    smart_wallet_match_score: float      # 0.0 to 1.0
    smart_wallet_confidence: float       # 0.0 to 1.0
    matched_fingerprints_count: int
    dimension_scores: Dict[str, float]
    setup_classification: str            # 'STRONG_SMART_MATCH', 'MODERATE_MATCH', 'WEAK_MATCH', 'NO_MATCH'

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class WalletSimilarityEngine:
    """
    Evaluates candidate token alignment with aggregated smart-money entry preferences.
    """

    @classmethod
    def calculate_match_score(
        cls,
        candidate_features: Dict[str, Any],
        validated_fingerprints: List[WalletEntryFingerprint],
    ) -> WalletEntryMatchResult:
        """
        Evaluate token similarity against a collection of validated smart-money fingerprints.
        """
        token_addr = str(candidate_features.get("token_address", "Unknown"))
        if not validated_fingerprints:
            return WalletEntryMatchResult(
                token_address=token_addr,
                smart_wallet_match_score=0.50,
                smart_wallet_confidence=0.0,
                matched_fingerprints_count=0,
                dimension_scores={},
                setup_classification="NO_MATCH",
            )

        mc = float(candidate_features.get("market_cap_usd", 15000.0) or 15000.0)
        age = float(candidate_features.get("token_age_minutes", candidate_features.get("age_minutes", 10.0)) or 10.0)
        liq = float(candidate_features.get("liquidity_usd", 5000.0) or 5000.0)
        regime = str(candidate_features.get("market_regime", "NORMAL")).upper()
        act_density = float(candidate_features.get("activity_density", 0.60) or 0.60)

        individual_scores: List[float] = []

        dim_mc_scores = []
        dim_age_scores = []
        dim_liq_scores = []
        dim_regime_scores = []

        for fp in validated_fingerprints:
            # 1. Market Cap Score
            mc_min, mc_max = fp.optimal_mc_range_usd
            if mc_min <= mc <= mc_max:
                s_mc = 1.0
            else:
                dist = min(abs(mc - mc_min), abs(mc - mc_max))
                s_mc = max(0.0, 1.0 - (dist / max(1.0, mc_max)))
            dim_mc_scores.append(s_mc)

            # 2. Token Age Score
            age_min, age_max = fp.optimal_age_range_min
            if age_min <= age <= age_max:
                s_age = 1.0
            else:
                dist = min(abs(age - age_min), abs(age - age_max))
                s_age = max(0.0, 1.0 - (dist / max(1.0, age_max)))
            dim_age_scores.append(s_age)

            # 3. Liquidity Score
            l_min, l_max = fp.optimal_liquidity_range_usd
            if l_min <= liq <= l_max:
                s_liq = 1.0
            else:
                dist = min(abs(liq - l_min), abs(liq - l_max))
                s_liq = max(0.0, 1.0 - (dist / max(1.0, l_max)))
            dim_liq_scores.append(s_liq)

            # 4. Regime Score
            s_reg = 1.0 if regime in fp.preferred_regimes else 0.40
            dim_regime_scores.append(s_reg)

            # Weighted composite for this fingerprint
            fp_composite = (s_mc * 0.30) + (s_age * 0.25) + (s_liq * 0.25) + (s_reg * 0.20)
            individual_scores.append(fp_composite)

        mean_score = sum(individual_scores) / len(individual_scores) if individual_scores else 0.50
        conf = min(0.95, 0.40 + (len(validated_fingerprints) * 0.10))

        if mean_score >= 0.80:
            classification = "STRONG_SMART_MATCH"
        elif mean_score >= 0.65:
            classification = "MODERATE_MATCH"
        elif mean_score >= 0.50:
            classification = "WEAK_MATCH"
        else:
            classification = "NO_MATCH"

        return WalletEntryMatchResult(
            token_address=token_addr,
            smart_wallet_match_score=round(mean_score, 4),
            smart_wallet_confidence=round(conf, 4),
            matched_fingerprints_count=len(validated_fingerprints),
            dimension_scores={
                "market_cap_similarity": round(sum(dim_mc_scores) / len(dim_mc_scores), 4) if dim_mc_scores else 0.5,
                "token_age_similarity": round(sum(dim_age_scores) / len(dim_age_scores), 4) if dim_age_scores else 0.5,
                "liquidity_similarity": round(sum(dim_liq_scores) / len(dim_liq_scores), 4) if dim_liq_scores else 0.5,
                "regime_similarity": round(sum(dim_regime_scores) / len(dim_regime_scores), 4) if dim_regime_scores else 0.5,
            },
            setup_classification=classification,
        )
