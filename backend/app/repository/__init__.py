"""Persistence layer for the POS MVP.

Exposes the storage-agnostic repository protocol and action types, the in-memory
transactional fake used by tests, and the DynamoDB-backed implementation used in
production. Services depend only on :class:`PosRepository`; the concrete backend
is injected by the API layer (later wave).
"""

from __future__ import annotations

from app.repository.base import (
    CancellationReason,
    DuplicateItem,
    ItemNotFound,
    PosRepository,
    PutAction,
    StockDecrementAction,
    TransactionAction,
    TransactionCancelled,
)
from app.repository.dynamodb import DynamoDBPosRepository
from app.repository.memory import InMemoryPosRepository

__all__ = [
    "CancellationReason",
    "DuplicateItem",
    "ItemNotFound",
    "PosRepository",
    "PutAction",
    "StockDecrementAction",
    "TransactionAction",
    "TransactionCancelled",
    "InMemoryPosRepository",
    "DynamoDBPosRepository",
]
