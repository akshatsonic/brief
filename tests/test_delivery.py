from datetime import UTC, date, datetime
from email.message import EmailMessage
from unittest.mock import MagicMock, patch

import pytest

from daily_signal.config import DeliveryConfig
from daily_signal.delivery import DeliveryError, KindleSmtpDeliveryProvider
from daily_signal.models import Edition


def edition() -> Edition:
    return Edition(
        id="x" * 64,
        publication_name="Paper",
        publication_date=date(2026, 11, 7),
        timezone="UTC",
        articles=[],
        created_at=datetime.now(UTC),
    )


def test_smtp_delivery_uses_attachment_and_starttls(tmp_path, monkeypatch) -> None:
    artifact = tmp_path / "paper.epub"
    artifact.write_bytes(b"epub")
    monkeypatch.setenv("DAILY_SIGNAL_SMTP_HOST", "smtp.test")
    monkeypatch.setenv("DAILY_SIGNAL_SMTP_USERNAME", "sender@test")
    monkeypatch.setenv("DAILY_SIGNAL_SMTP_PASSWORD", "secret")
    client = MagicMock()
    client.__enter__.return_value = client
    with patch("smtplib.SMTP", return_value=client):
        result = KindleSmtpDeliveryProvider(
            DeliveryConfig(provider="kindle", kindle_email="reader@kindle.test")
        ).deliver(artifact, edition())
    assert result.status.value == "succeeded"
    client.starttls.assert_called_once()
    sent: EmailMessage = client.send_message.call_args.args[0]
    assert sent.get_filename() is None
    assert any(part.get_filename() == "paper.epub" for part in sent.walk())


def test_rejects_oversized_attachment_before_smtp(tmp_path) -> None:
    artifact = tmp_path / "large.epub"
    artifact.write_bytes(b"x" * (1024 * 1024 + 1))
    provider = KindleSmtpDeliveryProvider(
        DeliveryConfig(provider="kindle", kindle_email="reader@test", max_attachment_mb=1)
    )
    with pytest.raises(DeliveryError, match="exceeds"):
        provider.deliver(artifact, edition())
