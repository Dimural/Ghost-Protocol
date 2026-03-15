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
    className: "border-cyan-300/20 bg-cyan-400/10 text-cyan-100",
    dotClassName: "bg-cyan-300",
    Icon: TerminalSquare,
  },
  running: {
    label: "LIVE",
    className: "border-rose-300/20 bg-rose-400/10 text-rose-100",
    dotClassName: "bg-rose-300 animate-pulse",
    Icon: Activity,
  },
  paused: {
    label: "Paused",
    className: "border-amber-300/20 bg-amber-300/10 text-amber-100",
    dotClassName: "bg-amber-300",
    Icon: PauseCircle,
  },
  complete: {
    label: "Complete",
    className: "border-emerald-300/20 bg-emerald-400/10 text-emerald-100",
    dotClassName: "bg-emerald-300",
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
      className={`rounded-[22px] border px-4 py-4 shadow-[inset_0_1px_0_rgba(255,255,255,0.04)] ${className}`}
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
        <div className="rounded-full border border-white/10 bg-slate-950/40 p-2.5 text-slate-100">
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
    <section className="rounded-[28px] border border-white/10 bg-[linear-gradient(160deg,rgba(15,22,41,0.92),rgba(8,12,24,0.94))] p-6 shadow-[0_24px_80px_rgba(3,8,18,0.45)] backdrop-blur">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-xs uppercase tracking-[0.32em] text-cyan-300/80">
            Match Scoreboard
          </p>
          <h2 className="mt-2 text-2xl font-semibold text-slate-50">
            Defender score stream
          </h2>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-300">
            Caught fraud, missed fraud, false alarms, and financial impact are
            pulled directly from the live referee score.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <div className="rounded-full border border-white/10 bg-white/5 px-4 py-2 text-sm font-medium text-slate-100">
            Round {currentRound}/{totalRounds}
          </div>
          <div
            className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-semibold uppercase tracking-[0.18em] ${statusTone.className}`}
          >
            <span className={`h-2.5 w-2.5 rounded-full ${statusTone.dotClassName}`} />
            <StatusIcon className="h-3.5 w-3.5" />
            {statusTone.label}
          </div>
        </div>
      </div>

      <div className="mt-6 rounded-[26px] border border-white/10 bg-[radial-gradient(circle_at_top,rgba(255,59,59,0.1),transparent_38%),linear-gradient(180deg,rgba(5,9,18,0.98),rgba(8,13,24,0.94))] p-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <StatCard
            label="Caught"
            value={String(score.true_positives)}
            hint="True positives"
            className="border-emerald-300/18 bg-emerald-400/[0.07]"
            Icon={ShieldCheck}
          />
          <StatCard
            label="Missed"
            value={String(score.false_negatives)}
            hint="False negatives"
            className="border-rose-300/18 bg-rose-400/[0.08]"
            Icon={ShieldX}
          />
          <StatCard
            label="False Alarm"
            value={String(score.false_positives)}
            hint="Legit traffic blocked"
            className="border-amber-300/18 bg-amber-300/[0.08]"
            Icon={ShieldAlert}
          />
          <StatCard
            label="Lost"
            value={formatCurrency(moneyLost)}
            hint="Fraud value that slipped through"
            className="border-cyan-300/18 bg-cyan-400/[0.07]"
            Icon={CircleDollarSign}
          />
        </div>

        <div className="mt-4 grid gap-4 lg:grid-cols-[1fr_1fr_0.9fr]">
          <div className="rounded-[22px] border border-white/10 bg-white/[0.04] px-4 py-4">
            <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
              F1 Score
            </p>
            <p className="mt-3 text-3xl font-semibold leading-none text-slate-50">
              {formatRatio(f1Score)}
            </p>
          </div>
          <div className="rounded-[22px] border border-white/10 bg-white/[0.04] px-4 py-4">
            <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
              Recall
            </p>
            <p className="mt-3 text-3xl font-semibold leading-none text-slate-50">
              {formatRatio(recall)}
            </p>
          </div>
          <div className="rounded-[22px] border border-white/10 bg-white/[0.04] px-4 py-4">
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
