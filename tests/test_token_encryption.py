"""Schwab token files encrypted at rest (TOKEN_ENCRYPTION_KEY,
broker/schwab/auth/token_provider.py). Files live in tmp_path; no network."""

import json

import pytest
from cryptography.fernet import Fernet

from broker.schwab.auth.token_provider import FileTokenProvider, TokenDecryptError, check_token_encryption

TOKENS = {"access_token": "access-abc", "refresh_token": "refresh-xyz", "expires_in": 1800}


def fresh(path):
    """A provider that reads the file again instead of the process-wide cache."""
    provider = FileTokenProvider(str(path))
    provider.invalidate_cache()
    return provider


@pytest.fixture
def key(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", key)
    return key


def test_without_a_key_the_file_stays_plain_json(tmp_path, monkeypatch):
    monkeypatch.delenv("TOKEN_ENCRYPTION_KEY", raising=False)
    path = tmp_path / "token.json"
    FileTokenProvider(str(path)).save_tokens(TOKENS)
    assert json.loads(path.read_text())["refresh_token"] == "refresh-xyz"
    assert fresh(path).get_refresh_token() == "refresh-xyz"


def test_with_a_key_the_file_is_encrypted_and_reads_back(tmp_path, key):
    path = tmp_path / "token.json"
    FileTokenProvider(str(path)).save_tokens(TOKENS)
    content = path.read_text()
    assert "refresh-xyz" not in content and "access-abc" not in content
    assert json.loads(Fernet(key).decrypt(content.encode()))["access_token"] == "access-abc"
    provider = fresh(path)
    assert provider.get_access_token() == "access-abc"
    assert provider.refresh_token_expires_at() is not None
    assert oct(path.stat().st_mode & 0o777) == "0o600"


def test_a_plaintext_file_is_encrypted_in_place_on_first_read(tmp_path, key):
    path = tmp_path / "token.json"
    path.write_text(json.dumps(TOKENS))
    assert fresh(path).get_refresh_token() == "refresh-xyz"
    assert "refresh-xyz" not in path.read_text()
    assert fresh(path).get_refresh_token() == "refresh-xyz"


def test_a_file_the_key_cant_decrypt_reads_as_not_connected(tmp_path, monkeypatch, key):
    path = tmp_path / "token.json"
    FileTokenProvider(str(path)).save_tokens(TOKENS)
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    provider = fresh(path)
    # A ValueError, so BaseClient answers "connect Schwab in Settings".
    with pytest.raises(TokenDecryptError) as exc:
        provider.get_access_token()
    assert isinstance(exc.value, ValueError) and "refresh-xyz" not in str(exc.value)
    assert provider.has_tokens() is False
    monkeypatch.delenv("TOKEN_ENCRYPTION_KEY")
    with pytest.raises(TokenDecryptError):
        fresh(path).get_access_token()


def test_keys_rotate_first_encrypts_any_decrypts(tmp_path, monkeypatch, key):
    path = tmp_path / "token.json"
    FileTokenProvider(str(path)).save_tokens(TOKENS)
    new = Fernet.generate_key().decode()
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", f"{new}, {key}")
    provider = fresh(path)
    assert provider.get_refresh_token() == "refresh-xyz"
    provider.save_tokens(TOKENS)
    assert json.loads(Fernet(new).decrypt(path.read_text().encode()))["refresh_token"] == "refresh-xyz"


def test_a_malformed_key_stops_startup(monkeypatch):
    monkeypatch.setenv("TOKEN_ENCRYPTION_KEY", "not-a-fernet-key")
    with pytest.raises(ValueError):
        check_token_encryption()
