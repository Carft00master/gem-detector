"""
Credit Budget Tracker (Phase 1 Tier FREE & Multi-RPC)
Tracks daily and monthly RPC calls per endpoint.
Emits warning alerts at 70% of monthly budget, and enforces a hard stop at 95%.
"""

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from src.utils.paths import get_data_dir

logger = logging.getLogger(__name__)


class CreditBudgetExceededError(Exception):
    """Raised when an RPC endpoint has reached the 95% hard stop budget threshold."""
    pass


PROVIDER_RATE_METADATA = {
    "endpoint_0": {"name": "Helius (Free Plan)", "rate_limit": "10 req/s RPC, 2 req/s DAS", "unit": "credits"},
    "endpoint_1": {"name": "QuickNode (30-Day Trial)", "rate_limit": "Rate limit unverified", "unit": "credits"},
    "endpoint_2": {"name": "Alchemy (Free Tier)", "rate_limit": "330 CUPS / ~30 req/s", "unit": "CUs"},
    "helius": {"name": "Helius (Free Plan)", "rate_limit": "10 req/s RPC, 2 req/s DAS", "unit": "credits"},
    "quicknode": {"name": "QuickNode (30-Day Trial)", "rate_limit": "Rate limit unverified", "unit": "credits"},
    "alchemy": {"name": "Alchemy (Free Tier)", "rate_limit": "330 CUPS / ~30 req/s", "unit": "CUs"},
    "ankr": {"name": "Ankr (Freemium Tier)", "rate_limit": "~30 req/s limit", "unit": "credits"},
    "drpc": {"name": "dRPC (Free Tier)", "rate_limit": "~2,100 CUPS / ~100 RPS", "unit": "CUs"},
    "grpc": {"name": "Yellowstone gRPC", "rate_limit": "Validator stream", "unit": "messages"},
}

METHOD_COST_WEIGHTS = {
    "helius": {
        "default": 1,
        "getTransaction": 1,
        "getSignaturesForAddress": 1,
        "getAccountInfo": 1,
        "getMultipleAccounts": 1,
        "getProgramAccounts": 10,
        "getAsset": 10,
        "getAssetsByOwner": 10,
    },
    "quicknode": {
        "default": 1,
        "getTransaction": 1,
        "getSignaturesForAddress": 1,
        "getAccountInfo": 1,
        "getMultipleAccounts": 1,
        "getProgramAccounts": 10,
    },
    "alchemy": {
        "default": 15,
        "getTransaction": 20,
        "getSignaturesForAddress": 20,
        "getAccountInfo": 10,
        "getMultipleAccounts": 25,
        "getProgramAccounts": 100,
    },
    "drpc": {
        "default": 20,
        "getTransaction": 20,
        "getSignaturesForAddress": 20,
        "getMultipleAccounts": 20,
        "getAccountInfo": 10,
        "getLatestBlockhash": 10,
        "getSlot": 10,
    },
    "ankr": {
        "default": 500,
        "getAccountInfo": 500,
        "getLatestBlockhash": 500,
    },
}


