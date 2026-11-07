from datetime import UTC, date, datetime
from email.message import EmailMessage
from unittest.mock import MagicMock, patch

import pytest

from brief.config import DeliveryConfig
from brief.delivery import DeliveryError, KindleSmtpDeliveryProvider
from brief.models import Edition


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
    artifact = tmp_path / "paper.pdf"
    artifact.write_bytes(b"%PDF")
    monkeypatch.setenv("BRIEF_SMTP_HOST", "smtp.test")
    monkeypatch.setenv("BRIEF_SMTP_USERNAME", "sender@test")
    monkeypatch.setenv("BRIEF_SMTP_PASSWORD", "secret")
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
    attachment = next(part for part in sent.walk() if part.get_filename() == "paper.pdf")
    assert attachment.get_content_type() == "application/pdf"


def test_rejects_oversized_attachment_before_smtp(tmp_path) -> None:
    artifact = tmp_path / "large.pdf"
    artifact.write_bytes(b"x" * (1024 * 1024 + 1))
    provider = KindleSmtpDeliveryProvider(
        DeliveryConfig(provider="kindle", kindle_email="reader@test", max_attachment_mb=1)
    )
    with pytest.raises(DeliveryError, match="exceeds"):
        provider.deliver(artifact, edition())
