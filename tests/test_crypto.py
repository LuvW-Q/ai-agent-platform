"""
Tests for crypto at rest — encrypt/decrypt round-trip, edge cases, and model integration.

Usage:
    APP_SECRET_KEY=<some-key> pytest tests/test_crypto.py -v
"""
from __future__ import annotations

import importlib
import os

import pytest
from cryptography.fernet import Fernet

# ── Unit tests for encrypt / decrypt ──────────────────────────────────────────


def test_round_trip_with_env_key(monkeypatch):
    """Test 1: set APP_SECRET_KEY, encrypt("sk-test") -> non-plaintext, decrypt == original."""
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("APP_SECRET_KEY", key)

    # Reload core.crypto with the new env key
    from core import crypto

    importlib.reload(crypto)

    plain = "sk-test"
    cipher = crypto.encrypt(plain)
    assert cipher != plain, "encrypt should produce non-plaintext"
    assert crypto.decrypt(cipher) == plain


def test_empty_string(monkeypatch):
    """Test 2: encrypt("") == "" and decrypt("") == ""."""
    monkeypatch.delenv("APP_SECRET_KEY", raising=False)
    from core import crypto

    importlib.reload(crypto)

    assert crypto.encrypt("") == ""
    assert crypto.decrypt("") == ""


def test_decrypt_plaintext_fallback(monkeypatch):
    """Test 3: decrypt(non-cipher) returns the input as-is (legacy plaintext compat)."""
    monkeypatch.delenv("APP_SECRET_KEY", raising=False)
    from core import crypto

    importlib.reload(crypto)

    legacy = "sk-placeholder"
    assert crypto.decrypt(legacy) == legacy


# ── Model integration test (requires a test database) ─────────────────────────


def test_model_round_trip(db_session):
    """Test 4: create AIModel(api_key="sk-test"), commit, re-query, assert plaintext
    matches and api_key_cipher is not plaintext."""
    from models.ai_model import AIModel

    plain = "sk-test"
    m = AIModel(
        name="test-crypto",
        provider="test",
        api_key=plain,
        model_name="test-model",
        endpoint="https://test.local",
        context_length=4096,
        model_type="chat",
    )
    db_session.add(m)
    db_session.commit()

    # Fresh query
    db_session.expire_all()
    row = db_session.query(AIModel).filter(AIModel.name == "test-crypto").first()

    assert row.api_key == plain, "hybrid getter should return plaintext"
    assert row.api_key_cipher != plain, "db column should hold ciphertext, not plaintext"
