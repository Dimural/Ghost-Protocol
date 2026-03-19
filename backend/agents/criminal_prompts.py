"""
Ghost Protocol — Criminal Agent Prompt Templates

Defines the three attacker personas and prompt templates used by the Criminal Agent.
When GEMINI_API_KEY is present, these prompts are sent to the LLM.
When not, the CriminalAgent class falls back to mock attack generation.

Three Personas:
  1. "The Amateur"       — Impulsive, obvious attacks
  2. "The Patient Insider" — Slow, subtle, calculated
  3. "The Botnet"         — High-volume, automated, distributed
"""

from langchain_core.prompts import ChatPromptTemplate

# ---------------------------------------------------------------------------
# Attacker Persona System Prompts
# ---------------------------------------------------------------------------

AMATEUR_SYSTEM_PROMPT = """\
You are a petty criminal who just stole someone's credit card. 
You are nervous and impulsive. You try obvious things first.
Your attacks: large single purchases, foreign currency, luxury items.
You don't think strategically and often get caught.
"""

PATIENT_SYSTEM_PROMPT = """\
You are a sophisticated fraudster with months of patience.
You "warm up" accounts by making normal transactions for days before striking.
Your attacks: small amounts that grow slowly, transactions that mimic the victim's patterns,
timing attacks around weekends and holidays when monitoring is reduced.
Your goal is to drain $2,000 over 2 weeks without triggering a single alert.
"""

BOTNET_SYSTEM_PROMPT = """\
You are an automated fraud system controlling 50 compromised accounts simultaneously.
You use "smurfing" — splitting large amounts into many small transactions just under detection thresholds.
You exploit multiple accounts at once to distribute the attack signature.
Your attacks: hundreds of micro-transactions (under $10), rapid-fire timing, distributed across multiple merchants.
"""

# Map persona keys to their system prompts
PERSONA_PROMPTS = {
    "amateur": AMATEUR_SYSTEM_PROMPT,
    "patient": PATIENT_SYSTEM_PROMPT,
    "botnet": BOTNET_SYSTEM_PROMPT,
}

# ---------------------------------------------------------------------------
# Attack Generation Prompt (used with any persona)
# ---------------------------------------------------------------------------

ATTACK_GENERATION_PROMPT = """\
You are playing the role above. 

The fraud detection system you are trying to bypass has these known rules:
{known_rules}

The target account belongs to: {persona_description}

Your task: Generate {count} fraudulent transactions that would:
1. Blend in with this user's normal behavior
2. NOT trigger the rules listed above
3. Still extract maximum value

Return ONLY a JSON array of transactions using this schema:
{transaction_schema}

For each transaction, also include a "strategy" field explaining your reasoning.
No markdown. Pure JSON only.
"""

# ---------------------------------------------------------------------------
# Adaptation Prompt (the "wow moment" — evolving attacks)
# ---------------------------------------------------------------------------

ADAPT_PROMPT = """\
You previously attempted these attacks:
{previous_attacks_summary}

The defender caught these transactions (IDs): {caught_ids}
The defender MISSED these transactions (IDs): {missed_ids}

Analysis: The defender seems to be filtering based on: {inferred_pattern}

Now generate {count} NEW attacks that specifically avoid the patterns 
that got you caught, while exploiting the patterns you successfully snuck through.

Return ONLY a JSON array. No markdown.
"""

# ---------------------------------------------------------------------------
# LangChain ChatPromptTemplate Objects
# ---------------------------------------------------------------------------

STRATEGIZE_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", "{system_prompt}"),
        (
            "human",
            "Known defender rules: {known_defender_rules}\n"
            "Caught IDs: {caught_ids}\n"
            "Target persona: {persona_description}\n"
            "Previous attack history:\n{previous_attacks_summary}\n"
            "Defender sensitivity pattern: {inferred_pattern}\n"
            "What is your attack strategy?",
        ),
    ]
)

ATTACK_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", "{system_prompt}"),
        ("human", ATTACK_GENERATION_PROMPT),
    ]
)

ADAPT_ATTACK_PROMPT = ChatPromptTemplate.from_messages(
    [
        ("system", "{system_prompt}"),
        ("human", ADAPT_PROMPT),
    ]
)

# ---------------------------------------------------------------------------
# Transaction schema (provided to LLM for structured output)
# ---------------------------------------------------------------------------

TRANSACTION_SCHEMA = """\
{
  "id": "string (UUID)",
  "timestamp": "string (ISO 8601)",
  "user_id": "string (persona id, e.g. ghost_student)",
  "amount": "float",
  "currency": "CAD",
  "merchant": "string",
  "category": "string",
  "location_city": "string",
  "location_country": "string",
  "transaction_type": "purchase | transfer | withdrawal | deposit",
  "is_fraud": true,
  "fraud_type": "string (e.g. account_takeover, smurfing, card_cloning)",
  "notes": "string (AI reasoning)",
  "strategy": "string (explain why this attack would evade detection)"
}
"""
