from __future__ import annotations

import os
import smtplib
from datetime import UTC, datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Protocol

from daily_signal.config import DeliveryConfig
from daily_signal.models import DeliveryResult, DeliveryStatus, Edition


class DeliveryError(RuntimeError):
    """A delivery failed without exposing transport credentials."""


class DeliveryProvider(Protocol):
    def deliver(self, artifact: Path, edition: Edition, *, dry_run: bool = False) -> DeliveryResult: ...


class LocalDeliveryProvider:
    def deliver(self, artifact: Path, edition: Edition, *, dry_run: bool = False) -> DeliveryResult:
        if not artifact.is_file():
            raise DeliveryError(f"artifact does not exist: {artifact}")
        return DeliveryResult(
            provider="local",
            status=DeliveryStatus.DRY_RUN if dry_run else DeliveryStatus.SUCCEEDED,
            message="artifact retained locally",
            submitted_at=None if dry_run else datetime.now(UTC),
        )


class KindleSmtpDeliveryProvider:
    def __init__(self, config: DeliveryConfig):
        self.config = config

    def deliver(self, artifact: Path, edition: Edition, *, dry_run: bool = False) -> DeliveryResult:
        if not artifact.is_file():
            raise DeliveryError(f"artifact does not exist: {artifact}")
        maximum = self.config.max_attachment_mb * 1024 * 1024
        if artifact.stat().st_size > maximum:
            raise DeliveryError(f"attachment exceeds {self.config.max_attachment_mb} MiB limit")
        settings = _smtp_settings()
        recipient = os.getenv("DAILY_SIGNAL_KINDLE_EMAIL") or self.config.kindle_email
        if not recipient:
            raise DeliveryError("Kindle email address is not configured")
        if dry_run:
            return DeliveryResult(
                provider="kindle",
                status=DeliveryStatus.DRY_RUN,
                message=f"would submit {artifact.name} to Kindle",
            )
        message = EmailMessage()
        message["Subject"] = f"{edition.publication_name} — {edition.publication_date}"
        message["From"] = settings["sender"]
        message["To"] = recipient
        message.set_content(
            "Daily Signal EPUB delivery. SMTP acceptance does not guarantee Kindle import."
        )
        message.add_attachment(
            artifact.read_bytes(),
            maintype="application",
            subtype="epub+zip",
            filename=artifact.name,
        )
        try:
            if settings["security"] == "ssl":
                client = smtplib.SMTP_SSL(settings["host"], settings["port"], timeout=30)
            else:
                client = smtplib.SMTP(settings["host"], settings["port"], timeout=30)
            with client:
                client.ehlo()
                if settings["security"] == "starttls":
                    client.starttls()
                    client.ehlo()
                client.login(settings["username"], settings["password"])
                client.send_message(message)
        except (OSError, smtplib.SMTPException) as error:
            raise DeliveryError(f"SMTP submission failed ({type(error).__name__})") from error
        return DeliveryResult(
            provider="kindle",
            status=DeliveryStatus.SUCCEEDED,
            message="SMTP server accepted the message; Kindle import is not confirmed",
            submitted_at=datetime.now(UTC),
        )


def provider_for(config: DeliveryConfig) -> DeliveryProvider:
    if config.provider == "kindle":
        return KindleSmtpDeliveryProvider(config)
    return LocalDeliveryProvider()


def _smtp_settings() -> dict[str, str | int]:
    required = {
        "host": os.getenv("DAILY_SIGNAL_SMTP_HOST"),
        "username": os.getenv("DAILY_SIGNAL_SMTP_USERNAME"),
        "password": os.getenv("DAILY_SIGNAL_SMTP_PASSWORD"),
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise DeliveryError("missing SMTP environment variables: " + ", ".join(missing))
    security = os.getenv("DAILY_SIGNAL_SMTP_SECURITY", "starttls").lower()
    if security not in {"starttls", "ssl"}:
        raise DeliveryError("DAILY_SIGNAL_SMTP_SECURITY must be starttls or ssl")
    default_port = "465" if security == "ssl" else "587"
    try:
        port = int(os.getenv("DAILY_SIGNAL_SMTP_PORT", default_port))
    except ValueError as error:
        raise DeliveryError("DAILY_SIGNAL_SMTP_PORT must be an integer") from error
    return {
        **required,
        "sender": os.getenv("DAILY_SIGNAL_SMTP_FROM") or required["username"],
        "security": security,
        "port": port,
    }

