import sqlite3
import shutil
import sys
import os

sys.path.insert(0, os.path.abspath("."))
from src.research.execution import AMMExecutionSimulator

def backup_db(path):
    if os.path.exists(path):
        backup_path = f"{path}.bak"
        shutil.copy2(path, backup_path)
        print(f"Backed up {path} -> {backup_path}")

def run_repairs():
    print("=== STARTING DATABASE REPAIR ===")
    paper_db = "data/paper_trading.db"
    wallet_db = "data/virtual_wallet.db"

    backup_db(paper_db)
    backup_db(wallet_db)

    sim = AMMExecutionSimulator()

    # 1. REPAIR PAPER TRADES
    p_conn = sqlite3.connect(paper_db)
    p_cur = p_conn.cursor()

    paper_updates = [
        # (trade_id, pnl, ret, liq, outcome)
        ("189f7f0b", 28.78, 57.57, 9577.43, "SUCCESS"),     # SIM
        ("a1f0e77b", -11.42, -27.53, 6130.82, "FAILURE"),   # Sacabambaspis
        ("ba990aa5", -22.60, -56.34, 2666.62, "FAILURE"),   # Camel
        ("511aa287", 351.37, 437.22, 11641.45, "SUCCESS"),  # VANTA (restore liq)
        ("00631c3a", -3.58, -4.37, 5594.37, "FAILURE"),     # Cephalopod (restore liq)
        ("5172f15e", -3.06, -4.38, 6989.36, "FAILURE"),     # Satoshi (restore liq)
    ]

    for tid, pnl, ret, liq, outcome in paper_updates:
        p_cur.execute("""
            UPDATE paper_trades
            SET net_realized_pnl_usd = ?,
                net_realized_return_pct = ?,
                exit_liquidity_usd = ?,
                outcome_label = ?
            WHERE trade_id = ?
        """, (pnl, ret, liq, outcome, tid))
        print(f"[PAPER] Updated trade {tid} -> PnL: ${pnl}, Ret: {ret}%, Outcome: {outcome}")

    p_conn.commit()
    p_conn.close()

    # 2. REPAIR WALLET POSITIONS AND LEDGER
    w_conn = sqlite3.connect(wallet_db)
    w_cur = w_conn.cursor()

    # Target positions in sess_cd310742
    wallet_updates = [
        # (pos_id, pnl, ret, proceeds, exit_impact, exit_liq)
        ("wpos_9834e2ab", 28.78, 57.57, 78.78, 0.5, 9577.43),      # SIM
        ("wpos_18766a6b", 201.98, 460.40, 245.85, 0.3, 11641.45),  # VANTA
        ("wpos_2f0ca8e7", -0.60, -1.37, 43.27, 0.5, 5594.37),      # Cephalopod
        ("wpos_fc240b51", -11.42, -27.53, 30.07, 0.5, 6130.82),    # Sacabambaspis
        ("wpos_e75c284c", -22.60, -56.34, 17.50, 0.6, 2666.62),    # Camel
        ("wpos_d13a9718", -1.40, -4.38, 30.53, 0.5, 6989.36),      # Satoshi
    ]

    for pid, pnl, ret, proceeds, impact, liq in wallet_updates:
        w_cur.execute("""
            UPDATE wallet_positions
            SET net_realized_pnl_usd = ?,
                net_realized_return_pct = ?,
                gross_exit_proceeds_usd = ?,
                exit_price_impact_pct = ?,
                exit_liquidity_usd = ?
            WHERE position_id = ?
        """, (pnl, ret, proceeds, impact, liq, pid))
        print(f"[WALLET POS] Updated {pid} -> PnL: ${pnl}, Ret: {ret}%, Proceeds: ${proceeds}")

        # Update matching SELL entry in wallet_ledger
        w_cur.execute("""
            UPDATE wallet_ledger
            SET amount_usd = ?
            WHERE position_id = ? AND entry_type = 'SELL'
        """, (proceeds, pid))
        print(f"[WALLET LEDGER] Updated SELL amount for {pid} -> ${proceeds}")

    w_conn.commit()

    # 3. RECALCULATE SESSION TOTALS FOR sess_cd310742
    session_id = "sess_cd310742"
    sess_row = w_cur.execute("SELECT * FROM wallet_sessions WHERE session_id = ?", (session_id,)).fetchone()
    s_cols = [col[1] for col in w_cur.execute("PRAGMA table_info(wallet_sessions)").fetchall()]
    sess = dict(zip(s_cols, sess_row))

    starting_capital = float(sess["starting_capital_usd"])

    # Cash = Starting Capital + sum of all ledger entries (BUYs are negative, SELLs are positive)
    ledger_rows = w_cur.execute("SELECT entry_type, amount_usd FROM wallet_ledger WHERE session_id = ?", (session_id,)).fetchall()
    cash = 0.0
    for entry_type, amt in ledger_rows:
        if amt is not None:
            cash += float(amt)

    # Open positions
    open_pos = w_cur.execute("SELECT position_size_usd FROM wallet_positions WHERE session_id = ? AND status = 'OPEN'", (session_id,)).fetchall()
    open_equity = sum(float(r[0]) for r in open_pos)

    total_equity = cash + open_equity
    total_pnl = total_equity - starting_capital

    print(f"\n[RECALC] Session {session_id}:")
    print(f"  Starting Capital: ${starting_capital:.2f}")
    print(f"  Calculated Cash: ${cash:.2f}")
    print(f"  Open Positions Capital: ${open_equity:.2f}")
    print(f"  Total Equity: ${total_equity:.2f}")
    print(f"  Total PnL: ${total_pnl:.2f}")

    # Peak equity & max drawdown
    peak_equity = max(starting_capital, total_equity)
    max_dd = max(0.0, round(((peak_equity - total_equity) / peak_equity) * 100.0, 2)) if peak_equity > 0 else 0.0

    w_cur.execute("""
        UPDATE wallet_sessions
        SET current_cash_usd = ?,
            current_equity_usd = ?,
            peak_equity_usd = ?,
            max_drawdown_pct = ?
        WHERE session_id = ?
    """, (round(cash, 2), round(total_equity, 2), round(peak_equity, 2), round(max_dd, 2), session_id))
    w_conn.commit()

    print(f"[RECALC] Updated session {session_id} in wallet_sessions successfully.")

    w_conn.close()

    # 4. SYNC TO DIST DIRECTORIES
    dist_targets = [
        "dist/MemecoinScanner/data",
        "dist/MemecoinScanner/_internal/data",
    ]
    for dt in dist_targets:
        if os.path.exists(dt):
            shutil.copy2(paper_db, os.path.join(dt, "paper_trading.db"))
            shutil.copy2(wallet_db, os.path.join(dt, "virtual_wallet.db"))
            print(f"[DIST SYNC] Copied updated DBs to {dt}")

    print("=== REPAIR COMPLETE ===")

if __name__ == "__main__":
    run_repairs()
