import os
import threading
from contextlib import contextmanager

import psycopg2
import psycopg2.pool
import psycopg2.extras

_pool = None
_pool_lock = threading.Lock()

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS um_users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(100) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(20) DEFAULT 'user' CHECK (role IN ('admin', 'user')),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS um_token_usage (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES um_users(id) ON DELETE SET NULL,
    context_id VARCHAR(100) NOT NULL,
    model VARCHAR(200) NOT NULL,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS um_context_ownership (
    context_id VARCHAR(100) PRIMARY KEY,
    user_id INTEGER REFERENCES um_users(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_um_token_usage_user ON um_token_usage(user_id);
CREATE INDEX IF NOT EXISTS idx_um_token_usage_ts ON um_token_usage(timestamp);
CREATE INDEX IF NOT EXISTS idx_um_token_usage_ctx ON um_token_usage(context_id);
CREATE INDEX IF NOT EXISTS idx_um_ctx_ownership_user ON um_context_ownership(user_id);
"""


def _get_db_url():
    url = os.environ.get("USER_MGMT_DB_URL")
    if url:
        return url
    try:
        from helpers.plugins import get_plugin_config
        config = get_plugin_config("user_management")
        if config and config.get("db_url"):
            return config["db_url"]
    except Exception:
        pass
    return "postgresql://a0:a0@localhost:5432/a0_user_mgmt"


def _get_pool():
    global _pool
    if _pool is not None:
        return _pool
    with _pool_lock:
        if _pool is not None:
            return _pool
        _pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=1,
            maxconn=10,
            dsn=_get_db_url(),
        )
        return _pool


@contextmanager
def get_conn():
    """Get a connection from the pool (context manager)."""
    pool = _get_pool()
    conn = pool.getconn()
    try:
        yield conn
    finally:
        pool.putconn(conn)


def execute_query(query, params=None):
    """Execute a SELECT query, return list of dicts."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, params)
            return [dict(row) for row in cur.fetchall()]


def execute_write(query, params=None, returning=False):
    """Execute INSERT/UPDATE/DELETE. Returns first row if RETURNING clause used."""
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(query, params)
            conn.commit()
            if returning:
                row = cur.fetchone()
                return dict(row) if row else None
            return None


def init_db():
    """Create tables and indexes."""
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(SCHEMA_SQL)
        conn.commit()
