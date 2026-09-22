"""
Composite Gem Scoring Engine
Computes 0-100 Breakout Probability Score and validates hard filters.
"""

from typing import List, Tuple
from src.config import FilterConfig, ScoringConfig
from src.engine.metrics import MetricsEngine
from src.feeds.base_feed import ScoredToken, ScoringBreakdown, TokenCandidate


class BreakoutScorer:
    def __init__(self, scoring_config: ScoringConfig, filter_config: FilterConfig):
        self.scoring_cfg = scoring_config
        self.filter_cfg = filter_config

    def validate_hard_filters(self, token: TokenCandidate) -> Tuple[bool, List[str]]:
        """
        Check if the token meets the minimum criteria for early microcap breakout consideration.
        """
        reasons: List[str] = []

        # 1. Market Cap Range
        if token.market_cap_usd < self.filter_cfg.min_market_cap_usd:
            reasons.append(f"MC below min (${token.market_cap_usd:,.0f} < ${self.filter_cfg.min_market_cap_usd:,.0f})")
        if token.market_cap_usd > self.filter_cfg.max_market_cap_usd:
            reasons.append(f"MC above max (${token.market_cap_usd:,.0f} > ${self.filter_cfg.max_market_cap_usd:,.0f})")

        # 2. Liquidity
        if token.liquidity_usd < self.filter_cfg.min_liquidity_usd:
            reasons.append(f"Liquidity too low (${token.liquidity_usd:,.0f} < ${self.filter_cfg.min_liquidity_usd:,.0f})")
        if token.liquidity_mc_ratio < self.filter_cfg.min_liquidity_mc_ratio:
            reasons.append(f"LP/MC ratio low ({token.liquidity_mc_ratio:.1%} < {self.filter_cfg.min_liquidity_mc_ratio:.1%})")

        # 3. Volume
        if token.volume_5m_usd < self.filter_cfg.min_volume_5m_usd and token.volume_1h_usd < self.filter_cfg.min_volume_5m_usd:
            reasons.append(f"Volume too low (5m: ${token.volume_5m_usd:,.0f})")
        if token.volume_mc_ratio_1h > self.filter_cfg.max_volume_mc_ratio and token.unique_buyers_1h < 25:
            reasons.append(f"Suspicious wash volume ({token.volume_mc_ratio_1h:.1f}x MC with few buyers)")

        # 4. Order Flow
        effective_buy_sell = max(token.buy_sell_ratio_5m, token.buy_sell_ratio_1h)
        if effective_buy_sell < self.filter_cfg.min_buy_sell_ratio and (token.txns_5m_buys + token.txns_5m_sells) > 5:
            reasons.append(f"Buy/Sell ratio low ({effective_buy_sell:.2f}x < {self.filter_cfg.min_buy_sell_ratio:.2f}x)")

        # 5. Security & Contract
        if token.security.is_honeypot:
            reasons.append("HONEYPOT_DETECTED")
        if self.filter_cfg.require_mint_renounced and not token.security.mint_renounced:
            reasons.append("MINT_AUTH_ENABLED")
        if self.filter_cfg.require_freeze_renounced and not token.security.freeze_renounced:
            reasons.append("FREEZE_AUTH_ENABLED")
        if token.security.top10_holder_pct > self.filter_cfg.max_top10_holder_percent:
            reasons.append(f"Top 10 holds {token.security.top10_holder_pct:.1f}% (> {self.filter_cfg.max_top10_holder_percent:.1f}%)")
        if token.security.dev_holding_pct > self.filter_cfg.max_dev_holding_percent and not token.security.dev_sold_all:
            reasons.append(f"Dev holds {token.security.dev_holding_pct:.1f}% (> {self.filter_cfg.max_dev_holding_percent:.1f}%)")

        return len(reasons) == 0, reasons

    def score_token(self, token: TokenCandidate) -> ScoredToken:
        """
        Calculates the comprehensive 0-100 Gem Score across the 5 pillars.
        """
        weights = self.scoring_cfg.weights
        signals: List[str] = []
        warnings: List[str] = []

        # 1. Holder Distribution & Decentralization (Max 25 pts)
        holder_norm, holder_sigs = MetricsEngine.evaluate_holder_decentralization(
            top10_pct=token.security.top10_holder_pct,
            dev_holding_pct=token.security.dev_holding_pct,
            dev_sold_all=token.security.dev_sold_all,
        )
        holder_score = holder_norm * weights.holder_distribution
        signals.extend(holder_sigs)

        # 2. Volume & Momentum Dynamics (Max 25 pts)
        vol_mc = max(token.volume_mc_ratio_5m * 12.0, token.volume_mc_ratio_1h)
        vol_norm, vol_sig = MetricsEngine.evaluate_vol_mc_ratio(vol_mc)
        vol_score = vol_norm * weights.volume_momentum
        if vol_sig != "NO_VOLUME":
            signals.append(vol_sig)

        # 3. Order Flow & Buyer Pressure (Max 20 pts)
        effective_buy_sell = max(token.buy_sell_ratio_5m, token.buy_sell_ratio_1h)
        order_flow_norm, order_sigs = MetricsEngine.evaluate_order_flow(
            buy_sell_ratio=effective_buy_sell,
            buyer_seller_ratio=token.buyer_seller_ratio_1h,
            unique_buyers=token.unique_buyers_1h,
        )
        order_flow_score = order_flow_norm * weights.order_flow
        signals.extend(order_sigs)

        # 4. Liquidity Depth & Lock Quality (Max 20 pts)
        liq_norm, liq_sigs = MetricsEngine.evaluate_liquidity(
            liquidity_usd=token.liquidity_usd,
            liquidity_mc_ratio=token.liquidity_mc_ratio,
            lp_burned_pct=token.security.lp_burned_or_locked_pct,
        )
        liq_score = liq_norm * weights.liquidity_health
        signals.extend(liq_sigs)

        # 5. Social Presence & Virality (Max 10 pts)
        social_points = 0.0
        if token.socials.twitter:
            social_points += 4.0
        if token.socials.telegram:
            social_points += 3.0
        if token.socials.website:
            social_points += 3.0
        social_score = min(weights.social_virality, (social_points / 10.0) * weights.social_virality)

        if token.socials.has_any:
            signals.append(f"SOCIALS_ACTIVE_{token.socials.count}/3")
        else:
            warnings.append("NO_SOCIALS_LISTED")

        # Compile Total Score
        total_score = holder_score + vol_score + order_flow_score + liq_score + social_score
        total_score = round(min(100.0, max(0.0, total_score)), 1)

        # Validate Filters
        passed, filter_reasons = self.validate_hard_filters(token)
        if not passed:
            warnings.extend(filter_reasons)

        breakdown = ScoringBreakdown(
            holder_distribution_score=round(holder_score, 1),
            volume_momentum_score=round(vol_score, 1),
            order_flow_score=round(order_flow_score, 1),
            liquidity_health_score=round(liq_score, 1),
            social_virality_score=round(social_score, 1),
            total_gem_score=total_score,
            signals=list(dict.fromkeys(signals)),
            warnings=list(dict.fromkeys(warnings)),
        )

        return ScoredToken(
            token=token,
            score=breakdown,
            passed_filters=passed,
        )
