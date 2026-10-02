"""Vendor automation: sale emails in, inventory and notifications out."""
from .mailbox import ImapMailbox, InboundEmail, Mailbox, MaildirMailbox, MemoryMailbox
from .notify import CollectingNotifier, ConsoleNotifier, Notifier, WebhookNotifier
from .parsers import (
    DEFAULT_PARSERS,
    CardmarketSaleParser,
    EbaySaleParser,
    ParseResult,
    SaleEmailParser,
    message_parts,
    money_after,
    money_after_with_currency,
    parse_email,
    to_gbp,
)
from .pipeline import PipelineResult, SalesPipeline, describe

__all__ = [
    "Mailbox", "MemoryMailbox", "MaildirMailbox", "ImapMailbox", "InboundEmail",
    "Notifier", "ConsoleNotifier", "CollectingNotifier", "WebhookNotifier",
    "parse_email", "ParseResult", "SaleEmailParser",
    "EbaySaleParser", "CardmarketSaleParser", "DEFAULT_PARSERS", "message_parts",
    "money_after", "money_after_with_currency", "to_gbp",
    "SalesPipeline", "PipelineResult", "describe",
]
