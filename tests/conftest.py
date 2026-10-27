"""
Global pytest configuration and test database isolation fixture (Phase 1.3 / B4).
Guarantees that NO test in the suite can ever write to data/paper_trading.db or data/onchain_events.db.
All default ledgers and event stores are redirected to an isolated temporary test directory.
"""

import sys
import os
from pathlib import Path
import sqlite3
import pytest

_repo_root_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _repo_root_path not in sys.path:
    sys.path.insert(0, _repo_root_path)

from src.utils.paths import get_project_root


@pytest.fixture(scope="session", autouse=True)
def isolate_test_environment(tmp_path_factory):
    """
    Session-level isolation fixture.
    Redirects default paper_trading.db and onchain_events.db to an ephemeral temporary directory
    and blocks any direct writes to production databases.
    """
    repo_root = get_project_root().resolve()
    prod_data_dir = (repo_root / "data").resolve()
    prod_paper_db = (prod_data_dir / "paper_trading.db").resolve()
    prod_event_db = (prod_data_dir / "onchain_events.db").resolve()

    test_data_dir = tmp_path_factory.mktemp("test_isolated_data")
    test_paper_db = test_data_dir / "paper_trading.db"
    test_event_db = test_data_dir / "onchain_events.db"
    test_jsonl = test_data_dir / "paper_trades.jsonl"

    # Patch default constructors of ledger and event store to use test DBs
    from src.paper.ledger import PaperTradingLedger
    from src.onchain.events import OnChainEventStore
    from src.paper.shadow_ledger import ShadowLedgerManager

    orig_ledger_init = PaperTradingLedger.__init__
    orig_event_init = OnChainEventStore.__init__
    orig_shadow_init = ShadowLedgerManager.__init__

    def patched_ledger_init(self, db_path=None, jsonl_path=None, *args, **kwargs):
        target_db = db_path if db_path is not None else test_paper_db
        target_jsonl = jsonl_path if jsonl_path is not None else test_jsonl
        orig_ledger_init(self, db_path=target_db, jsonl_path=target_jsonl, *args, **kwargs)

    def patched_event_init(self, db_path=None, *args, **kwargs):
        target_db = db_path if db_path is not None else test_event_db
        orig_event_init(self, db_path=target_db, *args, **kwargs)

    def patched_shadow_init(self, ledger=None, db_path=None, *args, **kwargs):
        target_db = db_path if db_path is not None else test_paper_db
        orig_shadow_init(self, ledger=ledger, db_path=target_db, *args, **kwargs)

    PaperTradingLedger.__init__ = patched_ledger_init
    OnChainEventStore.__init__ = patched_event_init
    ShadowLedgerManager.__init__ = patched_shadow_init

    # Monkeypatch sqlite3.connect to forbid opening production DBs for writing
    real_connect = sqlite3.connect

    def guarded_connect(database, *args, **kwargs):
        if isinstance(database, (str, Path)):
            db_path = Path(database).resolve()
            if db_path in (prod_paper_db, prod_event_db):
                uri = kwargs.get("uri", False)
                mode = kwargs.get("mode")
                if mode != "ro" and not (isinstance(database, str) and "mode=ro" in database):
                    raise RuntimeError(
                        f"TEST ISOLATION VIOLATION: Test attempted to connect to production database "
                        f"{db_path.name} without read-only mode!"
                    )
        return real_connect(database, *args, **kwargs)

    sqlite3.connect = guarded_connect

    yield test_data_dir

    # Teardown
    sqlite3.connect = real_connect
    PaperTradingLedger.__init__ = orig_ledger_init
    OnChainEventStore.__init__ = orig_event_init
    ShadowLedgerManager.__init__ = orig_shadow_init
