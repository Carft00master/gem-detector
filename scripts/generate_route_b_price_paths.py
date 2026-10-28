"""
Route B Realistic Latency Price Paths & Horizon Replay Generator (Review Item 1 Fix).
- Fixes vault balance extraction: selects WSOL account owned by the pool, largest balance, same-mint check.
- Fixes boost_sol: extracts true InitBoost amount from the migration transaction's InitBoostEvent
  (17.584505 SOL for the 19 InitBoost pools; 0.0 SOL for the 15 unboosted Mayhem/custom-threshold pools),
  eliminating the buggy `84.990359 - wsol_open` back-computation.
- Verifies that effective SOL implied by swap price matches `vault_sol + boost_sol` within 2% across all 34 pools.
- Reports Version A (Available Only), Version B (Carried Forward), genuine price crash counts (p_exit/p_entry < 0.5),
  and separate statistics for the 19 standard boosted pools vs all 34 pools.
- Outputs reports/route_b_price_paths.json.
"""

import json
import math
import os
import random
import struct
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

PUMPSWAP_PROGRAM = "pAMMBay6oceH9fJKBRHGP5D4bD4sWpmSwMn52FMfXEA"
WSOL = "So11111111111111111111111111111111111111112"
INIT_BOOST_EVENT_DISC = bytes.fromhex("e445a52e51cb9a1dae7c4af90451f611")
B58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

HORIZONS = {
    "S+5": 5,
    "S+10": 10,
    "S+20": 20,
    "S+40": 40,
    "+30s": 139,
    "+2m": 554,
    "+5m": 1386,
    "+15m": 4158,
    "+60m": 16632,
}

SOL_USD_PRICE = 150.0
PRIORITY_FEE_SOL = 0.002
TIER_0_FEE_RATE = 0.0125  # 125 bps total


