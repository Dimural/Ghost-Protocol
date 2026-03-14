"""
Ghost Protocol — Pydantic Data Models
Defines the core data structures used throughout the application.
"""
from pydantic import BaseModel, Field
from typing import Literal, Optional
from enum import Enum
import uuid
from datetime import datetime


class TransactionType(str, Enum):
    PURCHASE = "purchase"
    TRANSFER = "transfer"
    WITHDRAWAL = "withdrawal"
    DEPOSIT = "deposit"


class Transaction(BaseModel):
    """A single financial transaction in the Ghost World."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str  # ISO 8601
    user_id: str
    amount: float
    currency: str = "CAD"
    merchant: str
    category: str
    location_city: str
    location_country: str
    transaction_type: TransactionType
    is_fraud: bool  # Ground truth — hidden from Defender, known to Referee
    fraud_type: Optional[str] = None  # e.g., "smurfing", "account_takeover"
    notes: Optional[str] = None  # AI's reasoning (for report generation)


class DefenderDecision(BaseModel):
    """A Defender's response to a single transaction."""
    transaction_id: str = Field(min_length=1)
    decision: Literal["APPROVE", "DENY"]
    confidence: float = Field(ge=0.0, le=1.0)
    reason: Optional[str] = None


class Persona(BaseModel):
    """A Ghost World user archetype."""
    id: str
    name: str
    age: int
    city: str
    country: str
    occupation: str
    income: float
    spending_patterns: list[str]
    typical_max_transaction: float
