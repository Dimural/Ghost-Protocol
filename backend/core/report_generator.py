"""
Ghost Protocol — Post-Game Report Generator

Builds and persists a structured security report for completed matches. Without
`GEMINI_API_KEY` it returns a deterministic professional mock report so the
demo stays fully functional offline.
"""
from __future__ import annotations

import json
import tempfile
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import redis
from pydantic import BaseModel, Field

from backend.config import GEMINI_API_KEY, REDIS_URL, USE_MOCK_LLM
from backend.core.blind_spot_detector import BlindSpot, BlindSpotCategory, BlindSpotDetector
from backend.core.match_state import MATCH_STATE_STORE, MatchState, utc_now
from backend.core.referee import MatchScore, RefereeEngine

RiskRating = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
RuntimeMode = Literal["mock", "gemini"]

REPORT_PROMPT = """
You are a senior cybersecurity analyst reviewing the results of a fraud simulation.

Match Summary:
- Scenario: {scenario_name}
- Criminal Persona: {criminal_persona}
- Rounds: {rounds_completed}
- Final F1 Score: {f1_score}
- Total Fraud Transactions: {total_fraud}
- Caught: {caught} | Missed: {missed}
- Money Defended: ${money_defended} | Money Lost: ${money_lost}

Blind Spots Detected:
{blind_spots}

Write a professional security assessment that includes:
1. Executive Summary (2-3 sentences)
2. Critical Vulnerabilities (list the blind spots in plain English)
3. Attack Pattern Analysis (what strategies the attacker used)
4. Recommended Fixes (3-5 specific, actionable recommendations)
5. Risk Rating: LOW / MEDIUM / HIGH / CRITICAL

Return ONLY JSON with these keys:
- executive_summary
- critical_vulnerabilities
- attack_pattern_analysis
- recommended_fixes
- risk_rating
""".strip()


class MatchReport(BaseModel):
    report_id: str = Field(default_factory=lambda: f"report_{uuid.uuid4().hex[:12]}")
    match_id: str
    generated_at: str = Field(default_factory=utc_now)
    runtime_mode: RuntimeMode
    scenario_name: str
    criminal_persona: str | None = None
    rounds_completed: int
    total_rounds: int
    final_score: MatchScore
    total_fraud_transactions: int
    caught: int
    missed: int
    money_defended: float
    money_lost: float
    blind_spots: list[BlindSpot] = Field(default_factory=list)
    security_gaps: list["SecurityGap"] = Field(default_factory=list)
    executive_summary: str
    critical_vulnerabilities: list[str] = Field(default_factory=list)
    attack_pattern_analysis: str
    recommended_fixes: list[str] = Field(default_factory=list)
    risk_rating: RiskRating


class AnonymizedTransactionExample(BaseModel):
    amount: float
    currency: str
    merchant_label: str
    category: str
    location: str
    transaction_type: str
    fraud_type: str | None = None
    time_window: str


class SecurityGap(BaseModel):
    pattern_name: str
    category: BlindSpotCategory
    description: str
    transactions_exploited: int
    total_money_slipped_through: float
    example_transaction: AnonymizedTransactionExample


class MatchReportStore:
    def __init__(self) -> None:
        self._fallback_path = Path(tempfile.gettempdir()) / "ghost_protocol_reports.json"
        self._redis_client = self._build_redis_client()

    def load(self, match_id: str) -> MatchReport | None:
        raw = self._load_payload(match_id)
        if raw is None:
            return None
        return MatchReport.model_validate(raw)

    def save(self, report: MatchReport) -> None:
        payload = report.model_dump(mode="json")
        if self._redis_client is not None:
            try:
                self._redis_client.set(self._redis_key(report.match_id), json.dumps(payload))
                return
            except redis.RedisError:
                self._redis_client = None

        fallback_payload = self._read_fallback_file()
        fallback_payload[report.match_id] = payload
        self._write_fallback_file(fallback_payload)

    def delete(self, match_id: str) -> None:
        if self._redis_client is not None:
            try:
                self._redis_client.delete(self._redis_key(match_id))
            except redis.RedisError:
                self._redis_client = None

        fallback_payload = self._read_fallback_file()
        if match_id in fallback_payload:
            del fallback_payload[match_id]
            self._write_fallback_file(fallback_payload)

    def _load_payload(self, match_id: str) -> dict[str, Any] | None:
        if self._redis_client is not None:
            try:
                raw = self._redis_client.get(self._redis_key(match_id))
                if raw:
                    return json.loads(raw)
            except redis.RedisError:
                self._redis_client = None

        return self._read_fallback_file().get(match_id)

    def _build_redis_client(self) -> redis.Redis | None:
        if not REDIS_URL:
            return None

        try:
            client = redis.from_url(
                REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=1,
                socket_timeout=1,
            )
            client.ping()
            return client
        except redis.RedisError:
            return None

    def _redis_key(self, match_id: str) -> str:
        return f"report:{match_id}"

    def _read_fallback_file(self) -> dict[str, Any]:
        if not self._fallback_path.exists():
            return {}
        return json.loads(self._fallback_path.read_text())

    def _write_fallback_file(self, payload: dict[str, Any]) -> None:
        self._fallback_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self._fallback_path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(payload, indent=2))
        temp_path.replace(self._fallback_path)