def b58decode(s: str) -> bytes:
    n = 0
    for c in s:
        n = n * 58 + B58_ALPHABET.index(c)
    res = n.to_bytes((n.bit_length() + 7) // 8, "big") if n > 0 else b""
    pad = 0
    for c in s:
        if c == "1":
            pad += 1
        else:
            break
    return b"\x00" * pad + res


def get_account_keys(tx: dict) -> List[str]:
    msg = (tx.get("transaction") or {}).get("message") or {}
    raw_keys = msg.get("accountKeys") or []
    keys = []
    for k in raw_keys:
        if isinstance(k, dict):
            keys.append(k.get("pubkey", ""))
        else:
            keys.append(str(k))
    loaded = (tx.get("meta") or {}).get("loadedAddresses") or {}
    for w in loaded.get("writable") or []:
        keys.append(str(w))
    for r in loaded.get("readonly") or []:
        keys.append(str(r))
    return keys


def extract_init_boost_sol(mig_tx: dict) -> float:
    """
    Extract exact boost_sol from the 144-byte InitBoostEvent (disc ae7c4af90451f611, offset 120 u64)
    in the migration transaction's innerInstructions. Returns 0.0 if InitBoost was not called.
    """
    meta = mig_tx.get("meta") or {}
    keys = get_account_keys(mig_tx)
    for grp in meta.get("innerInstructions") or []:
        for ix in grp.get("instructions") or []:
            pid_idx = ix.get("programIdIndex")
            pid = keys[pid_idx] if pid_idx is not None and pid_idx < len(keys) else str(ix.get("programId"))
            if pid == PUMPSWAP_PROGRAM:
                raw_ix = b58decode(ix.get("data", ""))
                if len(raw_ix) == 144 and raw_ix[:16] == INIT_BOOST_EVENT_DISC:
                    boost_lamports = struct.unpack_from("<Q", raw_ix, 120)[0]
                    return boost_lamports / 1e9
    return 0.0


def load_fixture(sig: str) -> Optional[dict]:
    p1 = Path(f"tests/fixtures/txs/{sig}.json")
    if p1.exists():
        try:
            return json.load(open(p1, encoding="utf-8"))
        except Exception:
            return None
    p2 = Path(f"data/retrospective_cache/txs/{sig}.json")
    if p2.exists():
        try:
            return json.load(open(p2, encoding="utf-8"))
        except Exception:
            return None
    return None


def get_pool_balances_from_tx(
    tx: dict,
    pool: str,
    mint: str,
    use_pre: bool = False,
    expected_wsol_vault: Optional[str] = None,
) -> Tuple[Optional[float], Optional[float]]:
    """
    Extract (wsol_balance, token_balance) owned by `pool` from preTokenBalances or postTokenBalances.
    Enforces owner == pool, same-mint check (mint == WSOL for quote vault, mint == token_mint for base vault),
    and selects the largest balance (or exact expected_wsol_vault when provided).
    """
    meta = tx.get("meta") or {}
    keys = get_account_keys(tx)
    tb_list = (meta.get("preTokenBalances") or []) if use_pre else (meta.get("postTokenBalances") or [])
    wsol_cands: List[Tuple[str, float]] = []
    tok_cands: List[float] = []
    for tb in tb_list:
        if tb.get("owner") == pool:
            m = tb.get("mint")
            amt = (tb.get("uiTokenAmount") or {}).get("uiAmount")
            if amt is None:
                continue
            idx = tb.get("accountIndex")
            pubkey = keys[idx] if idx is not None and idx < len(keys) else ""
            if m == WSOL:
                wsol_cands.append((pubkey, float(amt)))
            elif m == mint:
                tok_cands.append(float(amt))

    wsol_bal = None
    if wsol_cands:
        if expected_wsol_vault:
            matched = [amt for pk, amt in wsol_cands if pk == expected_wsol_vault]
            wsol_bal = max(matched) if matched else max(amt for _, amt in wsol_cands)
        else:
            wsol_bal = max(amt for _, amt in wsol_cands)

    tok_bal = max(tok_cands) if tok_cands else None
    return wsol_bal, tok_bal


def get_pool_wsol_vault_address(mig_tx: dict, pool: str) -> str:
    meta = mig_tx.get("meta") or {}
    keys = get_account_keys(mig_tx)
    cands = []
    for tb in meta.get("postTokenBalances") or []:
        if tb.get("owner") == pool and tb.get("mint") == WSOL:
            idx = tb.get("accountIndex")
            pk = keys[idx] if idx is not None and idx < len(keys) else ""
            amt = (tb.get("uiTokenAmount") or {}).get("uiAmount") or 0.0
            cands.append((pk, float(amt)))
    if not cands:
        return ""
    return max(cands, key=lambda x: x[1])[0]


def verify_swap_price_matches_vault_plus_boost(
    pool: str,
    mint: str,
    mig_sig: str,
    boost_sol: float,
    wsol_vault_addr: str,
    sigs: List[dict],
) -> Dict[str, Any]:
    """
    Find the first successful swap on the pool and verify that the effective SOL implied by the
    swap price (`dw_curve * tok_post / dt`) matches `vault_sol + boost_sol` within 2%.
    """
    sigs_sorted = sorted(
        [s for s in sigs if s.get("err") is None and s["signature"] != mig_sig],
        key=lambda x: (x.get("slot", 0), x.get("transactionIndex", 0)),
    )
    for s in sigs_sorted:
        tx = load_fixture(s["signature"])
        if not tx or (tx.get("meta") or {}).get("err") is not None:
            continue
        pw, pt = get_pool_balances_from_tx(tx, pool, mint, use_pre=True, expected_wsol_vault=wsol_vault_addr)
        qw, qt = get_pool_balances_from_tx(tx, pool, mint, use_pre=False, expected_wsol_vault=wsol_vault_addr)
        if pw is not None and pt is not None and qw is not None and qt is not None and abs(qt - pt) > 1.0:
            s_eff_true = pw + boost_sol
            dw = abs(qw - pw)
            dt = abs(qt - pt)
            dw_curve = (dw / 1.002) if qw > pw else (dw / 0.998)
            s_eff_implied = dw_curve * qt / dt
            rel_err_pct = abs(s_eff_implied - s_eff_true) / s_eff_true * 100.0
            assert rel_err_pct <= 2.0, (
                f"Pool {pool} failed 2% effective SOL check: implied={s_eff_implied:.6f}, "
                f"vault+boost={s_eff_true:.6f}, err={rel_err_pct:.4f}%"
            )
            return {
                "swap_signature": s["signature"],
                "pre_vault_sol": round(pw, 6),
                "boost_sol": round(boost_sol, 6),
                "vault_plus_boost_sol": round(s_eff_true, 6),
                "swap_implied_eff_sol": round(s_eff_implied, 6),
                "relative_error_pct": round(rel_err_pct, 4),
            }
    raise AssertionError(f"No valid swap found to verify effective SOL for pool {pool}")


def bootstrap_ci(data: List[float], n_boot: int = 10000, conf: float = 0.95) -> Tuple[float, float]:
    if not data:
        return (0.0, 0.0)
    if len(data) == 1:
        return (data[0], data[0])
    random.seed(42)
    means = []
    n = len(data)
    for _ in range(n_boot):
        sample = [random.choice(data) for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    lower_idx = int((1.0 - conf) / 2.0 * n_boot)
    upper_idx = int((1.0 + conf) / 2.0 * n_boot)
    return round(means[lower_idx], 2), round(means[upper_idx], 2)


def calc_stats(values: List[float]) -> Dict[str, Any]:
    if not values:
        return {"n": 0, "median": None, "mean_ex_top1": None, "frac_below_neg50_pct": None, "bootstrap_95_ci": None}
    v_sorted = sorted(values)
    n = len(v_sorted)
    med = v_sorted[n // 2] if n % 2 != 0 else (v_sorted[n // 2 - 1] + v_sorted[n // 2]) / 2.0
    ex_top1 = v_sorted[:-1] if n > 1 else v_sorted
    mean_ex1 = sum(ex_top1) / len(ex_top1)
    frac_lt_50 = sum(1 for x in v_sorted if x < -50.0) / n
    ci = bootstrap_ci(v_sorted)
    return {
        "n": n,
        "median": round(med, 2),
        "mean_ex_top1": round(mean_ex1, 2),
        "frac_below_neg50_pct": round(frac_lt_50 * 100.0, 2),
        "count_below_neg50": sum(1 for x in v_sorted if x < -50.0),
        "bootstrap_95_ci": list(ci),
    }


def calc_lag_stats(lags: List[int]) -> Dict[str, Any]:
    if not lags:
        return {"n": 0, "median": None, "max": None, "count_lag_gt_50": 0}
    l_sorted = sorted(lags)
    n = len(l_sorted)
    med = l_sorted[n // 2] if n % 2 != 0 else (l_sorted[n // 2 - 1] + l_sorted[n // 2]) / 2.0
    max_lag = l_sorted[-1]
    cnt_gt_50 = sum(1 for l in l_sorted if l > 50)
    return {
        "n": n,
        "median_lag_slots": med,
        "max_lag_slots": max_lag,
        "count_lag_gt_50": cnt_gt_50,
        "pct_lag_gt_50": round(cnt_gt_50 / n * 100.0, 1),
    }


def simulate_trade(
    entry_usd: float,
    entry_vault: float,
    entry_tok: float,
    boost_sol: float,
    exit_vault: float,
    exit_tok: float,
) -> float:
    entry_sol = entry_usd / SOL_USD_PRICE
    net_entry_sol = entry_sol * (1.0 - TIER_0_FEE_RATE)

    s_eff_entry = entry_vault + boost_sol
    trader_tokens = (entry_tok * net_entry_sol) / (s_eff_entry + net_entry_sol)

    s_eff_exit = exit_vault + boost_sol
    gross_sol_exit = (s_eff_exit * trader_tokens) / (exit_tok + trader_tokens)
    net_sol_exit = gross_sol_exit * (1.0 - TIER_0_FEE_RATE) - PRIORITY_FEE_SOL

    capped_net_sol_exit = max(0.0, min(net_sol_exit, exit_vault))
    total_outlay_sol = entry_sol + PRIORITY_FEE_SOL
    ret_pct = ((capped_net_sol_exit - total_outlay_sol) / total_outlay_sol) * 100.0
    return round(ret_pct, 2)


def simulate_price_ratio_return(
    entry_usd: float,
    entry_price_sol: float,
    exit_price_sol: float,
) -> float:
    """
    Pure price-ratio return (excluding self-impact distortion on tiny micro-pools where $91 > pool SOL,
    charging 2x 125 bps Tier 0 swap fee and 2x 0.002 SOL priority fee).
    """
    entry_sol = entry_usd / SOL_USD_PRICE
    net_entry_sol = entry_sol * (1.0 - TIER_0_FEE_RATE)
    gross_exit_sol = net_entry_sol * (exit_price_sol / entry_price_sol) if entry_price_sol > 0 else 0.0
    net_exit_sol = max(0.0, gross_exit_sol * (1.0 - TIER_0_FEE_RATE) - PRIORITY_FEE_SOL)
    total_outlay_sol = entry_sol + PRIORITY_FEE_SOL
    return round(((net_exit_sol - total_outlay_sol) / total_outlay_sol) * 100.0, 2)


def main():
    print("=" * 115)
    print("ROUTE B PRICE PATHS & REALISTIC HORIZON REPLAY (Review Item 1 Vault & Boost Fix)")
    print("True InitBoost extracted from migration tx | Swap-Implied S_eff verified within <2% for all 34 pools")
    print("=" * 115)

    with open("reports/retrospective_report.json", encoding="utf-8") as f:
        retro = json.load(f)

    reached_pools = [r for r in retro["per_migration_table"] if r.get("reached_creation_slot")]
    print(f"Loaded {len(reached_pools)} reached pools.")

    pool_results = []

    rel_prices_slots = {"S+0": [], "S+1": [], "S+2": [], "S+3": []}

    # Version A: Available Only (All 34 pools)
    rel_prices_horizons_avail = {h: [] for h in HORIZONS}
    sim_s10_91_avail = {h: [] for h in HORIZONS if HORIZONS[h] > 10}
    sim_s10_185_avail = {h: [] for h in HORIZONS if HORIZONS[h] > 10}
    sim_s20_91_avail = {h: [] for h in HORIZONS if HORIZONS[h] > 20}
    sim_s20_185_avail = {h: [] for h in HORIZONS if HORIZONS[h] > 20}

    # Version B: Carried Forward (All 34 pools)
    rel_prices_horizons_carried = {h: [] for h in HORIZONS}
    sim_s10_91_carried = {h: [] for h in HORIZONS if HORIZONS[h] > 10}
    sim_s10_185_carried = {h: [] for h in HORIZONS if HORIZONS[h] > 10}
    sim_s20_91_carried = {h: [] for h in HORIZONS if HORIZONS[h] > 20}
    sim_s20_185_carried = {h: [] for h in HORIZONS if HORIZONS[h] > 20}

    # Standard Boosted Subcohort (19 pools where InitBoost was called, wsol_open >= 67.4 SOL)
    sim_s10_91_boosted_avail = {h: [] for h in HORIZONS if HORIZONS[h] > 10}
    sim_s10_91_boosted_carried = {h: [] for h in HORIZONS if HORIZONS[h] > 10}
    sim_s20_91_boosted_avail = {h: [] for h in HORIZONS if HORIZONS[h] > 20}
    sim_s20_91_boosted_carried = {h: [] for h in HORIZONS if HORIZONS[h] > 20}

    # Genuine price crash tracking (price_exit / price_entry < 0.50, or price_ratio_ret < -50%)
    price_ratio_ret_s10_avail = {h: [] for h in HORIZONS if HORIZONS[h] > 10}
    price_ratio_ret_s10_carried = {h: [] for h in HORIZONS if HORIZONS[h] > 10}
    price_ratio_ret_s20_avail = {h: [] for h in HORIZONS if HORIZONS[h] > 20}
    price_ratio_ret_s20_carried = {h: [] for h in HORIZONS if HORIZONS[h] > 20}

    horizon_lags = {h: [] for h in HORIZONS}
    horizon_coverage = {h: {"available": 0, "carried_forward": 0, "not_obtained": 0} for h in HORIZONS}

    pools_s0_surge_gt_1_5 = 0
    max_seff_err_pct = 0.0

    for r in reached_pools:
        idx = r["index"]
        pool = r["pool_address"]
        mint = r["mint"]
        mig_sig = r["migration_signature"]
        c_slot = r["creation_slot"]

        # 1. Opening Balances & True InitBoost from Migration Transaction
        mig_tx = load_fixture(mig_sig)
        assert mig_tx is not None, f"Missing migration fixture for {pool}"
        wsol_vault_addr = get_pool_wsol_vault_address(mig_tx, pool)
        wsol_open, tok_open = get_pool_balances_from_tx(
            mig_tx, pool, mint, use_pre=False, expected_wsol_vault=wsol_vault_addr
        )
        assert wsol_open is not None and tok_open is not None

        boost_sol = extract_init_boost_sol(mig_tx)
        is_boosted_pool = boost_sol > 0.0
        price_open = (wsol_open + boost_sol) / tok_open

        sig_cache_path = f"data/retrospective_cache/pool_sigs/{pool}.json"
        sigs = json.load(open(sig_cache_path, encoding="utf-8"))

        # Verify effective SOL implied by swap price matches vault + boost within 2%
        seff_check = verify_swap_price_matches_vault_plus_boost(
            pool, mint, mig_sig, boost_sol, wsol_vault_addr, sigs
        )
        max_seff_err_pct = max(max_seff_err_pct, seff_check["relative_error_pct"])

        # 2. Window S+0 .. S+3 State Tracking
        window_sigs = [s for s in sigs if 0 <= (s.get("slot", 0) - c_slot) <= 3]

        curr_vault = wsol_open
        curr_tok = tok_open

        slot_states = {}
        for offset_val in [0, 1, 2, 3]:
            offset_label = f"S+{offset_val}"
            target_s = c_slot + offset_val
            s_sigs = [s for s in window_sigs if s.get("slot", 0) == target_s]
            s_sigs_sorted = sorted(s_sigs, key=lambda x: x.get("transactionIndex", 0))

            for s in s_sigs_sorted:
                sig_val = s["signature"]
                tx_data = load_fixture(sig_val)
                if not tx_data:
                    continue
                meta = tx_data.get("meta") or {}
                if meta.get("err") is not None:
                    continue
                w_b, t_b = get_pool_balances_from_tx(
                    tx_data, pool, mint, use_pre=False, expected_wsol_vault=wsol_vault_addr
                )
                if w_b is not None and t_b is not None:
                    curr_vault = w_b
                    curr_tok = t_b

            eff_price = (curr_vault + boost_sol) / curr_tok
            rel_p = eff_price / price_open
            slot_states[offset_label] = {
                "slot": target_s,
                "vault_sol": round(curr_vault, 6),
                "token_reserve": round(curr_tok, 2),
                "effective_price_sol": eff_price,
                "price_rel_open": round(rel_p, 4),
            }
            rel_prices_slots[offset_label].append(rel_p)

        if slot_states["S+0"]["price_rel_open"] > 1.5:
            pools_s0_surge_gt_1_5 += 1

        # 3. Horizon Sampling using PRE-swap reserves of first successful tx at or after target
        horizon_states = {}
        last_known_reserves = (curr_vault, curr_tok, (curr_vault + boost_sol) / curr_tok)

        for h_label, h_slots in HORIZONS.items():
            target_slot = c_slot + h_slots
            candidates = sorted(
                [s for s in sigs if s.get("slot", 0) >= target_slot and s.get("err") is None],
                key=lambda x: (x.get("slot", 0), x.get("transactionIndex", 0)),
            )

            found_pre = None
            found_sig = None
            found_slot = None

            for cand in candidates:
                csig = cand["signature"]
                ctx = load_fixture(csig)
                if ctx and ctx.get("meta"):
                    w_b, t_b = get_pool_balances_from_tx(
                        ctx, pool, mint, use_pre=True, expected_wsol_vault=wsol_vault_addr
                    )
                    if w_b is not None and t_b is not None:
                        found_pre = (w_b, t_b)
                        found_sig = csig
                        found_slot = cand.get("slot", 0)
                        break

            if found_pre:
                h_vault, h_tok = found_pre
                h_eff_price = (h_vault + boost_sol) / h_tok
                rel_open = h_eff_price / price_open
                lag = found_slot - target_slot

                horizon_states[h_label] = {
                    "status": "AVAILABLE",
                    "slot": found_slot,
                    "target_slot": target_slot,
                    "lag_slots": lag,
                    "signature": found_sig,
                    "vault_sol": round(h_vault, 6),
                    "token_reserve": round(h_tok, 2),
                    "effective_price_sol": h_eff_price,
                    "price_rel_open": round(rel_open, 4),
                }
                rel_prices_horizons_avail[h_label].append(round(rel_open, 4))
                rel_prices_horizons_carried[h_label].append(round(rel_open, 4))
                horizon_lags[h_label].append(lag)
                horizon_coverage[h_label]["available"] += 1
                last_known_reserves = (h_vault, h_tok, h_eff_price)
            else:
                c_vault, c_tok, c_price = last_known_reserves
                c_rel_open = c_price / price_open
                horizon_states[h_label] = {
                    "status": "CARRIED_FORWARD",
                    "target_slot": target_slot,
                    "vault_sol": round(c_vault, 6),
                    "token_reserve": round(c_tok, 2),
                    "effective_price_sol": c_price,
                    "price_rel_open": round(c_rel_open, 4),
                    "note": "Carried forward from last known reserves",
                }
                rel_prices_horizons_carried[h_label].append(round(c_rel_open, 4))
                horizon_coverage[h_label]["carried_forward"] += 1

        # 4. Simulate Trades for S+10 and S+20 entries
        s10_st = horizon_states["S+10"]
        s10_v = s10_st["vault_sol"]
        s10_t = s10_st["token_reserve"]
        s10_p = s10_st["effective_price_sol"]

        for h_label in sim_s10_91_avail:
            exit_st = horizon_states[h_label]
            ret91_c = simulate_trade(91.0, s10_v, s10_t, boost_sol, exit_st["vault_sol"], exit_st["token_reserve"])
            ret185_c = simulate_trade(185.0, s10_v, s10_t, boost_sol, exit_st["vault_sol"], exit_st["token_reserve"])
            pr_ret91 = simulate_price_ratio_return(91.0, s10_p, exit_st["effective_price_sol"])

            sim_s10_91_carried[h_label].append(ret91_c)
            sim_s10_185_carried[h_label].append(ret185_c)
            price_ratio_ret_s10_carried[h_label].append(pr_ret91)
            if is_boosted_pool:
                sim_s10_91_boosted_carried[h_label].append(ret91_c)

            if exit_st["status"] == "AVAILABLE":
                sim_s10_91_avail[h_label].append(ret91_c)
                sim_s10_185_avail[h_label].append(ret185_c)
                price_ratio_ret_s10_avail[h_label].append(pr_ret91)
                if is_boosted_pool:
                    sim_s10_91_boosted_avail[h_label].append(ret91_c)

            horizon_states[h_label]["sim_from_s10_91_pct"] = ret91_c
            horizon_states[h_label]["sim_from_s10_185_pct"] = ret185_c
            horizon_states[h_label]["price_ratio_ret_from_s10_91_pct"] = pr_ret91

        s20_st = horizon_states["S+20"]
        s20_v = s20_st["vault_sol"]
        s20_t = s20_st["token_reserve"]
        s20_p = s20_st["effective_price_sol"]

        for h_label in sim_s20_91_avail:
            exit_st = horizon_states[h_label]
            ret91_c = simulate_trade(91.0, s20_v, s20_t, boost_sol, exit_st["vault_sol"], exit_st["token_reserve"])
            ret185_c = simulate_trade(185.0, s20_v, s20_t, boost_sol, exit_st["vault_sol"], exit_st["token_reserve"])
            pr_ret91 = simulate_price_ratio_return(91.0, s20_p, exit_st["effective_price_sol"])

            sim_s20_91_carried[h_label].append(ret91_c)
            sim_s20_185_carried[h_label].append(ret185_c)
            price_ratio_ret_s20_carried[h_label].append(pr_ret91)
            if is_boosted_pool:
                sim_s20_91_boosted_carried[h_label].append(ret91_c)

            if exit_st["status"] == "AVAILABLE":
                sim_s20_91_avail[h_label].append(ret91_c)
                sim_s20_185_avail[h_label].append(ret185_c)
                price_ratio_ret_s20_avail[h_label].append(pr_ret91)
                if is_boosted_pool:
                    sim_s20_91_boosted_avail[h_label].append(ret91_c)

            horizon_states[h_label]["sim_from_s20_91_pct"] = ret91_c
            horizon_states[h_label]["sim_from_s20_185_pct"] = ret185_c
            horizon_states[h_label]["price_ratio_ret_from_s20_91_pct"] = pr_ret91

        pool_results.append({
            "index": idx,
            "pool_address": pool,
            "mint": mint,
            "wsol_vault_address": wsol_vault_addr,
            "creation_slot": c_slot,
            "is_boosted_pool": is_boosted_pool,
            "opening_balances": {
                "vault_sol": round(wsol_open, 6),
                "boost_sol": round(boost_sol, 6),
                "token_reserve": round(tok_open, 2),
                "price_open_sol": price_open,
            },
            "swap_effective_sol_verification": seff_check,
            "window_slots": slot_states,
            "horizon_samples": horizon_states,
        })

    summary = {
        "pools_analyzed": len(reached_pools),
        "boosted_pools_count": sum(1 for p in pool_results if p["is_boosted_pool"]),
        "unboosted_micro_pools_count": sum(1 for p in pool_results if not p["is_boosted_pool"]),
        "max_swap_implied_seff_error_pct": round(max_seff_err_pct, 4),
        "pools_with_s0_price_surge_gt_1_5": {
            "count": pools_s0_surge_gt_1_5,
            "total_pools": len(reached_pools),
            "percentage": round(pools_s0_surge_gt_1_5 / len(reached_pools) * 100.0, 2),
        },
        "price_relative_to_open_by_window_slot": {
            s: calc_stats(rel_prices_slots[s]) for s in ["S+0", "S+1", "S+2", "S+3"]
        },
        "horizon_lag_statistics": {
            h: calc_lag_stats(horizon_lags[h]) for h in HORIZONS
        },
        "price_relative_to_open_by_horizon": {
            h: {
                "version_a_available_only": calc_stats(rel_prices_horizons_avail[h]),
                "version_b_carried_forward": calc_stats(rel_prices_horizons_carried[h]),
                "coverage": horizon_coverage[h],
            }
            for h in HORIZONS
        },
        "headline_simulated_entry_s10": {
            "version_a_available_only": {
                "sim_91_usd": {h: calc_stats(sim_s10_91_avail[h]) for h in sim_s10_91_avail},
                "sim_185_usd": {h: calc_stats(sim_s10_185_avail[h]) for h in sim_s10_185_avail},
                "price_ratio_91_usd_genuine_crashes": {h: calc_stats(price_ratio_ret_s10_avail[h]) for h in price_ratio_ret_s10_avail},
                "boosted_19_pools_sim_91_usd": {h: calc_stats(sim_s10_91_boosted_avail[h]) for h in sim_s10_91_boosted_avail},
            },
            "version_b_carried_forward": {
                "sim_91_usd": {h: calc_stats(sim_s10_91_carried[h]) for h in sim_s10_91_carried},
                "sim_185_usd": {h: calc_stats(sim_s10_185_carried[h]) for h in sim_s10_185_carried},
                "price_ratio_91_usd_genuine_crashes": {h: calc_stats(price_ratio_ret_s10_carried[h]) for h in price_ratio_ret_s10_carried},
                "boosted_19_pools_sim_91_usd": {h: calc_stats(sim_s10_91_boosted_carried[h]) for h in sim_s10_91_boosted_carried},
            },
        },
        "headline_simulated_entry_s20": {
            "version_a_available_only": {
                "sim_91_usd": {h: calc_stats(sim_s20_91_avail[h]) for h in sim_s20_91_avail},
                "sim_185_usd": {h: calc_stats(sim_s20_185_avail[h]) for h in sim_s20_185_avail},
                "price_ratio_91_usd_genuine_crashes": {h: calc_stats(price_ratio_ret_s20_avail[h]) for h in price_ratio_ret_s20_avail},
                "boosted_19_pools_sim_91_usd": {h: calc_stats(sim_s20_91_boosted_avail[h]) for h in sim_s20_91_boosted_avail},
            },
            "version_b_carried_forward": {
                "sim_91_usd": {h: calc_stats(sim_s20_91_carried[h]) for h in sim_s20_91_carried},
                "sim_185_usd": {h: calc_stats(sim_s20_185_carried[h]) for h in sim_s20_185_carried},
                "price_ratio_91_usd_genuine_crashes": {h: calc_stats(price_ratio_ret_s20_carried[h]) for h in price_ratio_ret_s20_carried},
                "boosted_19_pools_sim_91_usd": {h: calc_stats(sim_s20_91_boosted_carried[h]) for h in sim_s20_91_boosted_carried},
            },
        },
    }

    report = {
        "metadata": {
            "title": "Route B Realistic Latency Price Paths & Replay (Review Item 1 Vault & Boost Fix)",
            "methodology": "PRE-swap reserves at target slot | True InitBoost from migration tx | Swap S_eff verified <2%",
            "total_pools": len(reached_pools),
            "fee_tier": "Tier 0 (125 bps total)",
            "priority_fee_sol": PRIORITY_FEE_SOL,
        },
        "summary": summary,
        "per_pool_data": pool_results,
    }

    out_file = "reports/route_b_price_paths.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(f"\nReport generated successfully: {out_file}")
    print(f"Max swap-implied S_eff error across all 34 pools: {max_seff_err_pct:.4f}% (< 2.0% threshold PASS)")
    print(f"Pools with S+0 price(S+0)/price(open) > 1.5x: {pools_s0_surge_gt_1_5} / {len(reached_pools)}")

    print("\n" + "=" * 115)
    print("PRICE RELATIVE TO OPEN: VERSION A (Available Only) vs VERSION B (Carried Forward):")
    print("=" * 115)
    for h in HORIZONS:
        cov = summary["price_relative_to_open_by_horizon"][h]["coverage"]
        va = summary["price_relative_to_open_by_horizon"][h]["version_a_available_only"]
        vb = summary["price_relative_to_open_by_horizon"][h]["version_b_carried_forward"]
        print(f"  {h:<6}: [Ver A: Avail n={va['n']:2d}] Median={va['median']:6.3f}x | Mean(ex1)={va['mean_ex_top1']:6.3f}x | 95% CI=[{va['bootstrap_95_ci'][0]:.2f}, {va['bootstrap_95_ci'][1]:.2f}]")
        print(f"          [Ver B: Carry n={vb['n']:2d}] Median={vb['median']:6.3f}x | Mean(ex1)={vb['mean_ex_top1']:6.3f}x | 95% CI=[{vb['bootstrap_95_ci'][0]:.2f}, {vb['bootstrap_95_ci'][1]:.2f}] (Carried: {cov['carried_forward']})")

    print("\n" + "=" * 115)
    print("HEADLINE ENTRY: S+10 (~2.2s reaction time) -> $91 ENTRY:")
    print("=" * 115)
    for h in sim_s10_91_avail:
        va_all = summary["headline_simulated_entry_s10"]["version_a_available_only"]["sim_91_usd"][h]
        vb_all = summary["headline_simulated_entry_s10"]["version_b_carried_forward"]["sim_91_usd"][h]
        va_pr = summary["headline_simulated_entry_s10"]["version_a_available_only"]["price_ratio_91_usd_genuine_crashes"][h]
        vb_pr = summary["headline_simulated_entry_s10"]["version_b_carried_forward"]["price_ratio_91_usd_genuine_crashes"][h]
        va_b19 = summary["headline_simulated_entry_s10"]["version_a_available_only"]["boosted_19_pools_sim_91_usd"][h]
        vb_b19 = summary["headline_simulated_entry_s10"]["version_b_carried_forward"]["boosted_19_pools_sim_91_usd"][h]
        print(f"  Exit {h:<6}:")
        print(f"    [All 34 E-Model Ver A n={va_all['n']:2d}] Median={va_all['median']:+6.2f}% | Mean(ex1)={va_all['mean_ex_top1']:+6.2f}% | <-50%: {va_all['frac_below_neg50_pct']:5.1f}% ({va_all['count_below_neg50']}/{va_all['n']})")
        print(f"    [All 34 E-Model Ver B n={vb_all['n']:2d}] Median={vb_all['median']:+6.2f}% | Mean(ex1)={vb_all['mean_ex_top1']:+6.2f}% | <-50%: {vb_all['frac_below_neg50_pct']:5.1f}% ({vb_all['count_below_neg50']}/{vb_all['n']})")
        print(f"    [Genuine Price Crash  Ver A n={va_pr['n']:2d}] Median={va_pr['median']:+6.2f}% | Mean(ex1)={va_pr['mean_ex_top1']:+6.2f}% | <-50%: {va_pr['frac_below_neg50_pct']:5.1f}% ({va_pr['count_below_neg50']}/{va_pr['n']})")
        print(f"    [Genuine Price Crash  Ver B n={vb_pr['n']:2d}] Median={vb_pr['median']:+6.2f}% | Mean(ex1)={vb_pr['mean_ex_top1']:+6.2f}% | <-50%: {vb_pr['frac_below_neg50_pct']:5.1f}% ({vb_pr['count_below_neg50']}/{vb_pr['n']})")
        print(f"    [19 Boosted Pools     Ver A n={va_b19['n']:2d}] Median={va_b19['median']:+6.2f}% | Mean(ex1)={va_b19['mean_ex_top1']:+6.2f}% | <-50%: {va_b19['frac_below_neg50_pct']:5.1f}% ({va_b19['count_below_neg50']}/{va_b19['n']})")
        print(f"    [19 Boosted Pools     Ver B n={vb_b19['n']:2d}] Median={vb_b19['median']:+6.2f}% | Mean(ex1)={vb_b19['mean_ex_top1']:+6.2f}% | <-50%: {vb_b19['frac_below_neg50_pct']:5.1f}% ({vb_b19['count_below_neg50']}/{vb_b19['n']})")


if __name__ == "__main__":
    main()
