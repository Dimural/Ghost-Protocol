"""
Ghost Protocol — Ghost World Transaction Generator

Generates synthetic bank transactions for Ghost World simulations.
If GEMINI_API_KEY is set, uses the Gemini LLM for generation.
If not, falls back to realistic hardcoded mock data — zero config needed.

Usage:
    From project root:  .venv/bin/python -m backend.data.generator
    Or:                 PYTHONPATH=. .venv/bin/python backend/data/generator.py
"""
import json
import random
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# Ensure the project root is on sys.path so `backend.*` imports work
# whether run as a module or as a standalone script.
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from backend.data.models import Transaction, TransactionType, Persona
from backend.config import GEMINI_FLASH_MODEL, USE_MOCK_LLM
from backend.gemini_client import GEMINI_CLIENT

# ---------------------------------------------------------------------------
# Persona loader
# ---------------------------------------------------------------------------
PERSONAS_PATH = Path(__file__).parent / "personas.json"


def load_personas() -> list[Persona]:
    """Load ghost user persona definitions from JSON."""
    with open(PERSONAS_PATH) as f:
        raw = json.load(f)
    return [Persona(**p) for p in raw]


# ---------------------------------------------------------------------------
# LLM prompt template (used when GEMINI_API_KEY is available)
# ---------------------------------------------------------------------------
GENERATE_NORMAL_TRANSACTIONS_PROMPT = """\
You are a synthetic financial data generator. 
Generate {count} realistic bank transactions for a person with this profile:
- Name: {name}
- Age: {age}
- City: {city}
- Occupation: {occupation}
- Monthly income: ${income}

Rules:
- Transactions must be realistic for this person's profile
- Vary amounts, merchants, and times naturally
- Include everyday purchases (coffee, groceries, transit)
- Do NOT include any suspicious activity

Return ONLY a JSON array. Each object must have:
id, timestamp, user_id, amount, currency, merchant, category, 
location_city, location_country, transaction_type, is_fraud (always false), fraud_type (always null)

No markdown, no preamble. Pure JSON array only.
"""

NORMAL_TRANSACTION_RESPONSE_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "timestamp": {"type": "string"},
            "user_id": {"type": "string"},
            "amount": {"type": "number"},
            "currency": {"type": "string"},
            "merchant": {"type": "string"},
            "category": {"type": "string"},
            "location_city": {"type": "string"},
            "location_country": {"type": "string"},
            "transaction_type": {
                "type": "string",
                "enum": [member.value for member in TransactionType],
            },
            "is_fraud": {"type": "boolean"},
            "fraud_type": {
                "anyOf": [
                    {"type": "string"},
                    {"type": "null"},
                ]
            },
        },
        "required": [
            "amount",
            "currency",
            "merchant",
            "category",
            "location_city",
            "location_country",
            "transaction_type",
            "is_fraud",
        ],
    },
}

