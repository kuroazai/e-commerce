"""Marketplace adapters.

Both eBay and Cardmarket forbid scraping and both publish an API, so these are
API clients. Each needs credentials, which come from the environment.

These are structurally complete but have not been exercised against the live
APIs - response shapes are covered by unit tests using recorded payloads, not by
a real call. Verify against a sandbox before trusting prices from them.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import requests

from .base import Condition, Marketplace, PriceQuote

DEFAULT_TIMEOUT = 15.0


class ProviderError(RuntimeError):
    """The marketplace refused the request or returned something unusable."""



#: eBay's OAuth token endpoint. Production; the sandbox host differs.
EBAY_TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
#: The only scope the Browse API needs.
EBAY_SCOPE = "https://api.ebay.com/oauth/api_scope"


def fetch_ebay_token(
    client_id: str,
    client_secret: str,
    *,
    token_url: str = EBAY_TOKEN_URL,
    timeout: float = DEFAULT_TIMEOUT,
    session: requests.Session | None = None,
) -> str:
    """Exchange eBay client credentials for an access token.

    `EbayBrowseProvider` wants a token, not a client id and secret, and a token
    lasts about two hours. Storing one in configuration therefore does not work
    for anything that runs on a schedule - it would be expired by the second
    run. So the credentials are stored and the token is minted when needed.
    """
    if not client_id or not client_secret:
        raise ProviderError("eBay client id and secret are both required")

    http = session or requests
    try:
        response = http.post(
            token_url,
            auth=(client_id, client_secret),
            data={"grant_type": "client_credentials", "scope": EBAY_SCOPE},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=timeout,
        )
        response.raise_for_status()
        token = response.json().get("access_token", "")
    except requests.RequestException as exc:
        raise ProviderError(f"could not get an eBay token: {exc}") from exc
    except ValueError as exc:
        raise ProviderError("eBay returned a token response that was not JSON") from exc

    if not token:
        raise ProviderError("eBay returned no access_token")
    return str(token)

@dataclass
class StaticPriceProvider:
    """Quotes from a fixed list. For tests, offline work and manual overrides."""

    marketplace: Marketplace = Marketplace.MANUAL
    catalogue: dict[str, list[PriceQuote]] = field(default_factory=dict)

    def quotes(self, card_name: str, *, set_code: str = "") -> list[PriceQuote]:
        found = self.catalogue.get(card_name, [])
        if set_code:
            found = [q for q in found if not q.set_code or q.set_code == set_code]
        return list(found)


@dataclass
class EbayBrowseProvider:
    """eBay Browse API.

    Browse returns *active listings*, which are asking prices. Completed sales
    need the Marketplace Insights API, which is access-restricted - so quotes
    from here are marked `sold=False` and `summarise()` will prefer any real sold
    data it has over them.
    """

    access_token: str
    marketplace: Marketplace = Marketplace.EBAY_UK
    base_url: str = "https://api.ebay.com/buy/browse/v1"
    marketplace_id: str = "EBAY_GB"
    timeout: float = DEFAULT_TIMEOUT
    session: requests.Session | None = None

    def __post_init__(self) -> None:
        self.session = self.session or requests.Session()

    def quotes(self, card_name: str, *, set_code: str = "") -> list[PriceQuote]:
        query = f"{card_name} {set_code}".strip()
        try:
            assert self.session is not None
            response = self.session.get(
                f"{self.base_url}/item_summary/search",
                params={"q": query, "limit": "50", "filter": "buyingOptions:{FIXED_PRICE}"},
                headers={
                    "Authorization": f"Bearer {self.access_token}",
                    "X-EBAY-C-MARKETPLACE-ID": self.marketplace_id,
                },
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise ProviderError(f"eBay unreachable: {exc}") from exc

        if response.status_code == 401:
            raise ProviderError("eBay rejected the token")
        if not response.ok:
            raise ProviderError(f"eBay returned {response.status_code}")

        return [
            quote
            for item in response.json().get("itemSummaries", [])
            if (quote := self._to_quote(item, card_name, set_code)) is not None
        ]

    def _to_quote(self, item: dict, card_name: str, set_code: str) -> PriceQuote | None:
        price = item.get("price") or {}
        # Skip anything not already in GBP rather than guessing an FX rate; a
        # wrong conversion is worse than one fewer data point.
        if price.get("currency") != "GBP":
            return None
        try:
            value = float(price["value"])
        except (KeyError, TypeError, ValueError):
            return None
        return PriceQuote(
            marketplace=self.marketplace,
            card_name=card_name,
            price_gbp=value,
            condition=_ebay_condition(item.get("condition", "")),
            set_code=set_code,
            sold=False,
            url=item.get("itemWebUrl", ""),
        )


def _ebay_condition(raw: str) -> Condition:
    """eBay's free-text condition onto Cardmarket's grades.

    eBay has no card-specific grading, so this is coarse by necessity. Anything
    unrecognised becomes GOOD rather than NEAR_MINT - guessing optimistically
    about condition is how you get returns.
    """
    text = (raw or "").strip().lower()
    if text in {"new", "brand new"}:
        return Condition.MINT
    if "very good" in text:
        return Condition.EXCELLENT
    if "good" in text:
        return Condition.GOOD
    if "acceptable" in text:
        return Condition.PLAYED
    if "used" in text:
        return Condition.GOOD
    return Condition.GOOD


@dataclass
class CardmarketProvider:
    """Cardmarket API.

    Cardmarket prices are in EUR, so an FX rate is required rather than assumed;
    `fx_eur_to_gbp` has no default for that reason.
    """

    app_token: str
    fx_eur_to_gbp: float
    marketplace: Marketplace = Marketplace.CARDMARKET
    base_url: str = "https://api.cardmarket.com/ws/v2.0/output.json"
    timeout: float = DEFAULT_TIMEOUT
    session: requests.Session | None = None

    def __post_init__(self) -> None:
        if self.fx_eur_to_gbp <= 0:
            raise ValueError("fx_eur_to_gbp must be positive")
        self.session = self.session or requests.Session()

    def quotes(self, card_name: str, *, set_code: str = "") -> list[PriceQuote]:
        try:
            assert self.session is not None
            response = self.session.get(
                f"{self.base_url}/products/find",
                params={"search": card_name, "exact": "false"},
                headers={"Authorization": self.app_token},
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise ProviderError(f"Cardmarket unreachable: {exc}") from exc
        if not response.ok:
            raise ProviderError(f"Cardmarket returned {response.status_code}")

        quotes = []
        for product in response.json().get("product", []):
            prices = product.get("priceGuide") or {}
            # TREND is Cardmarket's own smoothed estimate and is the most stable
            # single number they publish.
            trend_eur = prices.get("TREND") or prices.get("AVG7")
            if not trend_eur:
                continue
            quotes.append(PriceQuote(
                marketplace=self.marketplace,
                card_name=card_name,
                price_gbp=round(float(trend_eur) * self.fx_eur_to_gbp, 2),
                condition=Condition.NEAR_MINT,
                set_code=product.get("expansion", set_code),
                sold=True,  # TREND is derived from completed sales
                observed=date.today(),
                url=product.get("website", ""),
            ))
        return quotes
