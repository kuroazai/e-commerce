"""Where sale emails come from.

`Mailbox` is a protocol so the pipeline can be driven from a real IMAP account,
a folder of .eml files, or a list of fixtures - and so the test suite never needs
a mail server.
"""
from __future__ import annotations

import email
import imaplib
from collections.abc import Iterator
from dataclasses import dataclass, field
from email.message import Message
from pathlib import Path
from typing import Protocol


@dataclass
class InboundEmail:
    """One message, plus the handle needed to mark it processed."""

    sender: str
    subject: str
    body: str
    uid: str = ""


class Mailbox(Protocol):
    def fetch_unread(self, limit: int = 50) -> list[InboundEmail]: ...
    def mark_processed(self, uid: str) -> None: ...


@dataclass
class MemoryMailbox:
    """An in-memory mailbox for tests and dry runs."""

    messages: list[InboundEmail] = field(default_factory=list)
    processed: list[str] = field(default_factory=list)

    def fetch_unread(self, limit: int = 50) -> list[InboundEmail]:
        return [m for m in self.messages if m.uid not in self.processed][:limit]

    def mark_processed(self, uid: str) -> None:
        if uid and uid not in self.processed:
            self.processed.append(uid)


@dataclass
class MaildirMailbox:
    """Reads .eml files from a folder. Useful for replaying a saved mailbox."""

    folder: Path
    processed: list[str] = field(default_factory=list)

    def _messages(self) -> Iterator[tuple[Path, Message]]:
        for path in sorted(Path(self.folder).glob("*.eml")):
            yield path, email.message_from_bytes(path.read_bytes())

    def fetch_unread(self, limit: int = 50) -> list[InboundEmail]:
        from .parsers import message_parts

        out = []
        for path, message in self._messages():
            if str(path) in self.processed:
                continue
            sender, subject, body = message_parts(message)
            out.append(InboundEmail(sender, subject, body, uid=str(path)))
            if len(out) >= limit:
                break
        return out

    def mark_processed(self, uid: str) -> None:
        if uid not in self.processed:
            self.processed.append(uid)


@dataclass
class ImapMailbox:
    """A real IMAP mailbox.

    Credentials come from the environment via Settings, never from source.
    Messages are only flagged \\Seen after the pipeline has recorded them, so a
    crash mid-run leaves them to be picked up again rather than losing a sale.
    """

    host: str
    username: str
    password: str
    folder: str = "INBOX"
    port: int = 993
    _connection: imaplib.IMAP4_SSL | None = None

    def connect(self) -> None:
        self._connection = imaplib.IMAP4_SSL(self.host, self.port)
        self._connection.login(self.username, self.password)
        self._connection.select(self.folder)

    def _require(self) -> imaplib.IMAP4_SSL:
        if self._connection is None:
            self.connect()
        assert self._connection is not None
        return self._connection

    def fetch_unread(self, limit: int = 50) -> list[InboundEmail]:
        from .parsers import message_parts

        connection = self._require()
        status, data = connection.search(None, "UNSEEN")
        if status != "OK":
            return []

        out = []
        for uid in data[0].split()[:limit]:
            # BODY.PEEK avoids setting \\Seen as a side effect of reading, which
            # would mark a message processed before it actually was.
            status, payload = connection.fetch(uid, "(BODY.PEEK[])")
            if status != "OK" or not payload or not isinstance(payload[0], tuple):
                continue
            message = email.message_from_bytes(payload[0][1])
            sender, subject, body = message_parts(message)
            out.append(InboundEmail(sender, subject, body, uid=uid.decode()))
        return out

    def mark_processed(self, uid: str) -> None:
        self._require().store(uid, "+FLAGS", "\\Seen")

    def close(self) -> None:
        if self._connection is not None:
            try:
                self._connection.close()
                self._connection.logout()
            finally:
                self._connection = None
