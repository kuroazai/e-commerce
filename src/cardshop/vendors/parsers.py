"""Reading sale notifications out of marketplace emails.

Marketplaces send an email on every sale. Parsing it is the cheapest reliable way
to know you have sold something without polling an API you may not have access
to, and it works identically for any platform that sends mail.

Each parser owns one sender. `parse_email` picks the right one, and anything no
parser claims is returned as unrecognised rather than guessed at - a wrong parse
silently decrements the wrong stock.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from email.message import Message
from typing import Protocol

from ..inventory.models import SaleEvent
from ..market.base import Marketplace

#: An amount, with or without thousands separators: 12.50, 1,250.00, 18.
AMOUNT = r"[0-9][0-9,]*(?:\.[0-9]{1,2})?"
#: eBay UK writes GBP before the number. Cardmarket is a German company and
#: writes it after - "18.00 GBP". Accepting only one order means every price
#: from the other marketplace silently fails to parse, and the sale is dropped.
CURRENCY = r"(?:GBP|\u00a3|EUR|\u20ac)"
MONEY = rf"(?:{CURRENCY}\s*({AMOUNT})|({AMOUNT})\s*{CURRENCY})"
#: Same, as a standalone pattern for stripping a price off the end of a line.
TRAILING_MONEY = re.compile(rf"\s*{MONEY}\s*$", re.IGNORECASE)


def _money(text: str) -> float:
    return float(text.replace(",", ""))


#: Cardmarket settles in euros. Storing a euro figure in a field named
#: `price_gbp` is not a rounding error, it is a wrong number that propagates into
#: every margin and fee calculation downstream. So the currency is detected and
#: converted.
#:
#: This is a static rate, which is a deliberate limitation: a live FX lookup is
#: another network dependency and another failure mode for something that moves
#: a couple of percent a month. Set it from the environment, or pass a parser
#: with its own rate, if you need it exact for accounting.
DEFAULT_EUR_GBP = 0.85


def _amount(match: re.Match[str] | None) -> tuple[float, str] | None:
    """(amount, currency) from a MONEY match, whichever side the symbol was on."""
    if match is None:
        return None
    raw = match.group(1) or match.group(2)
    if not raw:
        return None
    symbol = re.search(CURRENCY, match.group(0), re.IGNORECASE)
    code = (symbol.group(0) if symbol else "GBP").upper()
    currency = "EUR" if code in {"EUR", "\u20ac"} else "GBP"
    return _money(raw), currency


def money_after(labels: tuple[str, ...], text: str) -> float | None:
    """The first amount following any of these labels, ignoring its currency."""
    found = money_after_with_currency(labels, text)
    return found[0] if found else None


def money_after_with_currency(
    labels: tuple[str, ...], text: str
) -> tuple[float, str] | None:
    """The first amount following any of these labels, with its currency."""
    pattern = rf"(?:{'|'.join(labels)})[:\s]*{MONEY}"
    return _amount(re.search(pattern, text, re.IGNORECASE))


def to_gbp(amount: float, currency: str, eur_gbp: float = DEFAULT_EUR_GBP) -> float:
    """Convert to GBP. A GBP amount passes through untouched."""
    if currency == "EUR":
        return round(amount * eur_gbp, 2)
    return round(amount, 2)


@dataclass(frozen=True)
class ParseResult:
    """Either a sale, or an explanation of why not."""

    sale: SaleEvent | None
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.sale is not None


class SaleEmailParser(Protocol):
    marketplace: Marketplace

    def claims(self, sender: str, subject: str) -> bool: ...
    def parse(self, sender: str, subject: str, body: str) -> ParseResult: ...


@dataclass
class EbaySaleParser:
    marketplace: Marketplace = Marketplace.EBAY_UK
    sender_domains: tuple[str, ...] = ("ebay.co.uk", "ebay.com")

    def claims(self, sender: str, subject: str) -> bool:
        sender = (sender or "").lower()
        if not any(domain in sender for domain in self.sender_domains):
            return False
        return "sold" in (subject or "").lower()

    def parse(self, sender: str, subject: str, body: str) -> ParseResult:
        order = re.search(r"(?:Order number|Order|Record number)[:\s]+([0-9\-]{6,})",
                          body, re.IGNORECASE)
        if not order:
            return ParseResult(None, "no order number found")

        price = money_after(("Total", "Item price", "Sold for"), body)
        if price is None:
            return ParseResult(None, "no price found")

        # Prefer the body's "Item:" line over the subject. The subject is prose
        # wrapped around the title - "Your item sold! Dark Magician LOB-005" -
        # and stripping the prose off reliably is not worth it when the body
        # states the title on its own.
        item = re.search(r"^\s*Item(?:\s*title)?[:\s]+(.+)$", body,
                         re.IGNORECASE | re.MULTILINE)
        title = item.group(1).strip() if item else _title_from_subject(subject)
        if not title:
            return ParseResult(None, "no item title found")

        quantity = re.search(r"(?:Quantity|Qty)[:\s]+(\d+)", body, re.IGNORECASE)
        buyer = re.search(r"(?:Buyer|Sold to)[:\s]+([^\r\n]+)", body, re.IGNORECASE)

        return ParseResult(SaleEvent(
            marketplace=self.marketplace,
            card_name=title,
            price_gbp=price,
            quantity=int(quantity.group(1)) if quantity else 1,
            order_reference=order.group(1).strip(),
            buyer=buyer.group(1).strip() if buyer else "",
            postage_gbp=money_after(("Postage", "Shipping"), body) or 0.0,
            raw_subject=subject or "",
        ))


@dataclass
class CardmarketSaleParser:
    marketplace: Marketplace = Marketplace.CARDMARKET
    sender_domains: tuple[str, ...] = ("cardmarket.com",)
    #: EUR to GBP. Cardmarket settles in euros; inventory is costed in pounds.
    eur_gbp: float = DEFAULT_EUR_GBP

    def claims(self, sender: str, subject: str) -> bool:
        sender = (sender or "").lower()
        if not any(domain in sender for domain in self.sender_domains):
            return False
        subject = (subject or "").lower()
        return "order" in subject or "sold" in subject

    def parse(self, sender: str, subject: str, body: str) -> ParseResult:
        order = re.search(r"Order\s*(?:ID|number)?[:\s#]+([0-9]{5,})", body, re.IGNORECASE)
        if not order:
            return ParseResult(None, "no order id found")

        # The article line carries the quantity and name. The price may be on
        # the same line or on its own "Total:" line further down, so it is read
        # separately rather than being required here.
        article = re.search(r"^\s*(\d+)\s*x\s+(\S.*?)\s*$", body, re.MULTILINE)
        if not article:
            return ParseResult(None, "no article line found")

        quantity, name = article.groups()
        found = _amount(TRAILING_MONEY.search(name))
        name = TRAILING_MONEY.sub("", name).strip()
        if found is None:
            found = money_after_with_currency(("Total", "Article price", "Price"), body)
        if found is None:
            return ParseResult(None, "no price found")
        if not name:
            return ParseResult(None, "no article name found")

        amount, currency = found
        buyer = re.search(r"(?:Buyer|Username)[:\s]+([^\r\n]+)", body, re.IGNORECASE)
        postage = money_after_with_currency(("Shipping", "Postage"), body)

        return ParseResult(
            SaleEvent(
                marketplace=self.marketplace,
                card_name=name,
                price_gbp=to_gbp(amount, currency, self.eur_gbp),
                quantity=int(quantity),
                order_reference=order.group(1),
                buyer=buyer.group(1).strip() if buyer else "",
                postage_gbp=(
                    to_gbp(postage[0], postage[1], self.eur_gbp) if postage else 0.0
                ),
                raw_subject=subject or "",
            ),
            f"converted from {currency} at {self.eur_gbp}" if currency == "EUR" else "",
        )


def _title_from_subject(subject: str) -> str:
    """Last resort: strip eBay's prose off the front of a subject line.

    "Your item sold! Dark Magician LOB-005" -> "Dark Magician LOB-005". The
    leading-punctuation strip matters: without it the title keeps the "!" and
    then matches nothing in inventory.
    """
    stripped = re.sub(r"^.*?\bsold\b", "", subject or "", flags=re.IGNORECASE)
    return stripped.lstrip(" :-!,\u2013\u2014").strip() or (subject or "").strip()


DEFAULT_PARSERS: tuple[SaleEmailParser, ...] = (EbaySaleParser(), CardmarketSaleParser())


def parse_email(
    sender: str, subject: str, body: str,
    parsers: tuple[SaleEmailParser, ...] = DEFAULT_PARSERS,
) -> ParseResult:
    """Parse a sale email, or say why it could not be parsed."""
    for parser in parsers:
        if parser.claims(sender, subject):
            return parser.parse(sender, subject, body)
    return ParseResult(None, "no parser recognised this sender")


def message_parts(message: Message) -> tuple[str, str, str]:
    """(sender, subject, body) from an email.message.Message.

    Walks multipart messages for the text/plain part; HTML-only mail comes back
    with an empty body rather than raising, so the caller can escalate it.
    """
    sender = str(message.get("From", ""))
    subject = str(message.get("Subject", ""))

    if not message.is_multipart():
        decoded = _decode(message)
        return sender, subject, decoded if decoded else str(message.get_payload())

    for part in message.walk():
        if part.get_content_type() == "text/plain":
            decoded = _decode(part)
            if decoded:
                return sender, subject, decoded
    return sender, subject, ""


def _decode(part: Message) -> str:
    """The text of one message part, or empty string.

    `get_payload(decode=True)` is documented to return bytes, but for a
    multipart part it returns the Message itself and for a part with no payload
    it returns None. Calling .decode on either raises, which would take down a
    whole mailbox run over one malformed email.

    errors="replace" rather than strict: a mojibake character in a sale
    notification is worth keeping, an exception is not.
    """
    payload = part.get_payload(decode=True)
    if not isinstance(payload, bytes):
        return ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        # The email declared a charset Python does not know.
        return payload.decode("utf-8", errors="replace")
