"use client";

import {
  Activity,
  CheckCircle2,
  CircleDollarSign,
  type LucideIcon,
  PauseCircle,
  ShieldAlert,
  ShieldCheck,
  ShieldX,
  TerminalSquare,
} from "lucide-react";

import type { MatchStateResponse } from "@/lib/api";
import type { MatchScorePayload } from "@/lib/websocket";

type ScoreboardProps = {
  score: MatchScorePayload;
  currentRound: number;
  totalRounds: number;
  status: MatchStateResponse["status"];
};

type StatusTone = {
  label: string;
  className: string;
  dotClassName: string;
  Icon: LucideIcon;
};

type StatCardProps = {
  label: string;
  value: string;
  hint: string;
  className: string;
  Icon: LucideIcon;
};

const STATUS_TONES: Record<MatchStateResponse["status"], StatusTone> = {
  setup: {
    label: "Setup",
    className: "landing-pill",
    dotClassName: "bg-white/70",
    Icon: TerminalSquare,
  },
  running: {
    label: "LIVE",
    className: "landing-pill landing-pill-accent",
    dotClassName: "bg-[var(--accent-signal)] animate-pulse",
    Icon: Activity,
  },
  paused: {
    label: "Paused",
    className: "landing-pill",
    dotClassName: "bg-white/70",
    Icon: PauseCircle,
  },
  complete: {
    label: "Complete",
    className: "landing-pill landing-pill-accent",
    dotClassName: "bg-[var(--accent-signal)]",
    Icon: CheckCircle2,
  },
};

function formatCurrency(amount: number): string {
  return new Intl.NumberFormat("en-CA", {
    style: "currency",
    currency: "CAD",
    maximumFractionDigits: 0,
  }).format(amount);
}

function formatRatio(value: number): string {
  return value.toFixed(2);
}

function calculatePrecision(score: MatchScorePayload): number {
  if (typeof score.precision === "number") {
    return score.precision;
  }

  const denominator = score.true_positives + score.false_positives;
  return denominator === 0 ? 0 : score.true_positives / denominator;
}

function calculateRecall(score: MatchScorePayload): number {
  if (typeof score.recall === "number") {
    return score.recall;
  }

  const denominator = score.true_positives + score.false_negatives;
  return denominator === 0 ? 0 : score.true_positives / denominator;
}

function calculateF1Score(score: MatchScorePayload): number {
  if (typeof score.f1_score === "number") {
    return score.f1_score;
  }

  const precision = calculatePrecision(score);
  const recall = calculateRecall(score);
  if (precision === 0 && recall === 0) {
    return 0;
  }

  return (2 * precision * recall) / (precision + recall);
}

function calculateMoneyLost(score: MatchScorePayload): number {
  if (typeof score.money_lost === "number") {
    return score.money_lost;
  }

  return score.false_negative_amount_total;
}

function StatCard({ label, value, hint, className, Icon }: StatCardProps) {
  return (
    <div
      className={`app-subpanel px-4 py-4 ${className}`}
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
            {label}
          </p>
          <p className="mt-3 text-3xl font-semibold leading-none text-slate-50">
            {value}
          </p>
          <p className="mt-3 text-sm text-slate-300">{hint}</p>
        </div>
        <div className="app-subpanel-strong rounded-full p-2.5 text-slate-100">
          <Icon className="h-5 w-5" />
        </div>
      </div>
    </div>
  );
}

export function Scoreboard({
  score,
  currentRound,
  totalRounds,
  status,
}: ScoreboardProps) {
  const statusTone = STATUS_TONES[status];
  const f1Score = calculateF1Score(score);
  const recall = calculateRecall(score);
  const precision = calculatePrecision(score);
  const moneyLost = calculateMoneyLost(score);
  const StatusIcon = statusTone.Icon;

  return (
    <section className="app-panel p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-xs uppercase tracking-[0.32em] text-slate-500">
            Section Score
          </p>
          <h2 className="mt-2 text-2xl font-semibold text-slate-50">
            Defender score stream
          </h2>
          <p className="mt-3 max-w-2xl text-sm leading-7 text-slate-300">
            A live read of catches, misses, and impact.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <div className="landing-pill">
            Round {currentRound}/{totalRounds}
          </div>
          <div className={statusTone.className}>
            <span className={`h-2.5 w-2.5 rounded-full ${statusTone.dotClassName}`} />
            <StatusIcon className="h-3.5 w-3.5" />
            {statusTone.label}
          </div>
        </div>
      </div>

      <div className="app-subpanel mt-6 p-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <StatCard
            label="Caught"
            value={String(score.true_positives)}
            hint="True positives"
            className="bg-[rgba(255,255,255,0.04)]"
            Icon={ShieldCheck}
          />
          <StatCard
            label="Missed"
            value={String(score.false_negatives)}
            hint="False negatives"
            className="bg-[rgba(255,255,255,0.04)]"
            Icon={ShieldX}
          />
          <StatCard
            label="False Alarm"
            value={String(score.false_positives)}
            hint="Legit traffic blocked"
            className="bg-[rgba(255,255,255,0.04)]"
            Icon={ShieldAlert}
          />
          <StatCard
            label="Lost"
            value={formatCurrency(moneyLost)}
            hint="Fraud value that slipped through"
            className="bg-[rgba(255,255,255,0.04)]"
            Icon={CircleDollarSign}
          />
        </div>

        <div className="mt-4 grid gap-4 lg:grid-cols-[1fr_1fr_0.9fr]">
          <div className="app-subpanel px-4 py-4">
            <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
              F1 Score
            </p>
            <p className="mt-3 text-3xl font-semibold leading-none text-slate-50">
              {formatRatio(f1Score)}
            </p>
          </div>
          <div className="app-subpanel px-4 py-4">
            <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
              Recall
            </p>
            <p className="mt-3 text-3xl font-semibold leading-none text-slate-50">
              {formatRatio(recall)}
            </p>
          </div>
          <div className="app-subpanel px-4 py-4">
            <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
              Precision
            </p>
            <p className="mt-3 text-3xl font-semibold leading-none text-slate-50">
              {formatRatio(precision)}
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
