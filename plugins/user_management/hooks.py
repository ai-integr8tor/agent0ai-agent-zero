import subprocess
import sys
from helpers.print_style import PrintStyle


def install():
    """Called when plugin is installed or enabled."""
    PrintStyle.standard("[user_management] Installing dependencies...")
    try:
        subprocess.check_call([
            sys.executable, "-m", "pip", "install",
            "psycopg2-binary", "bcrypt", "openpyxl",
            "--quiet", "--disable-pip-version-check",
        ])
    except Exception as e:
        PrintStyle.error(f"[user_management] pip install failed: {e}")
        return

    try:
        from usr.plugins.user_management.helpers.db import init_db
        from usr.plugins.user_management.helpers.auth import ensure_admin_user
        init_db()
        ensure_admin_user()
        PrintStyle.standard("[user_management] Database initialized successfully.")
    except Exception as e:
        PrintStyle.error(f"[user_management] DB init failed: {e}")
        PrintStyle.error(
            "[user_management] Ensure PostgreSQL is running and "
            "USER_MGMT_DB_URL env var or plugin config is correct."
        )