REPORT_STORE = MatchReportStore()


class ReportGenerator:
    """Generate structured match reports with automatic mock fallback."""

    def __init__(
        self,
        *,
        store: MatchReportStore | None = None,
        blind_spot_detector: BlindSpotDetector | None = None,
    ) -> None:
        self._store = store or REPORT_STORE
        self._blind_spot_detector = blind_spot_detector or BlindSpotDetector()
        self._referee = RefereeEngine()

    async def generate_for_match(self, match_id: str, *, force: bool = False) -> MatchReport:
        match_state = MATCH_STATE_STORE.load(match_id)
        if match_state is None:
            raise ValueError(f"Match '{match_id}' was not found.")
        return await self.generate(match_state, force=force)

    async def generate(self, match_state: MatchState, *, force: bool = False) -> MatchReport:
        existing = self._store.load(match_state.match_id)
        if existing is not None and not force:
            return existing

        if match_state.status != "complete":
            raise ValueError(
                f"Match '{match_state.match_id}' must be complete before generating a report."
            )

        report_id = existing.report_id if existing is not None else f"report_{uuid.uuid4().hex[:12]}"
        blind_spots = self._blind_spot_detector.detect(match_state)
        security_gaps = self._build_security_gaps(blind_spots)
        final_score = self._derive_score(match_state)
        summary = self._build_match_summary(match_state, blind_spots, final_score)

        runtime_mode: RuntimeMode = "mock" if USE_MOCK_LLM else "gemini"
        try:
            if USE_MOCK_LLM:
                sections = self._build_mock_sections(match_state, blind_spots, summary)
            else:
                sections = await self._build_gemini_sections(match_state, blind_spots, summary)
        except Exception:
            runtime_mode = "mock"
            sections = self._build_mock_sections(match_state, blind_spots, summary)

        report = MatchReport(
            report_id=report_id,
            match_id=match_state.match_id,
            generated_at=utc_now(),
            runtime_mode=runtime_mode,
            scenario_name=match_state.scenario_name,
            criminal_persona=match_state.criminal_persona,
            rounds_completed=summary["rounds_completed"],
            total_rounds=match_state.total_rounds,
            final_score=final_score,
            total_fraud_transactions=summary["total_fraud_transactions"],
            caught=summary["caught"],
            missed=summary["missed"],
            money_defended=summary["money_defended"],
            money_lost=summary["money_lost"],
            blind_spots=blind_spots,
            security_gaps=security_gaps,
            executive_summary=sections["executive_summary"],
            critical_vulnerabilities=sections["critical_vulnerabilities"],
            attack_pattern_analysis=sections["attack_pattern_analysis"],
            recommended_fixes=sections["recommended_fixes"],
            risk_rating=sections["risk_rating"],
        )
        self._store.save(report)
        return report

    def _build_match_summary(
        self,
        match_state: MatchState,
        blind_spots: list[BlindSpot],
        final_score: MatchScore,
    ) -> dict[str, Any]:
        fraud_transactions = [transaction for transaction in match_state.transactions if transaction.is_fraud]
        fraud_total_amount = round(sum(transaction.amount for transaction in fraud_transactions), 2)
        caught_amount = round(fraud_total_amount - final_score.money_lost, 2)
        rounds_completed = max(match_state.current_round, len(match_state.attack_rounds))

        return {
            "rounds_completed": rounds_completed,
            "total_fraud_transactions": len(fraud_transactions),
            "fraud_total_amount": fraud_total_amount,
            "caught": final_score.true_positives,
            "missed": final_score.false_negatives,
            "money_defended": max(caught_amount, 0.0),
            "money_lost": round(final_score.money_lost, 2),
            "blind_spots": blind_spots,
            "precision": final_score.precision,
            "recall": final_score.recall,
            "f1_score": final_score.f1_score,
        }

    def _build_mock_sections(
        self,
        match_state: MatchState,
        blind_spots: list[BlindSpot],
        summary: dict[str, Any],
    ) -> dict[str, Any]:
        risk_rating = self._determine_risk_rating(match_state, summary)
        executive_summary = self._build_executive_summary(match_state, summary, risk_rating)
        critical_vulnerabilities = self._build_critical_vulnerabilities(blind_spots, summary)
        attack_pattern_analysis = self._build_attack_pattern_analysis(match_state)
        recommended_fixes = self._build_recommendations(blind_spots, summary)

        return {
            "executive_summary": executive_summary,
            "critical_vulnerabilities": critical_vulnerabilities,
            "attack_pattern_analysis": attack_pattern_analysis,
            "recommended_fixes": recommended_fixes,
            "risk_rating": risk_rating,
        }

    async def _build_gemini_sections(
        self,
        match_state: MatchState,
        blind_spots: list[BlindSpot],
        summary: dict[str, Any],
    ) -> dict[str, Any]:
        import google.generativeai as genai

        if not GEMINI_API_KEY:
            raise RuntimeError("Gemini API key is missing; cannot generate the final report.")

        prompt = REPORT_PROMPT.format(
            scenario_name=match_state.scenario_name,
            criminal_persona=match_state.criminal_persona or "unknown",
            rounds_completed=summary["rounds_completed"],
            f1_score=f"{summary['f1_score']:.2f}",
            total_fraud=summary["total_fraud_transactions"],
            caught=summary["caught"],
            missed=summary["missed"],
            money_defended=f"{summary['money_defended']:.2f}",
            money_lost=f"{summary['money_lost']:.2f}",
            blind_spots=self._format_blind_spots_for_prompt(blind_spots),
        )

        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-1.5-pro")
        response = model.generate_content(prompt)
        raw_text = (response.text or "").strip()
        cleaned = self._strip_markdown_fences(raw_text)
        payload = json.loads(cleaned)
        return self._normalize_llm_sections(payload)

    def _determine_risk_rating(self, match_state: MatchState, summary: dict[str, Any]) -> RiskRating:
        missed = summary["missed"]
        money_lost = summary["money_lost"]
        recall = summary["recall"]

        if missed == 0 and money_lost == 0:
            return "LOW"
        if missed >= 5 or money_lost >= 2500 or recall < 0.5:
            return "CRITICAL"
        if missed >= 3 or money_lost >= 1000 or recall < 0.75:
            return "HIGH"
        return "MEDIUM"

    def _build_executive_summary(
        self,
        match_state: MatchState,
        summary: dict[str, Any],
        risk_rating: RiskRating,
    ) -> str:
        return (
            f"Ghost Protocol completed a {summary['rounds_completed']}-round simulation for "
            f"the '{match_state.scenario_name}' scenario against the "
            f"{(match_state.criminal_persona or 'unknown').title()} attacker persona. "
            f"The defender caught {summary['caught']} of {summary['total_fraud_transactions']} fraudulent "
            f"transactions, resulting in a recall of {summary['recall']:.2f} and an F1 score of "
            f"{summary['f1_score']:.2f}. "
            f"Total fraud exposure was ${summary['money_lost']:.2f}, leading to an overall risk rating of "
            f"{risk_rating}."
        )

    def _build_critical_vulnerabilities(
        self,
        blind_spots: list[BlindSpot],
        summary: dict[str, Any],
    ) -> list[str]:
        vulnerabilities: list[str] = []

        for blind_spot in blind_spots[:5]:
            vulnerabilities.append(
                f"{blind_spot.description} ({blind_spot.missed_count} misses, "
                f"${blind_spot.total_amount:.2f} exposed)."
            )

        if vulnerabilities:
            return vulnerabilities

        if summary["missed"] > 0:
            return [
                "Missed fraud was dispersed rather than concentrated into a single repeated pattern, "
                "which suggests the defender still needs stronger cross-transaction correlation."
            ]

        return [
            "No repeated critical blind spots surfaced in this simulation; the defender contained every "
            "fraudulent transaction presented in the match."
        ]

    def _build_security_gaps(self, blind_spots: list[BlindSpot]) -> list[SecurityGap]:
        security_gaps: list[SecurityGap] = []

        for blind_spot in blind_spots:
            security_gaps.append(
                SecurityGap(
                    pattern_name=self._pattern_name_for_blind_spot(blind_spot),
                    category=blind_spot.category,
                    description=blind_spot.description,
                    transactions_exploited=blind_spot.missed_count,
                    total_money_slipped_through=round(blind_spot.total_amount, 2),
                    example_transaction=self._anonymize_example_transaction(
                        blind_spot.example_transaction
                    ),
                )
            )

        return security_gaps

    def _build_attack_pattern_analysis(self, match_state: MatchState) -> str:
        fraud_types = Counter(
            (transaction.fraud_type or "unknown").replace("_", " ")
            for transaction in match_state.transactions
            if transaction.is_fraud
        )
        top_fraud_types = ", ".join(
            f"{fraud_type} ({count})"
            for fraud_type, count in fraud_types.most_common(3)
        ) or "no fraud patterns recorded"

        round_notes = [
            attack_round.strategy_notes
            for attack_round in match_state.attack_rounds
            if attack_round.strategy_notes
        ]
        adaptation_notes = [
            attack_round.adaptation_reasoning
            for attack_round in match_state.attack_rounds
            if attack_round.adaptation_reasoning
        ]

        base = (
            f"The attacker operated as the {(match_state.criminal_persona or 'unknown')} persona across "
            f"{max(match_state.current_round, len(match_state.attack_rounds))} rounds. "
            f"The most common fraud patterns were {top_fraud_types}."
        )

        if round_notes:
            base += f" Initial round behavior: {round_notes[0]}"
        if adaptation_notes:
            base += f" Adaptation observed: {' '.join(adaptation_notes)}"

        return base

    def _build_recommendations(
        self,
        blind_spots: list[BlindSpot],
        summary: dict[str, Any],
    ) -> list[str]:
        recommendations: list[str] = []

        for blind_spot in blind_spots:
            if blind_spot.category == "amount_range":
                recommendations.append(
                    f"Add rolling-threshold and velocity checks for fraud clustered in the "
                    f"{blind_spot.pattern} band rather than treating those amounts as low-risk by default."
                )
            elif blind_spot.category == "time_of_day":
                recommendations.append(
                    f"Increase scrutiny for transactions during {blind_spot.pattern} with step-up "
                    "verification or temporary confidence penalties."
                )
            elif blind_spot.category == "location":
                recommendations.append(
                    f"Introduce location-consistency scoring for activity coming from {blind_spot.pattern}, "
                    "including impossible-travel and first-seen-location logic."
                )
            elif blind_spot.category == "merchant_category":
                recommendations.append(
                    f"Build user-level category baselines and secondary review triggers for "
                    f"{blind_spot.pattern} transactions."
                )
            elif blind_spot.category == "fraud_type":
                recommendations.append(
                    f"Add explicit regression coverage for the {blind_spot.pattern} pattern so future rule "
                    "changes are tested against the same exploit family."
                )

        if summary["missed"] > 0:
            recommendations.append(
                "Combine single-transaction rules with rolling 24-hour correlation so individually small "
                "approvals cannot accumulate into material fraud loss."
            )

        recommendations.extend(
            [
                "Feed completed Ghost Protocol matches into a regression suite so defender changes are "
                "evaluated against historical attacker adaptations before deployment.",
                "Log and review false positives alongside missed fraud so rule tuning improves recall "
                "without introducing unnecessary customer friction.",
            ]
        )

        deduped: list[str] = []
        seen: set[str] = set()
        for recommendation in recommendations:
            if recommendation in seen:
                continue
            seen.add(recommendation)
            deduped.append(recommendation)

        return deduped[:5]

    def _format_blind_spots_for_prompt(self, blind_spots: list[BlindSpot]) -> str:
        if not blind_spots:
            return "No repeated blind spots detected."

        return "\n".join(
            f"- {blind_spot.description} ({blind_spot.missed_count} misses, "
            f"${blind_spot.total_amount:.2f} exposed)"
            for blind_spot in blind_spots
        )

    def _normalize_llm_sections(self, payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("Gemini report response was not a JSON object.")

        executive_summary = str(payload.get("executive_summary", "")).strip()
        attack_pattern_analysis = str(payload.get("attack_pattern_analysis", "")).strip()
        risk_rating = str(payload.get("risk_rating", "")).strip().upper()

        if not executive_summary or not attack_pattern_analysis:
            raise ValueError("Gemini report response omitted required text sections.")
        if risk_rating not in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}:
            raise ValueError("Gemini report response returned an invalid risk rating.")

        critical_vulnerabilities = payload.get("critical_vulnerabilities")
        if isinstance(critical_vulnerabilities, str):
            critical_vulnerabilities = [critical_vulnerabilities]
        if not isinstance(critical_vulnerabilities, list):
            raise ValueError("Gemini report response returned invalid vulnerabilities.")

        recommended_fixes = payload.get("recommended_fixes")
        if isinstance(recommended_fixes, str):
            recommended_fixes = [recommended_fixes]
        if not isinstance(recommended_fixes, list):
            raise ValueError("Gemini report response returned invalid recommendations.")

        return {
            "executive_summary": executive_summary,
            "critical_vulnerabilities": [str(item).strip() for item in critical_vulnerabilities if str(item).strip()],
            "attack_pattern_analysis": attack_pattern_analysis,
            "recommended_fixes": [str(item).strip() for item in recommended_fixes if str(item).strip()],
            "risk_rating": risk_rating,
        }

    def _strip_markdown_fences(self, value: str) -> str:
        cleaned = value.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
            cleaned = cleaned.rsplit("```", 1)[0]
        return cleaned.strip()

    def _pattern_name_for_blind_spot(self, blind_spot: BlindSpot) -> str:
        labels: dict[BlindSpotCategory, str] = {
            "amount_range": "Missed Amount Range",
            "time_of_day": "Missed Time Window",
            "location": "Missed Location",
            "merchant_category": "Missed Merchant Category",
            "fraud_type": "Missed Fraud Type",
        }
        return f"{labels[blind_spot.category]}: {blind_spot.pattern}"

    def _anonymize_example_transaction(self, transaction) -> AnonymizedTransactionExample:
        return AnonymizedTransactionExample(
            amount=round(transaction.amount, 2),
            currency=transaction.currency,
            merchant_label=self._anonymized_merchant_label(transaction.category),
            category=transaction.category,
            location=self._anonymized_location_label(transaction.location_city, transaction.location_country),
            transaction_type=transaction.transaction_type.value,
            fraud_type=transaction.fraud_type,
            time_window=self._time_window_from_timestamp(transaction.timestamp),
        )

    def _anonymized_merchant_label(self, category: str) -> str:
        normalized_category = category.strip().lower() or "general"
        return f"redacted {normalized_category} merchant"

    def _anonymized_location_label(self, city: str, country: str) -> str:
        city = city.strip()
        country = country.strip()
        if city and country:
            return f"{city}, {country}"
        return city or country or "unknown location"

    def _time_window_from_timestamp(self, timestamp: str) -> str:
        normalized = timestamp.replace("Z", "+00:00")
        hour = datetime.fromisoformat(normalized).hour
        if 0 <= hour < 6:
            return "12 AM-5:59 AM"
        if 6 <= hour < 12:
            return "6 AM-11:59 AM"
        if 12 <= hour < 18:
            return "12 PM-5:59 PM"
        return "6 PM-11:59 PM"

    def _derive_score(self, match_state: MatchState) -> MatchScore:
        transactions_by_id = {transaction.id: transaction for transaction in match_state.transactions}
        score = MatchScore()

        for defender_decision in match_state.defender_decisions:
            transaction = transactions_by_id.get(defender_decision.transaction_id)
            if transaction is None:
                continue

            outcome = self._referee.classify_decision(transaction, defender_decision)
            score = score.with_outcome(outcome, transaction.amount)

        return score


REPORT_GENERATOR = ReportGenerator()


def get_match_report(match_id: str) -> MatchReport | None:
    return REPORT_STORE.load(match_id)
