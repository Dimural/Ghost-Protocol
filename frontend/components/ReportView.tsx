"use client";

import Link from "next/link";
import {
  ArrowLeft,
  Download,
  FileJson,
  FileText,
  Gauge,
  Radar,
  ShieldAlert,
  ShieldCheck,
  ShieldX,
  Sparkles,
  TriangleAlert,
  Waypoints,
} from "lucide-react";

import type {
  MatchReportResponse,
  MatchStateResponse,
  RecommendationResponse,
  SecurityGapResponse,
} from "@/lib/api";

type ReportViewProps = {
  matchId: string;
  match: MatchStateResponse;
  report: MatchReportResponse;
  jsonExportUrl: string;
  pdfExportUrl: string;
};

type SummaryCard = {
  label: string;
  value: string;
  tone: string;
  Icon: typeof ShieldCheck;
};

type RiskTone = {
  accent: string;
  chipClassName: string;
  ringClassName: string;
};

type PriorityTone = {
  className: string;
};

const RISK_TONES: Record<MatchReportResponse["risk_rating"], RiskTone> = {
  LOW: {
    accent: "#8fc7ad",
    chipClassName: "app-chip app-chip-success",
    ringClassName: "shadow-[0_20px_48px_rgba(0,0,0,0.22)]",
  },
  MEDIUM: {
    accent: "#c7b07a",
    chipClassName: "app-chip app-chip-warning",
    ringClassName: "shadow-[0_20px_48px_rgba(0,0,0,0.22)]",
  },
  HIGH: {
    accent: "#c98c63",
    chipClassName: "app-chip app-chip-warning",
    ringClassName: "shadow-[0_20px_48px_rgba(0,0,0,0.22)]",
  },
  CRITICAL: {
    accent: "#db8a8a",
    chipClassName: "app-chip app-chip-danger",
    ringClassName: "shadow-[0_20px_48px_rgba(0,0,0,0.22)]",
  },
};

const PRIORITY_TONES: Record<RecommendationResponse["priority"], PriorityTone> =
  {
    HIGH: {
      className: "app-chip app-chip-danger",
    },
    MEDIUM: {
      className: "app-chip app-chip-warning",
    },
    LOW: {
      className: "app-chip app-chip-accent",
    },
  };

function formatMoney(amount: number, currency = "CAD"): string {
  return new Intl.NumberFormat("en-CA", {
    style: "currency",
    currency,
    maximumFractionDigits: 2,
  }).format(amount);
}

function formatPercent(value: number): string {
  return `${Math.round(value * 100)}%`;
}

function formatDateTime(value: string): string {
  return new Intl.DateTimeFormat("en-CA", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  }).format(new Date(value));
}

function buildSummaryCards(report: MatchReportResponse): SummaryCard[] {
  return [
    {
      label: "Caught",
      value: String(report.caught),
      tone: "app-chip app-chip-success",
      Icon: ShieldCheck,
    },
    {
      label: "Missed",
      value: String(report.missed),
      tone: "app-chip app-chip-danger",
      Icon: ShieldX,
    },
    {
      label: "False Alarms",
      value: String(report.final_score.false_positives),
      tone: "app-chip app-chip-warning",
      Icon: TriangleAlert,
    },
    {
      label: "F1 Score",
      value: (report.final_score.f1_score ?? 0).toFixed(2),
      tone: "app-chip app-chip-accent",
      Icon: Gauge,
    },
    {
      label: "Money Defended",
      value: formatMoney(report.money_defended),
      tone: "app-chip app-chip-success",
      Icon: ShieldCheck,
    },
    {
      label: "Money Lost",
      value: formatMoney(report.money_lost),
      tone: "app-chip app-chip-danger",
      Icon: ShieldAlert,
    },
  ];
}

