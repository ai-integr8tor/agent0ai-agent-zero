"""Intercept A0 native login to authenticate against um_users table.

On POST (login attempt):
  - Verify credentials against um_users
  - If valid: set both A0 session auth AND um_* session vars, redirect to main UI
  - If invalid: show login page with error

On GET: let the original handler render the login page normally.

Fallback: if the extension errors (e.g. DB down), the original handler
proceeds and checks .env AUTH_LOGIN/AUTH_PASSWORD as emergency access.
"""
from __future__ import annotations

import asyncio

from helpers.extension import Extension
from helpers.print_style import PrintStyle


class UmLogin(Extension):

    async def execute(self, **kwargs):
        try:
            from flask import redirect, render_template_string, request, session, url_for
            from helpers import files, login

            data = kwargs.get("data", {})

            # Only intercept POST requests (login attempts)
            if request.method != "POST":
                return  # Let original handler show the login page

            username = request.form.get("username", "").strip()
            password = request.form.get("password", "").strip()

            if not username or not password:
                await asyncio.sleep(1)
                login_page = files.read_file("webui/login.html")
                data["result"] = render_template_string(
                    login_page, error="Please enter username and password."
                )
                return

            # Authenticate against um_users table
            from usr.plugins.user_management.helpers.auth import (
                verify_user,
                set_session_user,
            )

            user = verify_user(username, password)
            if user:
                # Set A0 native session auth so requires_auth decorator passes
                cred_hash = login.get_credentials_hash()
                if cred_hash:
                    session["authentication"] = cred_hash
                else:
                    # Edge case: no .env credentials configured
                    session["authentication"] = True

                # Set plugin session vars so token tracking works automatically
                set_session_user(user)

                PrintStyle.standard(
                    f"[user_management] User '{username}' logged in "
                    f"(id={user['id']}, role={user['role']})"
                )

                # Short-circuit original handler: redirect to main UI
                data["result"] = redirect(url_for("serve_index"))
                return

            # Authentication failed
            await asyncio.sleep(1)
            login_page = files.read_file("webui/login.html")
            data["result"] = render_template_string(
                login_page, error="Invalid credentials. Please try again."
            )

        except Exception as e:
            # On error (e.g. DB unreachable), DON'T set data["result"]
            # so the original handler proceeds as fallback (.env credentials)
            PrintStyle.error(f"[user_management] login extension error: {e}")
