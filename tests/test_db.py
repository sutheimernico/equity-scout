"""Central SQLite conventions (v12 R2): WAL + busy timeout so concurrent chains wait
instead of crashing with OperationalError (three schedulers share these DBs)."""
from __future__ import annotations

import threading

from equity_scout import db


def test_connect_enables_wal_and_busy_timeout(tmp_path) -> None:
    con = db.connect(str(tmp_path / "x.db"))
    assert con.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert con.execute("PRAGMA busy_timeout").fetchone()[0] == db.BUSY_TIMEOUT_MS
    con.close()


def test_concurrent_writers_wait_instead_of_crashing(tmp_path) -> None:
    path = str(tmp_path / "x.db")
    setup = db.connect(path)
    setup.execute("CREATE TABLE t (v INTEGER)")
    setup.commit()
    setup.close()

    lock_held = threading.Event()

    def hold_write_lock() -> None:
        con = db.connect(path)
        con.execute("BEGIN IMMEDIATE")
        con.execute("INSERT INTO t VALUES (1)")
        lock_held.set()
        threading.Event().wait(0.3)  # keep the write lock briefly
        con.commit()
        con.close()

    holder = threading.Thread(target=hold_write_lock)
    holder.start()
    lock_held.wait(timeout=5)
    con = db.connect(path)
    con.execute("INSERT INTO t VALUES (2)")  # default busy_timeout=0 would raise here
    con.commit()
    holder.join()
    assert con.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 2
    con.close()