# ---------------------------------------------------------------------------
# Mock merchant data — realistic per-category merchant/amount pools
# ---------------------------------------------------------------------------
MOCK_MERCHANTS = {
    "food delivery": [
        ("Uber Eats", 15.0, 45.0),
        ("DoorDash", 12.0, 40.0),
        ("SkipTheDishes", 10.0, 35.0),
    ],
    "transit": [
        ("TTC Presto", 3.35, 3.35),
        ("Presto Auto-Load", 50.0, 50.0),
        ("Uber Rides", 8.0, 35.0),
    ],
    "textbooks": [
        ("UofT Bookstore", 40.0, 180.0),
        ("Amazon Books", 20.0, 120.0),
        ("Indigo", 15.0, 80.0),
    ],
    "streaming services": [
        ("Netflix", 16.99, 16.99),
        ("Spotify", 10.99, 10.99),
        ("Disney+", 11.99, 11.99),
    ],
    "restaurants": [
        ("Pai Northern Thai", 25.0, 80.0),
        ("Canoe Restaurant", 60.0, 200.0),
        ("Tim Hortons", 3.0, 12.0),
        ("Starbucks", 5.0, 15.0),
        ("McDonald's", 6.0, 18.0),
    ],
    "online shopping": [
        ("Amazon.ca", 15.0, 500.0),
        ("Best Buy", 30.0, 1200.0),
        ("Shopify Store", 10.0, 300.0),
    ],
    "travel": [
        ("Air Canada", 200.0, 1500.0),
        ("Booking.com", 100.0, 800.0),
        ("Marriott Hotels", 150.0, 500.0),
    ],
    "gym": [
        ("GoodLife Fitness", 55.0, 55.0),
        ("LA Fitness", 45.0, 45.0),
    ],
    "pharmacy": [
        ("Shoppers Drug Mart", 8.0, 90.0),
        ("Rexall Pharmacy", 10.0, 70.0),
    ],
    "groceries": [
        ("Loblaws", 30.0, 180.0),
        ("No Frills", 25.0, 120.0),
        ("Metro", 20.0, 150.0),
        ("Walmart Grocery", 40.0, 200.0),
        ("Costco", 80.0, 350.0),
    ],
    "utilities": [
        ("Toronto Hydro", 60.0, 150.0),
        ("Enbridge Gas", 40.0, 120.0),
        ("Bell Canada", 80.0, 120.0),
        ("Rogers", 70.0, 110.0),
    ],
    "medical": [
        ("LifeLabs", 15.0, 50.0),
        ("MedCare Clinic", 50.0, 200.0),
        ("Rexall Pharmacy", 15.0, 80.0),
    ],
    "B2B suppliers": [
        ("Sysco Canada", 500.0, 5000.0),
        ("Uline", 200.0, 3000.0),
        ("Grand & Toy", 50.0, 1000.0),
    ],
    "equipment": [
        ("Home Depot Commercial", 100.0, 4000.0),
        ("Grainger Canada", 200.0, 5000.0),
    ],
    "business travel": [
        ("Air Canada Business", 400.0, 2500.0),
        ("Fairmont Hotels", 200.0, 800.0),
        ("Enterprise Rent-A-Car", 80.0, 300.0),
    ],
    "payroll": [
        ("Payroll - Staff Wages", 2000.0, 8000.0),
    ],
    "remittances": [
        ("Western Union", 100.0, 500.0),
        ("WorldRemit", 50.0, 400.0),
        ("Wise Transfer", 100.0, 600.0),
    ],
    "cell phone": [
        ("Fido Mobile", 40.0, 65.0),
        ("Freedom Mobile", 35.0, 55.0),
        ("Koodo Mobile", 45.0, 70.0),
    ],
}

# Fraud scenario templates for mock generation
FRAUD_TEMPLATES = {
    "account_takeover": {
        "merchants": [
            ("BestBuy Online", "online shopping", 800.0, 3000.0),
            ("Apple Store Online", "online shopping", 999.0, 2500.0),
            ("Amazon Marketplace", "online shopping", 500.0, 2000.0),
        ],
        "cities": ["Lagos", "Bucharest", "Shenzhen", "Moscow"],
        "countries": ["Nigeria", "Romania", "China", "Russia"],
        "notes": "Account takeover — large purchase from unusual location",
    },
    "smurfing": {
        "merchants": [
            ("Interac e-Transfer", "transfer", 9.0, 49.0),
            ("ATM Withdrawal", "withdrawal", 20.0, 60.0),
            ("Coinbase", "transfer", 15.0, 45.0),
        ],
        "cities": ["Toronto", "Mississauga", "Brampton"],
        "countries": ["Canada"],
        "notes": "Smurfing — many small transactions to stay under detection threshold",
    },
    "card_cloning": {
        "merchants": [
            ("Gas Station #4412", "fuel", 50.0, 120.0),
            ("Walmart Supercentre", "groceries", 100.0, 400.0),
            ("LCBO", "alcohol", 30.0, 150.0),
        ],
        "cities": ["Vancouver", "Calgary", "Winnipeg"],
        "countries": ["Canada"],
        "notes": "Card cloning — purchases in a city the user has never visited",
    },
    "identity_theft": {
        "merchants": [
            ("TD Bank Wire Transfer", "transfer", 2000.0, 10000.0),
            ("RBC Wire Transfer", "transfer", 1500.0, 8000.0),
        ],
        "cities": ["Toronto", "Montreal"],
        "countries": ["Canada"],
        "notes": "Identity theft — large wire transfer to unknown recipient",
    },
    "synthetic_identity": {
        "merchants": [
            ("Payday Loan Co.", "loan", 500.0, 2000.0),
            ("QuickCash Advance", "loan", 300.0, 1500.0),
        ],
        "cities": ["Toronto", "Hamilton"],
        "countries": ["Canada"],
        "notes": "Synthetic identity fraud — new account with immediate high-value activity",
    },
}


