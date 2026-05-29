"""Open Notebook — Setup script.

Checks connectivity to the Open Notebook backend, installs dependencies.
Run from A0's Plugins UI or manually: python execute.py
"""

import os
import subprocess
import sys
import urllib.request


DEFAULT_API_URL = "http://host.docker.internal:5055"


def _check_url(url: str, timeout: int = 5) -> bool:
    """Check if a URL is reachable."""
    try:
        resp = urllib.request.urlopen(f"{url}/api/transformations", timeout=timeout)
        return resp.status == 200
    except Exception:
        return False


def main():
    print("=" * 50)
    print("  Open Notebook — Setup")
    print("=" * 50)
    print()

    # 1. Check Python dependencies
    try:
        import websockets  # noqa: F401
        print("[OK] websockets installed.")
    except ImportError:
        print("Installing websockets...")
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "websockets>=12.0,<14.0"],
            text=True,
            capture_output=True,
        )
        if result.returncode == 0:
            print("[OK] Installed websockets.")
        else:
            print(f"[WARN] pip install websockets failed: {result.stderr[:100]}")

    # 2. Check ON backend connectivity
    api_url = os.environ.get("OPEN_NOTEBOOK_API_URL", DEFAULT_API_URL)
    print(f"\nChecking ON backend at {api_url} ...")

    if _check_url(api_url):
        print("[OK] Open Notebook backend is reachable.")
    elif _check_url("http://localhost:5055"):
        print("[OK] Open Notebook backend reachable at localhost:5055.")
        api_url = "http://localhost:5055"
    else:
        print("[WARN] Open Notebook backend not reachable.")
        print("       Make sure Open Notebook is running on the host (port 5055).")
        print("       The plugin will retry on each request.")

    print()
    print("-" * 50)
    print("  Setup complete!")
    print("-" * 50)
    print()
    print("  Open A0's sidebar > Open Notebook to browse your notebooks.")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