function RiskMeterCard({
  report,
  match,
}: {
  report: MatchReportResponse;
  match: MatchStateResponse;
}) {
  const riskPercent =
    report.total_fraud_transactions === 0
      ? 0
      : Math.round((report.missed / report.total_fraud_transactions) * 100);
  const tone = RISK_TONES[report.risk_rating];
  const ringBackground = `conic-gradient(${tone.accent} 0deg ${
    (riskPercent / 100) * 360
  }deg, rgba(255,255,255,0.08) ${(riskPercent / 100) * 360}deg 360deg)`;

  return (
    <section className="app-panel p-6">
      <p className="app-kicker">Risk Meter</p>
      <div className="mt-4 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-2xl font-semibold text-slate-50">
            Post-game threat posture
          </h2>
          <p className="mt-3 max-w-md text-sm leading-7 text-slate-400">
            Final exposure is derived from missed fraud as a share of total
            fraudulent transactions processed in this match.
          </p>
        </div>
        <div className={tone.chipClassName}>
          <ShieldAlert className="h-3.5 w-3.5" />
          {report.risk_rating}
        </div>
      </div>

      <div className="mt-8 grid gap-6 lg:grid-cols-[0.9fr_1.1fr] lg:items-center">
        <div className="flex justify-center">
          <div
            className={`relative flex h-60 w-60 items-center justify-center rounded-full border border-white/10 ${tone.ringClassName}`}
            style={{ background: ringBackground }}
          >
            <div className="absolute inset-[18px] rounded-full border border-white/10 bg-[radial-gradient(circle,rgba(20,24,32,0.98),rgba(10,12,17,0.94))]" />
            <div className="relative z-10 flex flex-col items-center">
              <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
                Threat Level
              </p>
              <p className="mt-3 text-6xl font-semibold text-slate-50">
                {riskPercent}
              </p>
              <p className="mt-1 text-sm uppercase tracking-[0.28em] text-slate-300">
                Percent
              </p>
            </div>
          </div>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <div className="app-subpanel px-5 py-5">
            <p className="text-xs uppercase tracking-[0.2em] text-slate-400">
              Fraud caught
            </p>
            <p className="mt-3 text-3xl font-semibold text-slate-50">
              {report.caught}
            </p>
          </div>
          <div className="app-subpanel px-5 py-5">
            <p className="text-xs uppercase tracking-[0.2em] text-slate-400">
              Fraud missed
            </p>
            <p className="mt-3 text-3xl font-semibold text-slate-50">
              {report.missed}
            </p>
          </div>
          <div className="app-subpanel px-5 py-5">
            <p className="text-xs uppercase tracking-[0.2em] text-slate-400">
              Precision
            </p>
            <p className="mt-3 text-3xl font-semibold text-slate-50">
              {formatPercent(report.final_score.precision ?? 0)}
            </p>
          </div>
          <div className="app-subpanel px-5 py-5">
            <p className="text-xs uppercase tracking-[0.2em] text-slate-400">
              Recall
            </p>
            <p className="mt-3 text-3xl font-semibold text-slate-50">
              {formatPercent(report.final_score.recall ?? 0)}
            </p>
          </div>
        </div>
      </div>

      <div className="app-subpanel mt-6 px-5 py-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-xs uppercase tracking-[0.2em] text-slate-400">
            Match status
          </p>
          <span className="text-sm font-medium capitalize text-slate-200">
            {match.status}
          </span>
        </div>
        <p className="mt-3 text-sm leading-7 text-slate-300">
          {report.rounds_completed} of {report.total_rounds} rounds completed.
          Runtime mode was {report.runtime_mode}, and the report was generated{" "}
          {formatDateTime(report.generated_at)}.
        </p>
      </div>
    </section>
  );
}

function SecurityGapCard({ gap }: { gap: SecurityGapResponse }) {
  return (
    <article className="app-panel p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="app-kicker">
            {gap.category.replaceAll("_", " ")}
          </p>
          <h3 className="mt-2 text-2xl font-semibold text-slate-50">
            {gap.pattern_name}
          </h3>
        </div>
        <div className="app-chip app-chip-danger">
          {formatMoney(gap.total_money_slipped_through)}
        </div>
      </div>

      <p className="mt-4 text-sm leading-7 text-slate-300">{gap.description}</p>

      <div className="mt-5 grid gap-4 md:grid-cols-3">
        <div className="app-subpanel px-4 py-4">
          <p className="text-xs uppercase tracking-[0.18em] text-slate-400">
            Transactions Exploited
          </p>
          <p className="mt-3 text-2xl font-semibold text-slate-50">
            {gap.transactions_exploited}
          </p>
        </div>
        <div className="app-subpanel px-4 py-4">
          <p className="text-xs uppercase tracking-[0.18em] text-slate-400">
            Example Merchant
          </p>
          <p className="mt-3 text-base font-medium text-slate-100">
            {gap.example_transaction.merchant_label}
          </p>
        </div>
        <div className="app-subpanel px-4 py-4">
          <p className="text-xs uppercase tracking-[0.18em] text-slate-400">
            Example Window
          </p>
          <p className="mt-3 text-base font-medium text-slate-100">
            {gap.example_transaction.time_window}
          </p>
        </div>
      </div>

      <div className="app-subpanel mt-5 p-4">
        <p className="text-xs uppercase tracking-[0.18em] text-slate-400">
          Anonymized example
        </p>
        <p className="mt-3 text-sm leading-7 text-slate-300">
          {formatMoney(
            gap.example_transaction.amount,
            gap.example_transaction.currency,
          )}{" "}
          at{" "}
          {gap.example_transaction.merchant_label} in{" "}
          {gap.example_transaction.location} via{" "}
          {gap.example_transaction.transaction_type}. Fraud type:{" "}
          {gap.example_transaction.fraud_type || "unlabeled"}.
        </p>
      </div>
    </article>
  );
}