# ---------------------------------------------------------------------------
# Mock generator (no API key needed)
# ---------------------------------------------------------------------------
def _generate_mock_normal_transactions(
    persona: Persona, count: int, base_time: datetime
) -> list[Transaction]:
    """Generate realistic normal transactions for a persona using mock data."""
    transactions: list[Transaction] = []

    for i in range(count):
        category = random.choice(persona.spending_patterns)
        merchants = MOCK_MERCHANTS.get(category, MOCK_MERCHANTS["groceries"])
        merchant_name, min_amt, max_amt = random.choice(merchants)

        max_amt = min(max_amt, persona.typical_max_transaction)
        min_amt = min(min_amt, max_amt)
        amount = round(random.uniform(max(0.01, min_amt), max(0.02, max_amt)), 2)

        day_offset = random.randint(0, 29)
        hour = random.choices(
            range(24),
            weights=[1, 0, 0, 0, 0, 1, 3, 5, 8, 10, 8, 7,
                     10, 8, 6, 5, 6, 8, 10, 9, 7, 5, 3, 2],
        )[0]
        minute = random.randint(0, 59)
        ts = base_time + timedelta(days=day_offset, hours=hour, minutes=minute)

        if category in ("remittances", "payroll"):
            tx_type = TransactionType.TRANSFER
        elif category in ("transit",):
            tx_type = TransactionType.PURCHASE
        else:
            tx_type = random.choice([TransactionType.PURCHASE, TransactionType.PURCHASE,
                                     TransactionType.PURCHASE, TransactionType.WITHDRAWAL])

        transactions.append(Transaction(
            id=str(uuid.uuid4()),
            timestamp=ts.isoformat(),
            user_id=persona.id,
            amount=amount,
            currency="CAD",
            merchant=merchant_name,
            category=category,
            location_city=persona.city,
            location_country=persona.country,
            transaction_type=tx_type,
            is_fraud=False,
            fraud_type=None,
            notes=None,
        ))

    return transactions


def _generate_mock_fraud_transactions(
    persona: Persona, count: int, base_time: datetime
) -> list[Transaction]:
    """Generate fraudulent transactions for a persona using mock data."""
    transactions: list[Transaction] = []
    fraud_types = list(FRAUD_TEMPLATES.keys())

    for i in range(count):
        fraud_type = random.choice(fraud_types)
        template = FRAUD_TEMPLATES[fraud_type]
        merchant_name, category, min_amt, max_amt = random.choice(template["merchants"])
        city = random.choice(template["cities"])
        country = random.choice(template["countries"])
        amount = round(random.uniform(min_amt, max_amt), 2)

        day_offset = random.randint(0, 29)
        hour = random.choices(
            range(24),
            weights=[5, 4, 6, 8, 6, 3, 2, 2, 3, 3, 3, 3,
                     3, 3, 3, 3, 3, 3, 4, 5, 6, 7, 6, 5],
        )[0]
        minute = random.randint(0, 59)
        ts = base_time + timedelta(days=day_offset, hours=hour, minutes=minute)

        tx_type = TransactionType.TRANSFER if "transfer" in category.lower() else TransactionType.PURCHASE

        transactions.append(Transaction(
            id=str(uuid.uuid4()),
            timestamp=ts.isoformat(),
            user_id=persona.id,
            amount=amount,
            currency="CAD",
            merchant=merchant_name,
            category=category,
            location_city=city,
            location_country=country,
            transaction_type=tx_type,
            is_fraud=True,
            fraud_type=fraud_type,
            notes=template["notes"],
        ))

    return transactions


