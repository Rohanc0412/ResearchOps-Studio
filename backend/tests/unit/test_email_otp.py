from __future__ import annotations

from dataclasses import dataclass

import pytest
from utils.email import send_password_reset_otp


@dataclass(frozen=True)
class _AuthCfg:
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_starttls: bool = True
    smtp_from_name: str = "noreply"
    smtp_from_email: str | None = None


class _FakeSMTP:
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.started_tls = False
        self.login_calls: list[tuple[str, str]] = []
        self.sent_count = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def starttls(self):
        self.started_tls = True

    def login(self, user: str, password: str):
        self.login_calls.append((user, password))

    def send_message(self, msg):
        self.sent_count += 1


def test_send_password_reset_otp_requires_host_and_from(monkeypatch) -> None:
    monkeypatch.setattr(
        "utils.email.get_auth_config",
        lambda: _AuthCfg(smtp_host=None, smtp_from_email=None),
    )
    with pytest.raises(RuntimeError, match="SMTP not configured"):
        send_password_reset_otp(to_email="test@example.com", otp="123456")

    monkeypatch.setattr(
        "utils.email.get_auth_config",
        lambda: _AuthCfg(smtp_host="smtp.local", smtp_from_email=None),
    )
    with pytest.raises(RuntimeError, match="SMTP not configured"):
        send_password_reset_otp(to_email="test@example.com", otp="123456")

    monkeypatch.setattr(
        "utils.email.get_auth_config",
        lambda: _AuthCfg(smtp_host="   ", smtp_from_email="noreply@example.com"),
    )
    with pytest.raises(RuntimeError, match="SMTP not configured"):
        send_password_reset_otp(to_email="test@example.com", otp="123456")


def test_send_password_reset_otp_requires_both_user_and_password(monkeypatch) -> None:
    monkeypatch.setattr(
        "utils.email.get_auth_config",
        lambda: _AuthCfg(
            smtp_host="smtp.local",
            smtp_from_email="noreply@example.com",
            smtp_user="user",
            smtp_password=None,
        ),
    )
    with pytest.raises(RuntimeError, match="SMTP password missing"):
        send_password_reset_otp(to_email="test@example.com", otp="123456")

    monkeypatch.setattr(
        "utils.email.get_auth_config",
        lambda: _AuthCfg(
            smtp_host="smtp.local",
            smtp_from_email="noreply@example.com",
            smtp_user=None,
            smtp_password="pass",
        ),
    )
    with pytest.raises(RuntimeError, match="SMTP user missing"):
        send_password_reset_otp(to_email="test@example.com", otp="123456")


def test_send_password_reset_otp_skips_login_when_no_credentials(monkeypatch) -> None:
    sent: list[_FakeSMTP] = []

    def _smtp_factory(host: str, port: int):
        smtp = _FakeSMTP(host, port)
        sent.append(smtp)
        return smtp

    monkeypatch.setattr(
        "utils.email.get_auth_config",
        lambda: _AuthCfg(
            smtp_host="smtp.local",
            smtp_port=1025,
            smtp_from_email="noreply@example.com",
            smtp_user=None,
            smtp_password=None,
            smtp_starttls=False,
        ),
    )
    monkeypatch.setattr("utils.email.smtplib.SMTP", _smtp_factory)

    send_password_reset_otp(to_email="test@example.com", otp="123456")

    assert len(sent) == 1
    assert sent[0].host == "smtp.local"
    assert sent[0].port == 1025
    assert sent[0].started_tls is False
    assert sent[0].login_calls == []
    assert sent[0].sent_count == 1


def test_send_password_reset_otp_logs_in_when_credentials_provided(monkeypatch) -> None:
    sent: list[_FakeSMTP] = []

    def _smtp_factory(host: str, port: int):
        smtp = _FakeSMTP(host, port)
        sent.append(smtp)
        return smtp

    monkeypatch.setattr(
        "utils.email.get_auth_config",
        lambda: _AuthCfg(
            smtp_host="smtp.local",
            smtp_port=587,
            smtp_from_email="noreply@example.com",
            smtp_user="user",
            smtp_password="pass",
            smtp_starttls=True,
        ),
    )
    monkeypatch.setattr("utils.email.smtplib.SMTP", _smtp_factory)

    send_password_reset_otp(to_email="test@example.com", otp="123456")

    assert len(sent) == 1
    assert sent[0].started_tls is True
    assert sent[0].login_calls == [("user", "pass")]
    assert sent[0].sent_count == 1

