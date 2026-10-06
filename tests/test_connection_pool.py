from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock

import pytest

from chatbi.infrastructure.database import DatabaseConnectionPool, QueryExecutionError


class Connection:
    def __init__(self):
        self.closed = False
        self.dead = False
    def ping(self, reconnect=False):
        assert reconnect is False
        if self.dead:
            raise OSError("dead")
    def close(self):
        self.closed = True


def test_pool_reserves_creation_slots_under_concurrent_load():
    entered, unblock = Event(), Event()
    created = []
    lock = Lock()
    def factory():
        with lock:
            created.append(Connection())
            if len(created) == 2:
                entered.set()
            conn = created[-1]
        assert unblock.wait(3)
        return conn
    pool = DatabaseConnectionPool(factory, pool_size=1, max_overflow=1, pool_timeout=0.03)
    with ThreadPoolExecutor(max_workers=3) as threads:
        first, second = [threads.submit(pool.acquire) for _ in range(2)]
        assert entered.wait(3)
        with pytest.raises(QueryExecutionError) as error:
            pool.acquire()
        assert error.value.error_type == "pool_timeout"
        assert len(created) == 2
        unblock.set()
        connections = [first.result(), second.result()]
    for conn in connections:
        pool.release(conn)
    assert pool.stats["total"] == 1
    assert sum(conn.closed for conn in created) == 1
    pool.close_all()


def test_failed_connection_creation_returns_reserved_capacity():
    calls = []
    def factory():
        calls.append(1)
        if len(calls) == 1:
            raise OSError("creation failed")
        return Connection()
    pool = DatabaseConnectionPool(factory, 1)
    with pytest.raises(OSError):
        pool.acquire()
    assert pool.stats["total"] == 0
    conn = pool.acquire()
    pool.release(conn)
    pool.close_all()


def test_pool_close_wakes_waiters_and_destroys_late_returns():
    pool = DatabaseConnectionPool(Connection, 1, pool_timeout=3)
    conn = pool.acquire()
    with ThreadPoolExecutor(max_workers=1) as threads:
        future = threads.submit(pool.acquire)
        pool.close_all()
        with pytest.raises(QueryExecutionError):
            future.result(timeout=1)
    pool.release(conn)
    assert conn.closed
    assert pool.stats["total"] == 0
    with pytest.raises(ValueError):
        pool.release(conn)
    pool.close_all()


def test_pool_closed_during_creation_destroys_new_connection():
    entered, unblock = Event(), Event()
    conn = Connection()
    def factory():
        entered.set()
        assert unblock.wait(3)
        return conn
    pool = DatabaseConnectionPool(factory, 1)
    with ThreadPoolExecutor(max_workers=1) as threads:
        future = threads.submit(pool.acquire)
        assert entered.wait(3)
        pool.close_all()
        unblock.set()
        with pytest.raises(QueryExecutionError):
            future.result(timeout=1)
    assert conn.closed
    assert pool.stats["total"] == 0


def test_dead_and_discarded_connections_are_not_reused():
    created = []
    def factory():
        conn = Connection()
        created.append(conn)
        return conn
    pool = DatabaseConnectionPool(factory, 1)
    first = pool.acquire()
    first.dead = True
    pool.release(first)
    second = pool.acquire()
    assert first.closed and second is not first
    pool.release(second, reusable=False)
    assert second.closed and pool.stats["total"] == 0
    pool.close_all()