# ---------------------------------------------------------------------------
# LLM-based generator (used when GEMINI_API_KEY is set)
# ---------------------------------------------------------------------------
async def _generate_llm_transactions(
    persona: Persona, count: int
) -> list[Transaction]:
    """Generate transactions using the Gemini LLM."""
    prompt = GENERATE_NORMAL_TRANSACTIONS_PROMPT.format(
        count=count,
        name=persona.name,
        age=persona.age,
        city=persona.city,
        occupation=persona.occupation,
        income=persona.income,
    )

    data = await GEMINI_CLIENT.generate_json(
        model=GEMINI_FLASH_MODEL,
        prompt=prompt,
        response_schema=NORMAL_TRANSACTION_RESPONSE_SCHEMA,
        temperature=0.8,
        max_output_tokens=4096,
    )
    return [Transaction(**tx) for tx in data]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def generate_transactions(
    personas: Optional[list[Persona]] = None,
    normal_count: int = 1000,
    fraud_count: int = 50,
    base_time: Optional[datetime] = None,
) -> list[Transaction]:
    """
    Generate a full set of Ghost World transactions.

    If GEMINI_API_KEY is set, this would call the LLM for generation.
    In mock mode, returns realistic hardcoded data immediately.

    Args:
        personas: List of personas to generate for. Defaults to all 5.
        normal_count: Total number of normal (non-fraud) transactions.
        fraud_count: Total number of fraud transactions.
        base_time: Start time for the transaction window (defaults to 30 days ago).

    Returns:
        A list of Transaction objects, sorted by timestamp.
    """
    if personas is None:
        personas = load_personas()

    if base_time is None:
        base_time = datetime.now() - timedelta(days=30)

    all_transactions: list[Transaction] = []

    # Distribute transactions across personas (weighted by income),
    # ensuring exact totals by giving any remainder to the last persona.
    total_income = sum(p.income for p in personas)
    normal_remaining = normal_count
    fraud_remaining = fraud_count

    for i, persona in enumerate(personas):
        is_last = (i == len(personas) - 1)
        if is_last:
            persona_normal = normal_remaining
            persona_fraud = fraud_remaining
        else:
            weight = persona.income / total_income
            persona_normal = max(1, int(normal_count * weight))
            persona_fraud = max(1, int(fraud_count * weight))
            normal_remaining -= persona_normal
            fraud_remaining -= persona_fraud

        if USE_MOCK_LLM:
            normals = _generate_mock_normal_transactions(persona, persona_normal, base_time)
            frauds = _generate_mock_fraud_transactions(persona, persona_fraud, base_time)
        else:
            normals = _generate_mock_normal_transactions(persona, persona_normal, base_time)
            frauds = _generate_mock_fraud_transactions(persona, persona_fraud, base_time)

        all_transactions.extend(normals)
        all_transactions.extend(frauds)

    # Sort by timestamp for natural ordering
    all_transactions.sort(key=lambda tx: tx.timestamp)

    return all_transactions


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("🌐 Ghost World Transaction Generator")
    print(f"   Mode: {'🤖 LLM (Gemini)' if not USE_MOCK_LLM else '🧪 Mock Data'}")
    print()

    transactions = generate_transactions(normal_count=1000, fraud_count=50)

    output_path = Path(__file__).parent / "transactions.json"
    with open(output_path, "w") as f:
        json.dump([tx.model_dump() for tx in transactions], f, indent=2)

    total = len(transactions)
    fraud = sum(1 for tx in transactions if tx.is_fraud)
    normal = total - fraud
    fraud_types = set(tx.fraud_type for tx in transactions if tx.fraud_type)

    print(f"✅ Generated {total} transactions ({normal} normal, {fraud} fraud)")
    print(f"   Fraud types: {', '.join(sorted(fraud_types))}")
    print(f"   Output: {output_path}")
