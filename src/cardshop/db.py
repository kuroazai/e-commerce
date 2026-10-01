"""Database access, behind a protocol so tests need no MongoDB."""
from __future__ import annotations

from typing import Any, Protocol


class Database(Protocol):
    """The slice of MongoDB this application actually uses."""

    def find_one(self, collection: str, query: dict) -> dict | None: ...
    def find(self, collection: str, query: dict) -> list[dict]: ...
    def insert_one(self, collection: str, document: dict) -> str: ...
    def update_one(self, collection: str, query: dict, update: dict) -> bool: ...


class MongoDatabase:
    """Thin wrapper over pymongo."""

    def __init__(self, uri: str, database: str) -> None:
        from pymongo import MongoClient

        self.client = MongoClient(uri)
        self.db = self.client[database]

    def find_one(self, collection: str, query: dict) -> dict | None:
        return self.db[collection].find_one(query)

    def find(self, collection: str, query: dict) -> list[dict]:
        return list(self.db[collection].find(query))

    def insert_one(self, collection: str, document: dict) -> str:
        return str(self.db[collection].insert_one(document).inserted_id)

    def update_one(self, collection: str, query: dict, update: dict) -> bool:
        return self.db[collection].update_one(query, update).modified_count > 0

    def close(self) -> None:
        self.client.close()


class InMemoryDatabase:
    """A dict-backed Database for tests and local runs.

    Exists so the suite can exercise the real auth flow end to end without a
    running MongoDB. Supports exact-match queries only - which is all this
    application issues.
    """

    def __init__(self) -> None:
        self.collections: dict[str, list[dict]] = {}
        self._next_id = 1

    def _matches(self, document: dict, query: dict) -> bool:
        return all(document.get(key) == value for key, value in query.items())

    def find_one(self, collection: str, query: dict) -> dict | None:
        for document in self.collections.get(collection, []):
            if self._matches(document, query):
                return dict(document)
        return None

    def find(self, collection: str, query: dict) -> list[dict]:
        return [dict(d) for d in self.collections.get(collection, [])
                if self._matches(d, query)]

    def insert_one(self, collection: str, document: dict) -> str:
        stored = dict(document)
        stored["_id"] = str(self._next_id)
        self._next_id += 1
        self.collections.setdefault(collection, []).append(stored)
        return stored["_id"]

    def update_one(self, collection: str, query: dict, update: dict) -> bool:
        changes: dict[str, Any] = update.get("$set", update)
        for document in self.collections.get(collection, []):
            if self._matches(document, query):
                document.update(changes)
                return True
        return False

    def close(self) -> None:
        self.collections.clear()
