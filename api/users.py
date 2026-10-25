"""App user accounts (multi-user, admin-managed).

SQLite database next to the Schwab token store — on Fly that's the /data
volume, so accounts survive redeploys (DB_PATH overrides the location).
There's no self-service sign-up: the admin creates accounts and resets
passwords (api/admin.py). The very first admin is bootstrapped from
ADMIN_USERNAME / ADMIN_PASSWORD when the database is empty; after that the
database — not those env vars — is the source of truth for passwords.

Recovery if every admin is locked out:
    uv run python -m api.users reset-password <username>
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import re
import secrets
import sqlite3
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator, Optional

logger = logging.getLogger(__name__)

MIN_PASSWORD_LENGTH = 8
_SCRYPT = {"n": 2**14, "r": 8, "p": 1}  # ~16MB memory, tens of ms per hash


def db_path() -> str:
    explicit = os.getenv("DB_PATH")
    if explicit:
        return explicit
    token_file = os.getenv("TOKEN_FILE") or "token.json"
    return os.path.join(os.path.dirname(os.path.abspath(token_file)), "nutrade.db")


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    path = db_path()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


@dataclass(frozen=True)
class User:
    id: int
    username: str
    is_admin: bool
    disabled: bool
    created_at: float
    password_changed_at: float
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    email: Optional[str] = None
    # The broker this user's Portfolio pages read (a registered name, see
    # service/portfolio/providers); None = the default broker.
    broker: Optional[str] = None
    # The broker account (full account number) this user's Portfolio pages
    # read, when their broker login covers more than one; None = the
    # broker's first. Server-side only — deliberately not in public().
    broker_account: Optional[str] = None

    def public(self) -> dict:
        return {
            "id": self.id,
            "username": self.username,
            "isAdmin": self.is_admin,
            "disabled": self.disabled,
            "createdAt": self.created_at,
            "firstName": self.first_name,
            "lastName": self.last_name,
            "email": self.email,
        }


def _row_to_user(row: Optional[sqlite3.Row]) -> Optional[User]:
    if row is None:
        return None
    return User(
        id=row["id"],
        username=row["username"],
        is_admin=bool(row["is_admin"]),
        disabled=bool(row["disabled"]),
        created_at=row["created_at"],
        password_changed_at=row["password_changed_at"],
        first_name=row["first_name"],
        last_name=row["last_name"],
        email=row["email"],
        broker=row["broker"] if "broker" in row.keys() else None,
        broker_account=row["broker_account"] if "broker_account" in row.keys() else None,
    )


# ─── Passwords ───────────────────────────────────────────────────────────

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return "scrypt${n}${r}${p}${salt}${digest}".format(
        **_SCRYPT,
        salt=base64.b64encode(salt).decode(),
        digest=base64.b64encode(digest).decode(),
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        actual = hashlib.scrypt(
            password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p)
        )
        return hmac.compare_digest(actual, base64.b64decode(digest))
    except Exception:
        return False


# A real-looking hash to verify against when the username doesn't exist, so
# "no such user" and "wrong password" take the same time.
_DUMMY_HASH = hash_password(secrets.token_hex(16))


def validate_new_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters")


def validate_username(username: str) -> str:
    username = username.strip()
    if not (3 <= len(username) <= 40) or not all(c.isalnum() or c in "._-@" for c in username):
        raise ValueError("Username must be 3–40 characters: letters, numbers, . _ - @")
    return username


# Optional profile fields. Blank means "not set" (stored as NULL).
PROFILE_FIELDS = ("first_name", "last_name", "email")
_MAX_NAME_LENGTH = 50
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def validate_profile(first_name: Optional[str], last_name: Optional[str], email: Optional[str]) -> dict:
    def clean(value: Optional[str]) -> Optional[str]:
        value = (value or "").strip()
        return value or None

    profile = {"first_name": clean(first_name), "last_name": clean(last_name), "email": clean(email)}
    for field, label in (("first_name", "First name"), ("last_name", "Last name")):
        if profile[field] and len(profile[field]) > _MAX_NAME_LENGTH:
            raise ValueError(f"{label} must be at most {_MAX_NAME_LENGTH} characters")
    if profile["email"] and (len(profile["email"]) > 254 or not _EMAIL_RE.match(profile["email"])):
        raise ValueError("Enter a valid email address")
    return profile


# ─── Schema / bootstrap ──────────────────────────────────────────────────

def init_db() -> None:
    with _connect() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                is_admin INTEGER NOT NULL DEFAULT 0,
                disabled INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL,
                password_changed_at REAL NOT NULL
            )
            """
        )
        # Profile columns were added after the table first shipped — add them
        # to an existing database in place (all nullable, so nothing to backfill).
        existing = {r["name"] for r in conn.execute("PRAGMA table_info(users)").fetchall()}
        # The chosen broker account was first stored as "schwab_account";
        # rename keeps a choice already made.
        if "schwab_account" in existing and "broker_account" not in existing:
            conn.execute("ALTER TABLE users RENAME COLUMN schwab_account TO broker_account")
            existing = {*existing - {"schwab_account"}, "broker_account"}
        for column in (*PROFILE_FIELDS, "broker", "broker_account"):
            if column not in existing:
                conn.execute(f"ALTER TABLE users ADD COLUMN {column} TEXT")
        count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if count == 0:
        username = os.getenv("ADMIN_USERNAME", "").strip()
        password = os.getenv("ADMIN_PASSWORD", "")
        if not username or not password:
            logger.warning("No users and no ADMIN_USERNAME/ADMIN_PASSWORD — nobody can log in yet.")
            return
        # Bootstrap admin gets id 1 — which is what keeps the original Schwab
        # token store (token_provider.LEGACY_OWNER_ID).
        create_user(username, password, is_admin=True, _skip_validation=True)
        logger.info("Bootstrapped admin user %r from ADMIN_USERNAME", username)


