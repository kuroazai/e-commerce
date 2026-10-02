"""The LLM, used only where deterministic code has genuinely run out.

Two escalation points, both discovered by testing rather than assumed:

1. A sale email no parser recognises. Marketplaces change templates and add new
   ones; a regex cannot keep up, and the alternative is silently dropping sales.
2. A listing title that matches two inventory items too closely to separate.

Everything else - parsing the 99% of emails that match a known format, stock
arithmetic, fee calculation, pricing - stays deterministic. An LLM in those paths
adds cost, latency and a failure mode, and buys nothing.

`AgentTriage` works without smolagents installed: it reports what it would have
escalated. That keeps the pipeline runnable, and testable, with no model.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ..inventory.models import SaleEvent
from ..inventory.service import InventoryService
from ..market.base import Marketplace
from ..vendors.mailbox import InboundEmail
from ..vendors.parsers import ParseResult

EXTRACTION_PROMPT = """You are reading a marketplace sale notification email.

Extract the sale as JSON with exactly these keys:
  marketplace      one of: ebay_uk, cardmarket, tcgplayer, manual
  card_name        the item title as listed
  price_gbp        number, the amount the buyer paid for the item
  quantity         integer, default 1
  order_reference  the order or transaction id
  buyer            buyer username if present, else ""
  postage_gbp      number, postage charged, else 0

If this is not a sale notification, return exactly: {"not_a_sale": true}
Return only JSON. Do not guess an order reference - leave it "" if absent.

FROM: %(sender)s
SUBJECT: %(subject)s

%(body)s
"""


@dataclass
class TriageOutcome:
    handled: bool
    detail: str
    sale: SaleEvent | None = None


@dataclass
class AgentTriage:
    """Escalation handler for what the deterministic path could not do."""

    inventory: InventoryService
    model: Any = None  # a smolagents model, or None
    #: Ceiling on model calls for the lifetime of this triage object. A mailbox
    #: full of junk would otherwise escalate every message, every run, and spend
    #: money on it indefinitely.
    max_escalations: int = 10
    escalations: list[str] = field(default_factory=list)

    @property
    def available(self) -> bool:
        return self.model is not None and not self.exhausted

    @property
    def exhausted(self) -> bool:
        return len(self.escalations) >= self.max_escalations

    def _note(self, detail: str) -> bool:
        """Record an escalation. False means the budget is already spent."""
        if self.exhausted:
            return False
        self.escalations.append(detail)
        return True

    # -- unparsed emails ---------------------------------------------------
    def parse_unrecognised_email(self, message: InboundEmail) -> ParseResult:
        """Last-resort extraction from an email no parser claimed."""
        if not self._note(f"unparsed email: {message.subject!r}"):
            return ParseResult(None, f"escalation budget of {self.max_escalations} spent")
        if self.model is None:
            return ParseResult(None, "no model configured")

        prompt = EXTRACTION_PROMPT % {
            "sender": message.sender,
            "subject": message.subject,
            # Truncated: a sale notification's useful content is at the top, and
            # a long HTML footer is cost without signal.
            "body": message.body[:4000],
        }
        try:
            raw = self._complete(prompt)
            payload = json.loads(_strip_fences(raw))
        except Exception as exc:  # noqa: BLE001
            # Broad on purpose: this is a network call to a model that may
            # return anything at all. Every failure mode here means the same
            # thing to the caller, which is that the email still needs a human.
            return ParseResult(None, f"model extraction failed: {exc}")

        if payload.get("not_a_sale"):
            return ParseResult(None, "model judged this not to be a sale notification")

        try:
            sale = SaleEvent(
                marketplace=Marketplace(payload.get("marketplace", "manual")),
                card_name=str(payload["card_name"]),
                price_gbp=float(payload["price_gbp"]),
                quantity=int(payload.get("quantity", 1)),
                order_reference=str(payload.get("order_reference", "")),
                buyer=str(payload.get("buyer", "")),
                postage_gbp=float(payload.get("postage_gbp", 0) or 0),
                raw_subject=message.subject,
            )
        except (KeyError, TypeError, ValueError) as exc:
            return ParseResult(None, f"model returned unusable fields: {exc}")

        # A model-extracted sale is never applied silently - it is recorded and
        # surfaced, because the cost of a hallucinated order is a wrong stock
        # count that nobody notices.
        return ParseResult(sale, "extracted by model - verify before trusting")

    # -- ambiguous title matches -------------------------------------------
    def resolve_ambiguous_title(self, title: str, candidates: list[dict]) -> TriageOutcome:
        """Pick between inventory items a title matches equally well."""
        if not self._note(f"ambiguous title: {title!r}"):
            return TriageOutcome(False, f"escalation budget of {self.max_escalations} spent")
        if self.model is None:
            return TriageOutcome(False, "ambiguous match, no model configured - needs a human")

        options = "\n".join(
            f"{i}. {c.get('card_name')} [{c.get('set_code')}] "
            f"condition={c.get('condition')} qty={c.get('quantity')}"
            for i, c in enumerate(candidates)
        )
        prompt = (
            "A card sold with this marketplace title:\n"
            f"  {title}\n\n"
            "Which inventory item is it? Reply with only the number, or NONE.\n\n"
            f"{options}\n"
        )
        try:
            answer = self._complete(prompt).strip()
        except Exception as exc:  # noqa: BLE001
            # As above: any failure leaves the match unresolved, and an
            # unresolved match is reported rather than guessed at.
            return TriageOutcome(False, f"model call failed: {exc}")

        if answer.upper().startswith("NONE"):
            return TriageOutcome(False, "model could not identify the item")
        try:
            chosen = candidates[int(answer.split()[0].rstrip(".")) ]
        except (ValueError, IndexError):
            return TriageOutcome(False, f"model gave an unusable answer: {answer!r}")
        return TriageOutcome(True, f"model chose {chosen.get('card_name')}")

    def _complete(self, prompt: str) -> str:
        """Call the model. smolagents models are callables over message dicts."""
        response = self.model([{"role": "user", "content": prompt}])
        return getattr(response, "content", str(response))


def _strip_fences(text: str) -> str:
    """Models wrap JSON in ``` fences regardless of instructions."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[-1]
        cleaned = cleaned.rsplit("```", 1)[0]
    return cleaned.strip()


def build_agent(inventory: InventoryService, model: Any, providers: list | None = None):
    """A smolagents CodeAgent wired to the inventory tools.

    For interactive questions - "what is my Dark Magician worth and how many do
    I have" - rather than for the automated pipeline, which stays deterministic.
    """
    from smolagents import CodeAgent

    from .tools import build_smolagent_tools

    return CodeAgent(tools=build_smolagent_tools(inventory, providers), model=model)