class CreditBudgetTracker:
    """
    Tracks RPC credits/calls per endpoint.
    Maintains persistent usage statistics across process restarts.
    """
    def __init__(
        self,
        storage_path: Optional[Path] = None,
        endpoint_budgets: Optional[Dict[str, int]] = None,
        warn_threshold_pct: float = 0.70,
        hard_stop_threshold_pct: float = 0.95,
        monthly_budget_per_endpoint: Optional[int] = None,
    ):
        self.storage_path = storage_path or (get_data_dir() / "rpc_credit_budget.json")
        if endpoint_budgets is not None:
            self.endpoint_budgets = dict(endpoint_budgets)
        elif monthly_budget_per_endpoint is not None:
            self.endpoint_budgets = {"default": monthly_budget_per_endpoint}
        else:
            try:
                import yaml
                from src.utils.paths import get_project_root
                cfg_path = get_project_root() / "config" / "settings.yaml"
                if cfg_path.exists():
                    raw_cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
                    self.endpoint_budgets = raw_cfg.get("provider", {}).get("endpoint_budgets", {}) or {}
                else:
                    self.endpoint_budgets = {}
            except Exception:
                self.endpoint_budgets = {}

        if monthly_budget_per_endpoint is not None:
            self.endpoint_budgets["default"] = monthly_budget_per_endpoint

        self.warn_threshold_pct = warn_threshold_pct
        self.hard_stop_threshold_pct = hard_stop_threshold_pct
        self._data: Dict[str, Any] = {}
        self._load()

    @property
    def budgets(self) -> Dict[str, int]:
        return self.endpoint_budgets

    def get_budget_for_endpoint(self, endpoint_id: str) -> int:
        """Fetch explicit monthly credit budget for an endpoint. Fails if unbudgeted."""
        if endpoint_id in self.endpoint_budgets and self.endpoint_budgets[endpoint_id] is not None:
            return self.endpoint_budgets[endpoint_id]
        if "default" in self.endpoint_budgets and self.endpoint_budgets["default"] is not None:
            return self.endpoint_budgets["default"]
        # Check by provider name if endpoint_id or stored alias matches
        record = self._data.get("endpoints", {}).get(endpoint_id, {})
        target = f"{endpoint_id} {record.get('alias', '')}".lower()
        for key in ["quicknode", "quiknode", "alchemy", "helius", "drpc", "ankr"]:
            lookup_key = "quicknode" if key == "quiknode" else key
            if key in target and lookup_key in self.endpoint_budgets and self.endpoint_budgets[lookup_key] is not None:
                return self.endpoint_budgets[lookup_key]
        if endpoint_id.startswith("endpoint_"):
            try:
                idx = int(endpoint_id.split("_")[1])
                keys = [k for k in self.endpoint_budgets.keys() if k != "default"]
                if idx < len(keys):
                    return self.endpoint_budgets[keys[idx]]
            except Exception:
                pass
        raise ValueError(
            f"Configuration error: Endpoint '{endpoint_id}' has no explicit credit budget configured. "
            f"Configured budgets: {list(self.endpoint_budgets.keys())}. Startup/call halted."
        )

    def _get_current_month(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m")

    def _get_current_day(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _load(self) -> None:
        current_month = self._get_current_month()
        if self.storage_path.exists():
            try:
                raw = json.loads(self.storage_path.read_text(encoding="utf-8"))
                if raw.get("month") == current_month:
                    self._data = raw
                    return
            except Exception as e:
                logger.warning(f"Could not load credit budget tracker file: {e}")

        # Initialize fresh month structure
        self._data = {
            "month": current_month,
            "endpoints": {},
        }
        self._save()

    def _save(self) -> None:
        try:
            self.storage_path.parent.mkdir(parents=True, exist_ok=True)
            self.storage_path.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        except Exception as e:
            logger.error(f"Failed to persist credit budget data: {e}")

    def _ensure_endpoint(self, endpoint_id: str, masked_alias: str = "") -> Dict[str, Any]:
        current_month = self._get_current_month()
        if self._data.get("month") != current_month:
            self._data = {"month": current_month, "endpoints": {}}

        endpoints = self._data.setdefault("endpoints", {})
        if endpoint_id not in endpoints:
            endpoints[endpoint_id] = {
                "alias": masked_alias or endpoint_id,
                "monthly_calls": 0,
                "daily_calls": {},
                "warned_70": False,
                "stopped_95": False,
            }
        elif masked_alias:
            endpoints[endpoint_id]["alias"] = masked_alias
        return endpoints[endpoint_id]

    def is_blocked(self, endpoint_id: str) -> bool:
        """Check if endpoint is marked as blocked due to plan restrictions."""
        record = self._ensure_endpoint(endpoint_id)
        return record.get("blocked", False)

    def mark_blocked(self, endpoint_id: str, reason: str = "") -> None:
        """Mark endpoint as blocked (e.g. chain/methods not supported on tier)."""
        record = self._ensure_endpoint(endpoint_id)
        record["blocked"] = True
        record["block_reason"] = reason
        self._save()
        logger.warning(f"[CREDIT BUDGET] Endpoint {record.get('alias', endpoint_id)} marked as BLOCKED: {reason}")

    def can_call(self, endpoint_id: str, masked_alias: str = "") -> bool:
        """
        Check if an endpoint has available credit budget and is not blocked.
        Returns False if the endpoint is blocked or at/above the 95% hard stop threshold.
        """
        record = self._ensure_endpoint(endpoint_id, masked_alias)
        if record.get("blocked"):
            return False

        budget = self.get_budget_for_endpoint(endpoint_id)
        used = record["monthly_calls"]
        hard_stop_limit = int(budget * self.hard_stop_threshold_pct)
        if used >= hard_stop_limit:
            if not record.get("stopped_95"):
                record["stopped_95"] = True
                self._save()
                logger.critical(
                    f"[CREDIT BUDGET CRITICAL] Endpoint {record['alias']} reached 95% hard stop: "
                    f"{used:,} / {budget:,} calls ({used / budget * 100:.1f}%). "
                    f"Calls halted."
                )
            return False
        return True

    def record_call(
        self,
        endpoint_id: str,
        credits: Optional[int] = None,
        method: str = "",
        masked_alias: str = "",
    ) -> int:
        """
        Record RPC call usage for an endpoint using provider-specific method weights.
        Raises CreditBudgetExceededError if the endpoint is at or above 95% limit.
        """
        if credits is None:
            # Determine provider-specific cost weight for method
            target = f"{endpoint_id} {masked_alias}".lower()
            if "quicknode" in target or "quiknode" in target:
                p_key = "quicknode"
            elif "alchemy" in target:
                p_key = "alchemy"
            elif "helius" in target:
                p_key = "helius"
            elif "drpc" in target:
                p_key = "drpc"
            elif "ankr" in target:
                p_key = "ankr"
            else:
                p_key = "default"
            weights = METHOD_COST_WEIGHTS.get(p_key, {})
            credits = weights.get(method, weights.get("default", 1))

        budget = self.get_budget_for_endpoint(endpoint_id)
        record = self._ensure_endpoint(endpoint_id, masked_alias)
        used = record["monthly_calls"]
        hard_stop_limit = int(budget * self.hard_stop_threshold_pct)
        warn_limit = int(budget * self.warn_threshold_pct)

        if used >= hard_stop_limit:
            record["stopped_95"] = True
            self._save()
            raise CreditBudgetExceededError(
                f"Endpoint {record['alias']} has reached 95% credit budget limit "
                f"({used:,} / {budget:,} calls). Hard stop enforced."
            )

        # Increment counts
        record["monthly_calls"] += credits
        today = self._get_current_day()
        daily = record.setdefault("daily_calls", {})
        daily[today] = daily.get(today, 0) + credits

        new_total = record["monthly_calls"]

        # Check 70% warning threshold
        if new_total >= warn_limit and not record.get("warned_70"):
            record["warned_70"] = True
            logger.warning(
                f"[CREDIT BUDGET WARNING] Endpoint {record['alias']} reached 70% of monthly budget: "
                f"{new_total:,} / {budget:,} calls ({new_total / budget * 100:.1f}%)."
            )

        # Check 95% hard stop threshold
        if new_total >= hard_stop_limit and not record.get("stopped_95"):
            record["stopped_95"] = True
            logger.critical(
                f"[CREDIT BUDGET HARD STOP] Endpoint {record['alias']} reached 95% of monthly budget: "
                f"{new_total:,} / {budget:,} calls ({new_total / budget * 100:.1f}%). "
                f"Hard stop engaged."
            )

        self._save()
        return new_total

    def get_endpoint_usage(self, endpoint_id: str) -> Dict[str, Any]:
        """Return usage stats and rate metadata for an endpoint."""
        record = self._ensure_endpoint(endpoint_id)
        today = self._get_current_day()
        monthly = record["monthly_calls"]
        daily = record.get("daily_calls", {}).get(today, 0)
        budget = self.get_budget_for_endpoint(endpoint_id)
        meta = PROVIDER_RATE_METADATA.get(endpoint_id, {})
        if not meta or not meta.get("name"):
            target = f"{endpoint_id} {record.get('alias', '')}".lower()
            for key in ["quicknode", "quiknode", "alchemy", "helius", "drpc", "ankr"]:
                if key in target:
                    lookup_key = "quicknode" if key == "quiknode" else key
                    meta = PROVIDER_RATE_METADATA.get(lookup_key, {})
                    break
        return {
            "endpoint_id": endpoint_id,
            "provider_name": meta.get("name", endpoint_id),
            "rate_limit": meta.get("rate_limit", "N/A"),
            "unit": meta.get("unit", "credits"),
            "alias": record.get("alias", endpoint_id),
            "monthly_calls": monthly,
            "monthly_budget": budget,
            "pct_used": round((monthly / max(1, budget)) * 100.0, 2),
            "daily_calls_today": daily,
            "is_warned_70": record.get("warned_70", False),
            "is_stopped_95": record.get("stopped_95", False),
        }

    def get_all_usage(self, include_aliases: bool = False, configured_endpoints: Optional[list] = None) -> Dict[str, Any]:
        """Return global usage summary across all configured endpoints."""
        if configured_endpoints:
            all_eids = set(configured_endpoints)
        else:
            all_eids = set(self._data.get("endpoints", {}).keys())
            for eid in self.endpoint_budgets.keys():
                if eid != "default":
                    all_eids.add(eid)

            if not include_aliases:
                # If only indexed endpoints (endpoint_0, endpoint_1...) are explicitly configured, keep indexed
                indexed_eids = [eid for eid in all_eids if eid.startswith("endpoint_")]
                if len(indexed_eids) > 1 and len(indexed_eids) == len(self._data.get("endpoints", {})):
                    all_eids = set(indexed_eids)

        return {
            "month": self._data.get("month", self._get_current_month()),
            "endpoints": {eid: self.get_endpoint_usage(eid) for eid in sorted(all_eids)},
        }

