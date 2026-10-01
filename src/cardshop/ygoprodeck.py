"""Client for the YGOPRODeck card API.

The original called `requests.get` with no timeout, so a hung server hung the
request thread forever, and returned `response.json()` without checking the
status - so an error page became a dict the caller then indexed into.
"""
from __future__ import annotations

from typing import Any

import requests

BASE_URL = "https://db.ygoprodeck.com/api/v7"
DEFAULT_TIMEOUT = 10.0


class CardApiError(RuntimeError):
    """The card API refused the request or returned something unusable."""


class YgoProDeckClient:
    def __init__(
        self,
        *,
        base_url: str = BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        session: requests.Session | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = session or requests.Session()

    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict:
        try:
            response = self.session.get(
                f"{self.base_url}/{path}", params=params, timeout=self.timeout
            )
        except requests.RequestException as exc:
            raise CardApiError(f"card API unreachable: {exc}") from exc

        if response.status_code == 400:
            # The API uses 400 for "no card matched", which is not an error the
            # caller should have to distinguish from a malformed request.
            raise CardApiError("no cards matched that query")
        if not response.ok:
            raise CardApiError(f"card API returned {response.status_code}")

        try:
            payload = response.json()
        except ValueError as exc:
            raise CardApiError("card API returned a non-JSON body") from exc
        if "data" not in payload:
            raise CardApiError("card API response had no data")
        return payload

    def card_by_name(self, name: str) -> list[dict]:
        return self._get("cardinfo.php", {"name": name})["data"]

    def cards_by_archetype(self, archetype: str) -> list[dict]:
        return self._get("cardinfo.php", {"archetype": archetype})["data"]

    def card_sets(self) -> list[dict]:
        response = self.session.get(f"{self.base_url}/cardsets.php", timeout=self.timeout)
        if not response.ok:
            raise CardApiError(f"card API returned {response.status_code}")
        return response.json()