# ─── Queries ─────────────────────────────────────────────────────────────

def get_user(user_id: int) -> Optional[User]:
    with _connect() as conn:
        return _row_to_user(conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())


def get_user_by_username(username: str) -> Optional[User]:
    with _connect() as conn:
        return _row_to_user(
            conn.execute("SELECT * FROM users WHERE username = ?", (username.strip(),)).fetchone()
        )


def authenticate(username: str, password: str) -> Optional[User]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username.strip(),)).fetchone()
    if row is None:
        verify_password(password, _DUMMY_HASH)
        return None
    if not verify_password(password, row["password_hash"]) or row["disabled"]:
        return None
    return _row_to_user(row)


def list_users() -> list[User]:
    with _connect() as conn:
        return [_row_to_user(r) for r in conn.execute("SELECT * FROM users ORDER BY id").fetchall()]


def create_user(
    username: str,
    password: str,
    is_admin: bool = False,
    first_name: Optional[str] = None,
    last_name: Optional[str] = None,
    email: Optional[str] = None,
    _skip_validation: bool = False,
) -> User:
    if not _skip_validation:
        username = validate_username(username)
        validate_new_password(password)
    profile = validate_profile(first_name, last_name, email)
    now = time.time()
    try:
        with _connect() as conn:
            cur = conn.execute(
                "INSERT INTO users (username, password_hash, is_admin, created_at, password_changed_at, "
                "first_name, last_name, email) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (username, hash_password(password), int(is_admin), now, now,
                 profile["first_name"], profile["last_name"], profile["email"]),
            )
            user_id = cur.lastrowid
    except sqlite3.IntegrityError:
        raise ValueError(f"Username {username!r} is already taken")
    return get_user(user_id)


def set_password(user_id: int, password: str) -> None:
    """Also bumps password_changed_at, which signs out every existing
    session of that user (api/auth.py rejects older tokens)."""
    validate_new_password(password)
    with _connect() as conn:
        conn.execute(
            "UPDATE users SET password_hash = ?, password_changed_at = ? WHERE id = ?",
            (hash_password(password), time.time(), user_id),
        )


def set_broker(user_id: int, name: Optional[str]) -> None:
    """Which broker this user's Portfolio pages read (None = the default).
    Clears the chosen account too: account numbers belong to one broker."""
    with _connect() as conn:
        conn.execute("UPDATE users SET broker = ?, broker_account = NULL WHERE id = ?", (name, user_id))


def set_broker_account(user_id: int, account_number: Optional[str]) -> None:
    """Which broker account this user's Portfolio pages read (None = the
    first one the broker lists)."""
    with _connect() as conn:
        conn.execute("UPDATE users SET broker_account = ? WHERE id = ?", (account_number, user_id))


def set_profile(user_id: int, first_name: Optional[str], last_name: Optional[str], email: Optional[str]) -> User:
    profile = validate_profile(first_name, last_name, email)
    with _connect() as conn:
        conn.execute(
            "UPDATE users SET first_name = ?, last_name = ?, email = ? WHERE id = ?",
            (profile["first_name"], profile["last_name"], profile["email"], user_id),
        )
    return get_user(user_id)


def set_disabled(user_id: int, disabled: bool) -> None:
    with _connect() as conn:
        conn.execute("UPDATE users SET disabled = ? WHERE id = ?", (int(disabled), user_id))


def delete_user(user_id: int) -> None:
    with _connect() as conn:
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))


def active_admin_count() -> int:
    with _connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM users WHERE is_admin = 1 AND disabled = 0").fetchone()[0]


# ─── CLI recovery ────────────────────────────────────────────────────────

def _cli() -> None:
    import getpass

    if len(sys.argv) != 3 or sys.argv[1] != "reset-password":
        print("Usage: python -m api.users reset-password <username>")
        sys.exit(2)
    from dotenv import load_dotenv

    load_dotenv()
    init_db()
    user = get_user_by_username(sys.argv[2])
    if user is None:
        print(f"No user named {sys.argv[2]!r} in {db_path()}")
        sys.exit(1)
    password = getpass.getpass("New password: ")
    if password != getpass.getpass("Repeat: "):
        print("Passwords don't match")
        sys.exit(1)
    set_password(user.id, password)
    set_disabled(user.id, False)
    print(f"Password reset for {user.username!r} (account enabled).")


if __name__ == "__main__":
    _cli()
