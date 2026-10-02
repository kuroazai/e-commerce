"""Mailbox in, inventory updated and you notified.

The ordering matters and is deliberate:

    fetch -> parse -> record sale -> adjust stock -> notify -> mark processed

A message is only marked processed at the very end. If anything fails in the
middle, the message is seen again on the next run, and `InventoryService` keys on
the order reference so the retry cannot double-count it. The alternative - mark
first, process after - loses sales on any crash.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from ..inventory.service import InventoryService
from .mailbox import InboundEmail, Mailbox
from .notify import Notifier
from .parsers import DEFAULT_PARSERS, ParseResult, SaleEmailParser, parse_email


@dataclass
class PipelineResult:
    processed: int = 0
    recorded: int = 0
    duplicates: int = 0
    unparsed: list[tuple[str, str]] = field(default_factory=list)  # (subject, reason)
    #: Sales that were recorded but whose stock could not be adjusted. The money
    #: moved, so these are not failures - but inventory no longer matches the
    #: shelf, and that needs a person.
    discrepancies: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def needs_attention(self) -> bool:
        return bool(self.unparsed or self.discrepancies)

    def summary(self) -> str:
        lines = [
            f"{self.processed} email(s) seen, {self.recorded} sale(s) recorded, "
            f"{self.duplicates} duplicate(s)"
        ]
        lines += [f"  {n}" for n in self.notes]
        if self.discrepancies:
            lines.append(f"  {len(self.discrepancies)} need stock fixed by hand:")
            lines += [f"    {d}" for d in self.discrepancies]
        if self.unparsed:
            lines.append(f"  {len(self.unparsed)} could not be parsed:")
            lines += [f"    {subject!r}: {reason}" for subject, reason in self.unparsed]
        return "\n".join(lines)


@dataclass
class SalesPipeline:
    inventory: InventoryService
    mailbox: Mailbox
    notifier: Notifier
    parsers: tuple[SaleEmailParser, ...] = DEFAULT_PARSERS
    #: Tried when no parser claims a message. This is where an LLM belongs: the
    #: rare unrecognised format, not the 99% the regexes handle for free. See
    #: `cardshop.agents.AgentTriage.parse_unrecognised_email`.
    fallback: Callable[[InboundEmail], ParseResult] | None = None

    def run(self, limit: int = 50, *, dry_run: bool = False) -> PipelineResult:
        result = PipelineResult()

        for message in self.mailbox.fetch_unread(limit):
            result.processed += 1
            parsed = parse_email(message.sender, message.subject, message.body, self.parsers)

            if not parsed.ok and self.fallback is not None:
                escalated = self.fallback(message)
                # Keep the original reason when the fallback also failed. The
                # fallback's "no model configured" is about the fallback, not
                # about the email, and reporting it loses the actual diagnosis.
                parsed = escalated if escalated.ok else ParseResult(
                    None, f"{parsed.reason}; escalation: {escalated.reason}"
                )

            if not parsed.ok or parsed.sale is None:
                result.unparsed.append((message.subject, parsed.reason))
                # A dry run reports; it does not touch the outside world. Sending
                # here would page you for emails you were only previewing.
                if not dry_run:
                    self.notifier.send(
                        "Unrecognised email",
                        f"{message.subject!r} from {message.sender}: {parsed.reason}",
                    )
                continue  # deliberately NOT marked processed - needs a human

            if dry_run:
                result.notes.append(f"would record: {parsed.sale.card_name} "
                                    f"x{parsed.sale.quantity} GBP {parsed.sale.price_gbp}")
                continue

            applied, note = self.inventory.record_sale(parsed.sale)
            # A successful parse can still carry a caveat worth seeing - a EUR
            # conversion, or a sale the model extracted rather than a parser.
            if parsed.reason:
                note = f"{note} [{parsed.reason}]"
            result.notes.append(note)
            if applied:
                result.recorded += 1
                self.inventory.mark_listing_sold(
                    parsed.sale.order_reference, parsed.sale.marketplace
                )
                # "stock not adjusted" means you have sold something the system
                # cannot account for. That is not routine, so it does not get a
                # routine notification.
                if "not adjusted" in note:
                    result.discrepancies.append(note)
                    self.notifier.send("Sale - STOCK NEEDS FIXING", note)
                else:
                    self.notifier.send("Sale", note)
            else:
                result.duplicates += 1

            self.mailbox.mark_processed(message.uid)

        return result


def describe(message: InboundEmail) -> str:
    """One line for logs and for handing to an agent."""
    return f"from={message.sender!r} subject={message.subject!r} chars={len(message.body)}"
