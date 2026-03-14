#!/usr/bin/env python3
"""
Ghost Protocol — Seed File Generator

CLI script to generate a static transactions.json for demos and testing.
Uses mock data by default; activates Gemini LLM if GEMINI_API_KEY is set.

Usage:
    .venv/bin/python backend/data/generate_seed.py --output backend/data/transactions.json --count 1000 --fraud 50
"""
import argparse
import json
import sys
from pathlib import Path

# Ensure project root is importable
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from backend.config import USE_MOCK_LLM
from backend.data.generator import generate_transactions


def main():
    parser = argparse.ArgumentParser(
        description="Generate Ghost World seed transaction data"
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default="backend/data/transactions.json",
        help="Output file path (default: backend/data/transactions.json)",
    )
    parser.add_argument(
        "--count", "-c",
        type=int,
        default=1000,
        help="Number of normal (non-fraud) transactions (default: 1000)",
    )
    parser.add_argument(
        "--fraud", "-f",
        type=int,
        default=50,
        help="Number of fraud transactions (default: 50)",
    )
    args = parser.parse_args()

    print("🌐 Ghost Protocol — Seed File Generator")
    print(f"   Mode: {'🤖 LLM (Gemini)' if not USE_MOCK_LLM else '🧪 Mock Data'}")
    print(f"   Target: {args.count} normal + {args.fraud} fraud")
    print()

    transactions = generate_transactions(
        normal_count=args.count,
        fraud_count=args.fraud,
    )

    # Write output
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump([tx.model_dump() for tx in transactions], f, indent=2)

    total = len(transactions)
    fraud = sum(1 for tx in transactions if tx.is_fraud)
    normal = total - fraud
    fraud_types = set(tx.fraud_type for tx in transactions if tx.fraud_type)

    print(f"✅ Generated {total} transactions ({normal} normal, {fraud} fraud)")
    print(f"   Fraud types ({len(fraud_types)}): {', '.join(sorted(fraud_types))}")
    print(f"   Output: {output_path.resolve()}")


if __name__ == "__main__":
    main()