function RecommendationCard({
  recommendation,
}: {
  recommendation: RecommendationResponse;
}) {
  const tone = PRIORITY_TONES[recommendation.priority];

  return (
    <article className="app-panel p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="app-kicker">
            Recommendation
          </p>
          <h3 className="mt-2 text-2xl font-semibold text-slate-50">
            {recommendation.title}
          </h3>
        </div>
        <div className={tone.className}>
          {recommendation.priority}
        </div>
      </div>

      <div className="app-subpanel mt-5 p-4">
        <p className="text-xs uppercase tracking-[0.18em] text-slate-400">
          Action
        </p>
        <p className="mt-3 text-sm leading-7 text-slate-200">
          {recommendation.action}
        </p>
      </div>

      <div className="app-subpanel mt-4 p-4">
        <p className="text-xs uppercase tracking-[0.18em] text-slate-400">
          Rationale
        </p>
        <p className="mt-3 text-sm leading-7 text-slate-300">
          {recommendation.rationale}
        </p>
      </div>

      {recommendation.code_hint ? (
        <div className="app-subpanel mt-4 p-4">
          <p className="text-xs uppercase tracking-[0.18em] text-slate-400">
            Code Hint
          </p>
          <p className="mt-3 text-sm leading-7 text-slate-300">
            {recommendation.code_hint}
          </p>
        </div>
      ) : null}
    </article>
  );
}

