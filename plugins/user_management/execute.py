"""Execute script for user_management plugin.
Called from the Plugin UI. Installs dependencies and initializes the database.
Must be standalone — no framework imports.
"""
import subprocess
import sys
import os


def main():
    print("[user_management] Running execute.py...")

    # 1. Install Python dependencies
    deps = ["psycopg2-binary", "bcrypt", "openpyxl"]
    print(f"[user_management] Installing: {', '.join(deps)}")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", *deps,
             "--quiet", "--disable-pip-version-check"],
            text=True, capture_output=True,
        )
        if result.returncode != 0:
            print(f"[user_management] pip install failed: {result.stderr}")
            return 1
        print("[user_management] Dependencies installed.")
    except Exception as e:
        print(f"[user_management] pip install failed: {e}")
        return 1

    # 2. Initialize database
    try:
        import psycopg2
        import bcrypt
    except ImportError as e:
        print(f"[user_management] Missing dependency after install: {e}")
        return 1

    # Resolve DB URL from env var or default
    db_url = os.environ.get(
        "USER_MGMT_DB_URL",
        "postgresql://a0:a0@localhost:5432/a0_user_mgmt"
    )
    print(f"[user_management] Connecting to: {db_url}")

    try:
        conn = psycopg2.connect(db_url)
        conn.autocommit = True
        cur = conn.cursor()

        # Create tables
        cur.execute("""
            CREATE TABLE IF NOT EXISTS um_users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(100) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                role VARCHAR(20) DEFAULT 'user' CHECK (role IN ('admin', 'user')),
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
        """)
        print("[user_management] Table um_users: OK")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS um_token_usage (
                id SERIAL PRIMARY KEY,
                user_id INTEGER REFERENCES um_users(id) ON DELETE SET NULL,
                context_id VARCHAR(100) NOT NULL,
                model VARCHAR(200) NOT NULL,
                input_tokens INTEGER DEFAULT 0,
                output_tokens INTEGER DEFAULT 0,
                timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
        """)
        print("[user_management] Table um_token_usage: OK")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS um_context_ownership (
                context_id VARCHAR(100) PRIMARY KEY,
                user_id INTEGER REFERENCES um_users(id) ON DELETE CASCADE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
            );
        """)
        print("[user_management] Table um_context_ownership: OK")

        # Create indexes
        cur.execute("CREATE INDEX IF NOT EXISTS idx_um_token_usage_user ON um_token_usage(user_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_um_token_usage_ts ON um_token_usage(timestamp);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_um_token_usage_ctx ON um_token_usage(context_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_um_ctx_ownership_user ON um_context_ownership(user_id);")
        print("[user_management] Indexes: OK")

        # Create admin user if not exists
        cur.execute("SELECT id FROM um_users WHERE username = 'admin'")
        if cur.fetchone() is None:
            admin_pw = os.environ.get("USER_MGMT_ADMIN_PASSWORD", "admin123")
            pw_hash = bcrypt.hashpw(admin_pw.encode(), bcrypt.gensalt()).decode()
            cur.execute(
                "INSERT INTO um_users (username, password_hash, role) VALUES (%s, %s, %s)",
                ('admin', pw_hash, 'admin')
            )
            print(f"[user_management] Admin user created (admin / {admin_pw})")
        else:
            print("[user_management] Admin user already exists.")

        cur.close()
        conn.close()
        print("[user_management] Database initialized successfully.")

    except Exception as e:
        print(f"[user_management] DB init failed: {e}")
        print(
            "[user_management] Make sure PostgreSQL is running and "
            "USER_MGMT_DB_URL env var or plugin config db_url is correct."
        )
        return 1

    print("[user_management] Setup complete!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
