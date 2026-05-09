#!/usr/bin/env python3
"""CLI tool for managing um_users.

Usage:
    python manage_users.py list
    python manage_users.py create <username> <password> [--role admin|user]
    python manage_users.py update <username> [--password <pw>] [--role admin|user]
    python manage_users.py delete <username>
    python manage_users.py sync          # Sync from config file
"""
import argparse
import json
import os
import sys

# Ensure the A0 root is on the path
sys.path.insert(0, "/a0")

from usr.plugins.user_management.helpers.db import init_db, execute_query
from usr.plugins.user_management.helpers.auth import (
    create_user,
    update_user,
    delete_user,
    list_users,
    hash_password,
)

SYNC_FILE = os.environ.get(
    "UM_USERS_SYNC_FILE",
    "/a0/usr/plugins/user_management/configs/users.json",
)


def cmd_list(args):
    users = list_users()
    if not users:
        print("No users found.")
        return
    print(f"{'ID':<5} {'Username':<20} {'Role':<10} {'Created'}")
    print("-" * 60)
    for u in users:
        print(f"{u['id']:<5} {u['username']:<20} {u['role']:<10} {u.get('created_at', '')}")


def cmd_create(args):
    role = args.role or "admin"
    try:
        result = create_user(args.username, args.password, role=role)
        print(f"Created user '{args.username}' (role={role}, id={result['id']})")
    except Exception as e:
        if "duplicate key" in str(e).lower() or "unique" in str(e).lower():
            print(f"User '{args.username}' already exists. Use 'update' instead.")
        else:
            print(f"Error: {e}")
            sys.exit(1)


def cmd_update(args):
    # Find user by username
    users = execute_query(
        "SELECT id FROM um_users WHERE username = %s", (args.username,)
    )
    if not users:
        print(f"User '{args.username}' not found.")
        sys.exit(1)

    uid = users[0]["id"]
    kwargs = {}
    if args.password:
        kwargs["password"] = args.password
    if args.role:
        kwargs["role"] = args.role

    if not kwargs:
        print("Nothing to update. Use --password and/or --role.")
        return

    result = update_user(uid, **kwargs)
    print(f"Updated user '{args.username}': {result}")


def cmd_delete(args):
    users = execute_query(
        "SELECT id FROM um_users WHERE username = %s", (args.username,)
    )
    if not users:
        print(f"User '{args.username}' not found.")
        sys.exit(1)

    delete_user(users[0]["id"])
    print(f"Deleted user '{args.username}'.")


def cmd_sync(args):
    """Sync users from a JSON config file.

    File format:
    [
        {"username": "admin", "password": "secret", "role": "admin"},
        {"username": "kostas", "password": "secret", "role": "admin"}
    ]

    - New users are created
    - Existing users get password/role updated if specified
    - Users NOT in the file are NOT deleted (safe sync)
    """
    sync_file = args.file or SYNC_FILE
    if not os.path.isfile(sync_file):
        print(f"Sync file not found: {sync_file}")
        print(f"Create it with the expected JSON array format.")
        sys.exit(1)

    with open(sync_file) as f:
        desired_users = json.load(f)

    if not isinstance(desired_users, list):
        print("Sync file must contain a JSON array of user objects.")
        sys.exit(1)

    existing = {u["username"]: u for u in list_users()}

    for entry in desired_users:
        uname = entry.get("username", "").strip()
        pw = entry.get("password", "").strip()
        role = entry.get("role", "admin").strip()

        if not uname:
            continue

        if uname in existing:
            # Update if password or role changed
            kwargs = {}
            if pw:
                kwargs["password"] = pw
            if role and role != existing[uname]["role"]:
                kwargs["role"] = role
            if kwargs:
                update_user(existing[uname]["id"], **kwargs)
                print(f"  Updated: {uname} (role={role})")
            else:
                print(f"  Unchanged: {uname}")
        else:
            if not pw:
                print(f"  Skipped: {uname} (no password for new user)")
                continue
            create_user(uname, pw, role=role)
            print(f"  Created: {uname} (role={role})")

    print("Sync complete.")


def main():
    # Ensure DB tables exist
    init_db()

    parser = argparse.ArgumentParser(description="User management CLI")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("list", help="List all users")

    p_create = sub.add_parser("create", help="Create a user")
    p_create.add_argument("username")
    p_create.add_argument("password")
    p_create.add_argument("--role", default="admin", choices=["admin", "user"])

    p_update = sub.add_parser("update", help="Update a user")
    p_update.add_argument("username")
    p_update.add_argument("--password", default=None)
    p_update.add_argument("--role", default=None, choices=["admin", "user"])

    p_delete = sub.add_parser("delete", help="Delete a user")
    p_delete.add_argument("username")

    p_sync = sub.add_parser("sync", help="Sync users from JSON config")
    p_sync.add_argument("--file", default=None, help="Path to sync file")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    cmds = {
        "list": cmd_list,
        "create": cmd_create,
        "update": cmd_update,
        "delete": cmd_delete,
        "sync": cmd_sync,
    }
    cmds[args.command](args)


if __name__ == "__main__":
    main()
