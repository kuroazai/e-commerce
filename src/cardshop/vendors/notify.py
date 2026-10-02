"""Telling you something happened."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class Notifier(Protocol):
    def send(self, title: str, message: str) -> None: ...


@dataclass
class ConsoleNotifier:
    def send(self, title: str, message: str) -> None:
        print(f"[{title}] {message}")


@dataclass
class CollectingNotifier:
    """Records notifications instead of sending them. For tests and dry runs."""

    sent: list[tuple[str, str]] = field(default_factory=list)

    def send(self, title: str, message: str) -> None:
        self.sent.append((title, message))


@dataclass
class WebhookNotifier:
    """POSTs to a webhook - Slack, Discord, ntfy, whatever you point it at.

    Failures are swallowed deliberately: a notification that cannot be delivered
    must not roll back a sale that has already been recorded.
    """

    url: str
    timeout: float = 10.0

    def send(self, title: str, message: str) -> None:
        import requests

        try:
            requests.post(self.url, json={"text": f"*{title}*\n{message}"},
                          timeout=self.timeout)
        except Exception as exc:  # noqa: BLE001 - never break the pipeline
            print(f"[notify failed] {exc}: {title} - {message}")