export function ReportView({
  matchId,
  match,
  report,
  jsonExportUrl,
  pdfExportUrl,
}: ReportViewProps) {
  const summaryCards = buildSummaryCards(report);
  const riskTone = RISK_TONES[report.risk_rating];

  return (
    <div className="mx-auto max-w-7xl space-y-8">
      <section className="app-hero p-8">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <Link
              href={`/match/${matchId}`}
              className="inline-flex items-center gap-2 text-sm text-slate-400 transition hover:text-slate-200"
            >
              <ArrowLeft className="h-4 w-4" />
              Back to War Room
            </Link>
            <p className="app-kicker mt-5">Post-Game Report</p>
            <h1 className="mt-2 text-4xl font-semibold text-slate-50">
              {report.scenario_name}
            </h1>
            <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-400">
              Match <span className="font-mono text-slate-200">{matchId}</span>{" "}
              has been analyzed. This dashboard turns the referee score,
              security gaps, and generated recommendations into a concise
              briefing you can hand directly to a defender team.
            </p>
            <div className="mt-5 flex flex-wrap gap-3">
              <Link
                href={`/replay/${matchId}`}
                className="app-button app-button-secondary"
              >
                <Radar className="h-4 w-4" />
                Open Replay
              </Link>
              <a
                href={pdfExportUrl}
                className="app-button"
              >
                <FileText className="h-4 w-4" />
                Export PDF
              </a>
              <a
                href={jsonExportUrl}
                className="app-button app-button-secondary"
              >
                <FileJson className="h-4 w-4" />
                Export JSON
              </a>
            </div>
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <div className="app-subpanel px-5 py-4">
              <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
                Risk Rating
              </p>
              <div className={`mt-3 ${riskTone.chipClassName}`}>
                <ShieldAlert className="h-3.5 w-3.5" />
                {report.risk_rating}
              </div>
            </div>
            <div className="app-subpanel px-5 py-4">
              <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
                Export Ready
              </p>
              <p className="mt-2 text-xl font-semibold text-slate-50">
                PDF + JSON
              </p>
            </div>
            <div className="app-subpanel px-5 py-4">
              <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
                Runtime
              </p>
              <p className="mt-2 text-xl font-semibold capitalize text-slate-50">
                {report.runtime_mode}
              </p>
            </div>
            <div className="app-subpanel px-5 py-4">
              <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
                Generated
              </p>
              <p className="mt-2 text-xl font-semibold text-slate-50">
                {formatDateTime(report.generated_at)}
              </p>
            </div>
          </div>
        </div>
      </section>

      <div className="grid gap-8 lg:grid-cols-[1.02fr_0.98fr]">
        <section className="app-panel p-6">
          <p className="app-kicker">Executive Summary</p>
          <h2 className="mt-2 text-2xl font-semibold text-slate-50">
            Immediate readout
          </h2>
          <p className="mt-5 text-lg leading-8 text-slate-100">
            {report.executive_summary}
          </p>

          <div className="app-subpanel mt-6 p-5">
            <p className="text-xs uppercase tracking-[0.2em] text-slate-400">
              Critical vulnerabilities
            </p>
            {report.critical_vulnerabilities.length > 0 ? (
              <div className="mt-4 space-y-3">
                {report.critical_vulnerabilities.map((item) => (
                  <div
                    key={item}
                    className="app-subpanel px-4 py-3 text-sm leading-7 text-slate-300"
                  >
                    {item}
                  </div>
                ))}
              </div>
            ) : (
              <p className="mt-4 text-sm leading-7 text-slate-300">
                No critical vulnerabilities were identified in this report.
              </p>
            )}
          </div>
        </section>

        <RiskMeterCard match={match} report={report} />
      </div>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {summaryCards.map(({ label, value, tone, Icon }) => (
          <article
            key={label}
            className="app-panel p-5"
          >
            <div className={tone}>
              <Icon className="h-3.5 w-3.5" />
              {label}
            </div>
            <p className="mt-4 text-3xl font-semibold text-slate-50">{value}</p>
          </article>
        ))}
      </section>

      <div className="grid gap-8 lg:grid-cols-[0.92fr_1.08fr]">
        <section className="app-panel p-6">
          <p className="app-kicker">Attack Pattern Analysis</p>
          <h2 className="mt-2 text-2xl font-semibold text-slate-50">
            How the attacker won ground
          </h2>
          <p className="mt-5 text-sm leading-8 text-slate-300">
            {report.attack_pattern_analysis}
          </p>
        </section>

        <section className="app-panel p-6">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div>
              <p className="app-kicker">Report Metadata</p>
              <h2 className="mt-2 text-2xl font-semibold text-slate-50">
                Match context
              </h2>
            </div>
            <div className="app-chip">
              Report {report.report_id}
            </div>
          </div>

          <dl className="mt-5 grid gap-4 sm:grid-cols-2">
            <div className="app-subpanel px-4 py-4">
              <dt className="text-xs uppercase tracking-[0.18em] text-slate-400">
                Criminal Persona
              </dt>
              <dd className="mt-2 text-base font-medium capitalize text-slate-100">
                {report.criminal_persona || "unknown"}
              </dd>
            </div>
            <div className="app-subpanel px-4 py-4">
              <dt className="text-xs uppercase tracking-[0.18em] text-slate-400">
                Total Fraud Transactions
              </dt>
              <dd className="mt-2 text-base font-medium text-slate-100">
                {report.total_fraud_transactions}
              </dd>
            </div>
            <div className="app-subpanel px-4 py-4">
              <dt className="text-xs uppercase tracking-[0.18em] text-slate-400">
                Share URL
              </dt>
              <dd className="mt-2 break-all text-sm font-medium text-slate-100">
                {match.share_url || "Unavailable"}
              </dd>
            </div>
            <div className="app-subpanel px-4 py-4">
              <dt className="text-xs uppercase tracking-[0.18em] text-slate-400">
                Downloads
              </dt>
              <dd className="mt-2 flex flex-wrap gap-2 text-sm font-medium text-slate-100">
                <a
                  href={pdfExportUrl}
                  className="app-button"
                >
                  <Download className="h-3.5 w-3.5" />
                  PDF
                </a>
                <a
                  href={jsonExportUrl}
                  className="app-button app-button-secondary"
                >
                  <Download className="h-3.5 w-3.5" />
                  JSON
                </a>
              </dd>
            </div>
          </dl>
        </section>
      </div>

      <section className="space-y-5">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <p className="app-kicker">Security Gaps</p>
            <h2 className="mt-2 text-3xl font-semibold text-slate-50">
              Where the defender was blind
            </h2>
          </div>
          <div className="app-chip app-chip-warning">
            <Waypoints className="h-3.5 w-3.5" />
            {report.security_gaps.length} gaps detected
          </div>
        </div>

        {report.security_gaps.length > 0 ? (
          <div className="grid gap-6 xl:grid-cols-2">
            {report.security_gaps.map((gap) => (
              <SecurityGapCard key={gap.pattern_name} gap={gap} />
            ))}
          </div>
        ) : (
          <section className="app-panel p-6 text-slate-200">
            No repeated security gaps were detected in this match.
          </section>
        )}
      </section>

      <section className="space-y-5">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <p className="app-kicker">Recommendations</p>
            <h2 className="mt-2 text-3xl font-semibold text-slate-50">
              What the defender should change next
            </h2>
          </div>
          <div className="app-chip app-chip-accent">
            <Sparkles className="h-3.5 w-3.5" />
            {report.recommendations.length} actions generated
          </div>
        </div>

        <div className="grid gap-6 xl:grid-cols-2">
          {report.recommendations.length > 0 ? (
            report.recommendations.map((recommendation) => (
              <RecommendationCard
                key={`${recommendation.priority}-${recommendation.title}`}
                recommendation={recommendation}
              />
            ))
          ) : (
            <section className="app-panel p-6 text-slate-200">
              No recommendations were generated for this match.
            </section>
          )}
        </div>
      </section>
    </div>
  );
}
