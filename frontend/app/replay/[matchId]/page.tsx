"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  ArrowLeft,
  ChevronLeft,
  ChevronRight,
  CircleDollarSign,
  Clock3,
  FileText,
  MapPinned,
  Pause,
  Play,
  ShieldAlert,
  ShieldCheck,
  ShieldX,
  Sparkles,
  Swords,
} from "lucide-react";

import {
  getErrorMessage,
  getMatch,
  type MatchStateResponse,
} from "@/lib/api";
import type {
  AttackerAdaptingMessage,
  DefenderDecisionPayload,
  OutcomeLabel,
  TransactionPayload,
} from "@/lib/websocket";

type ReplayPageProps = {
  params: {
    matchId: string;
  };
};

type ReplayStep = {
  id: string;
  position: number;
  round: number;
  transaction: TransactionPayload;
  defenderDecision: DefenderDecisionPayload;
  outcome: OutcomeLabel;
  isCorrect: boolean;
  strategyNote: string;
  roundStrategy: string | null;
  adaptationReasoning: string | null;
  notification: AttackerAdaptingMessage | null;
};

type RoundMetadata = {
  round: number;
  strategyNotes: string | null;
  adaptationReasoning: string | null;
  notification: AttackerAdaptingMessage | null;
};

type OutcomeTone = {
  label: string;
  className: string;
  Icon: typeof ShieldCheck;
};

const AUTOPLAY_INTERVAL_MS = 650;

const OUTCOME_TONES: Record<OutcomeLabel, OutcomeTone> = {
  true_positive: {
    label: "Caught",
    className: "app-chip app-chip-success",
    Icon: ShieldCheck,
  },
  false_positive: {
    label: "False Alarm",
    className: "app-chip app-chip-warning",
    Icon: ShieldAlert,
  },
  false_negative: {
    label: "Missed",
    className: "app-chip app-chip-danger",
    Icon: ShieldX,
  },
  true_negative: {
    label: "Approved Legit",
    className: "app-chip app-chip-accent",
    Icon: ShieldCheck,
  },
};

function classifyOutcome(
  isFraud: boolean,
  decision: "APPROVE" | "DENY",
): OutcomeLabel {
  if (isFraud && decision === "DENY") {
    return "true_positive";
  }
  if (!isFraud && decision === "DENY") {
    return "false_positive";
  }
  if (isFraud && decision === "APPROVE") {
    return "false_negative";
  }
  return "true_negative";
}

function formatAmount(amount: number, currency: string): string {
  return new Intl.NumberFormat("en-CA", {
    style: "currency",
    currency,
    maximumFractionDigits: 2,
  }).format(amount);
}

function formatTimestamp(timestamp: string): string {
  return new Intl.DateTimeFormat("en-CA", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(timestamp));
}

function formatConfidence(confidence: number): string {
  return `${Math.round(confidence * 100)}%`;
}

function buildReplaySteps(match: MatchStateResponse): ReplayStep[] {
  const transactionsById = new Map(
    match.transactions.map((transaction) => [transaction.id, transaction]),
  );
  const roundsByTransactionId = new Map<string, RoundMetadata>();

  for (const round of match.attack_rounds) {
    for (const attack of round.attacks) {
      roundsByTransactionId.set(attack.id, {
        round: round.round,
        strategyNotes: round.strategy_notes || null,
        adaptationReasoning: round.adaptation_reasoning || null,
        notification: round.notification || null,
      });
    }
  }

  return match.defender_decisions.flatMap((decision, index) => {
    const transaction = transactionsById.get(decision.transaction_id);
    if (!transaction) {
      return [];
    }

    const roundMetadata = roundsByTransactionId.get(transaction.id);
    const outcome = classifyOutcome(transaction.is_fraud, decision.decision);
    const strategyNote =
      transaction.notes ||
      roundMetadata?.strategyNotes ||
      roundMetadata?.adaptationReasoning ||
      "No strategy note was captured for this step.";

    return [
      {
        id: transaction.id,
        position: index,
        round: roundMetadata?.round || 1,
        transaction,
        defenderDecision: decision,
        outcome,
        isCorrect:
          outcome === "true_positive" || outcome === "true_negative",
        strategyNote,
        roundStrategy: roundMetadata?.strategyNotes || null,
        adaptationReasoning: roundMetadata?.adaptationReasoning || null,
        notification: roundMetadata?.notification || null,
      },
    ];
  });
}

export default function ReplayPage({ params }: ReplayPageProps) {
  const matchId = params.matchId;
  const [match, setMatch] = useState<MatchStateResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [currentStepIndex, setCurrentStepIndex] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);

  useEffect(() => {
    let isActive = true;

    async function loadMatch() {
      setIsLoading(true);
      setErrorMessage(null);

      try {
        const nextMatch = await getMatch(matchId);
        if (!isActive) {
          return;
        }

        setMatch(nextMatch);
        setCurrentStepIndex(0);
      } catch (error) {
        if (!isActive) {
          return;
        }

        setErrorMessage(getErrorMessage(error));
      } finally {
        if (isActive) {
          setIsLoading(false);
        }
      }
    }

    loadMatch();

    return () => {
      isActive = false;
    };
  }, [matchId]);

  const replaySteps = match ? buildReplaySteps(match) : [];
  const currentStep = replaySteps[currentStepIndex] || null;
  const progressPercent =
    replaySteps.length === 0
      ? 0
      : ((currentStepIndex + 1) / replaySteps.length) * 100;

  useEffect(() => {
    if (!isPlaying || replaySteps.length === 0) {
      return;
    }

    const timer = window.setInterval(() => {
      setCurrentStepIndex((currentIndex) => {
        if (currentIndex >= replaySteps.length - 1) {
          window.clearInterval(timer);
          setIsPlaying(false);
          return currentIndex;
        }

        return currentIndex + 1;
      });
    }, AUTOPLAY_INTERVAL_MS);

    return () => {
      window.clearInterval(timer);
    };
  }, [isPlaying, replaySteps.length]);

  if (isLoading) {
    return (
      <main className="app-page">
        <div className="mx-auto max-w-6xl">
          <div className="app-panel p-8 text-slate-200">
            Loading replay for match {matchId}...
          </div>
        </div>
      </main>
    );
  }

  if (errorMessage || !match) {
    return (
      <main className="app-page">
        <div className="mx-auto max-w-4xl">
          <div className="app-panel p-8">
            <div className="flex items-center gap-3 text-rose-100">
              <ShieldAlert className="h-6 w-6" />
              <h1 className="text-2xl font-semibold">Replay unavailable</h1>
            </div>
            <p className="mt-4 text-sm leading-6 text-rose-50/90">
              {errorMessage || "This replay could not be loaded."}
            </p>
            <Link
              href="/"
              className="app-button app-button-danger mt-6"
            >
              <ArrowLeft className="h-4 w-4" />
              Back to setup
            </Link>
          </div>
        </div>
      </main>
    );
  }

  function handlePreviousStep() {
    setIsPlaying(false);
    setCurrentStepIndex((currentIndex) => Math.max(0, currentIndex - 1));
  }

  function handleNextStep() {
    setIsPlaying(false);
    setCurrentStepIndex((currentIndex) =>
      Math.min(replaySteps.length - 1, currentIndex + 1),
    );
  }

  function handleTogglePlayback() {
    if (replaySteps.length === 0) {
      return;
    }

    if (isPlaying) {
      setIsPlaying(false);
      return;
    }

    if (currentStepIndex >= replaySteps.length - 1) {
      setCurrentStepIndex(0);
    }

    setIsPlaying(true);
  }

  if (!currentStep) {
    return (
      <main className="app-page">
        <div className="mx-auto max-w-6xl space-y-8">
          <section className="app-hero p-8">
            <Link
              href={`/match/${matchId}`}
              className="inline-flex items-center gap-2 text-sm text-slate-400 transition hover:text-slate-200"
            >
              <ArrowLeft className="h-4 w-4" />
              Back to live match
            </Link>
            <p className="app-kicker mt-5">Replay</p>
            <h1 className="mt-2 text-4xl font-semibold text-slate-50">
              Heist replay pending
            </h1>
            <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-400">
              This route is ready, but the defender has not processed any
              transactions for match{" "}
              <span className="font-mono text-slate-200">{matchId}</span> yet.
            </p>
          </section>

          <section className="app-panel p-8">
            <p className="text-sm leading-7 text-slate-300">
              Once Ghost Protocol has at least one defender decision, replay
              mode will let you step forward and backward through the match,
              auto-play at 2x speed, and inspect the criminal agent&apos;s
              strategy note for each transaction.
            </p>
            <div className="mt-6 flex flex-wrap gap-3">
              {match.status === "complete" || match.report_id ? (
                <Link
                  href={`/report/${matchId}`}
                  className="app-button app-button-success"
                >
                  <FileText className="h-4 w-4" />
                  Open post-game report
                </Link>
              ) : null}
              <Link
                href={`/match/${matchId}`}
                className="app-button"
              >
                Return to War Room
              </Link>
              <Link
                href="/"
                className="app-button app-button-secondary"
              >
                Back to setup
              </Link>
            </div>
          </section>
        </div>
      </main>
    );
  }

  const outcomeTone = OUTCOME_TONES[currentStep.outcome];
  const OutcomeIcon = outcomeTone.Icon;

  return (
    <main className="app-page">
      <div className="mx-auto max-w-7xl space-y-8">
        <section className="app-hero p-8">
          <div className="flex flex-wrap items-center justify-between gap-4">
            <div>
              <Link
                href={`/match/${matchId}`}
                className="inline-flex items-center gap-2 text-sm text-slate-400 transition hover:text-slate-200"
              >
                <ArrowLeft className="h-4 w-4" />
                Back to live match
              </Link>
              <p className="app-kicker mt-5">Replay</p>
              <h1 className="mt-2 text-4xl font-semibold text-slate-50">
                Heist replay
              </h1>
              <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-400">
                Step through each processed transaction in order and inspect how
                the attacker changed course over the life of the match.
              </p>
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <div className="app-subpanel px-5 py-4">
                <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
                  Match
                </p>
                <p className="mt-2 text-xl font-semibold text-slate-50">
                  {match.status === "complete" ? "Completed" : "Partial Replay"}
                </p>
              </div>
              <div className="app-subpanel px-5 py-4">
                <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
                  Steps
                </p>
                <p className="mt-2 text-xl font-semibold text-slate-50">
                  {replaySteps.length}
                </p>
              </div>
            </div>
          </div>
          {(match.status === "complete" || match.report_id) && (
            <div className="mt-6">
              <Link
                href={`/report/${matchId}`}
                className="app-button app-button-success"
              >
                <FileText className="h-4 w-4" />
                Open post-game report
              </Link>
            </div>
          )}
        </section>

        <div className="grid gap-8 lg:grid-cols-[1.15fr_0.85fr]">
          <section className="app-panel p-6">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <p className="app-kicker">Replay Controls</p>
                <h2 className="mt-2 text-2xl font-semibold text-slate-50">
                  Step {currentStepIndex + 1} of {replaySteps.length}
                </h2>
                <p className="mt-3 text-sm leading-6 text-slate-400">
                  Use previous and next to scrub the heist manually, or run it
                  at 2x speed for a fast walkthrough.
                </p>
              </div>

              <div className="flex flex-wrap gap-3">
                <button
                  type="button"
                  onClick={handlePreviousStep}
                  disabled={currentStepIndex === 0}
                  className="app-button app-button-secondary disabled:cursor-not-allowed disabled:opacity-40"
                >
                  <ChevronLeft className="h-4 w-4" />
                  Previous
                </button>
                <button
                  type="button"
                  onClick={handleTogglePlayback}
                  className="app-button"
                >
                  {isPlaying ? (
                    <Pause className="h-4 w-4" />
                  ) : (
                    <Play className="h-4 w-4" />
                  )}
                  {isPlaying ? "Pause 2x replay" : "Play at 2x speed"}
                </button>
                <button
                  type="button"
                  onClick={handleNextStep}
                  disabled={currentStepIndex >= replaySteps.length - 1}
                  className="app-button app-button-secondary disabled:cursor-not-allowed disabled:opacity-40"
                >
                  Next
                  <ChevronRight className="h-4 w-4" />
                </button>
              </div>
            </div>

            <div className="app-subpanel-strong mt-6 p-5">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="app-chip">
                  <Sparkles className="h-3.5 w-3.5 text-slate-300" />
                  Step progress
                </div>
                <p className="text-sm font-medium text-slate-300">
                  {Math.round(progressPercent)}%
                </p>
              </div>
              <div className="mt-4 h-3 overflow-hidden rounded-full bg-white/8">
                <div
                  className="h-full rounded-full bg-[linear-gradient(90deg,rgba(154,182,232,0.92),rgba(207,176,122,0.82))] transition-all duration-300"
                  style={{ width: `${progressPercent}%` }}
                />
              </div>
            </div>

            <div className="app-subpanel-strong mt-6 p-6">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div>
                  <div className="flex flex-wrap gap-2">
                    <div className="app-chip app-chip-accent">
                      <Swords className="h-3.5 w-3.5" />
                      Round {currentStep.round}
                    </div>
                    <div className={outcomeTone.className}>
                      <OutcomeIcon className="h-3.5 w-3.5" />
                      {outcomeTone.label}
                    </div>
                  </div>
                  <h3 className="mt-4 text-3xl font-semibold text-slate-50">
                    {formatAmount(
                      currentStep.transaction.amount,
                      currentStep.transaction.currency,
                    )}
                  </h3>
                  <p className="mt-2 text-xl text-slate-200">
                    {currentStep.transaction.merchant}
                  </p>
                  <p className="mt-2 text-sm uppercase tracking-[0.18em] text-slate-400">
                    {currentStep.transaction.category}
                  </p>
                </div>

                <div className="app-subpanel px-4 py-4">
                  <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
                    Defender verdict
                  </p>
                  <p className="mt-2 text-2xl font-semibold text-slate-50">
                    {currentStep.defenderDecision.decision}
                  </p>
                  <p className="mt-2 text-sm text-slate-300">
                    Confidence {formatConfidence(currentStep.defenderDecision.confidence)}
                  </p>
                </div>
              </div>

              <dl className="mt-6 grid gap-4 md:grid-cols-3">
                <div className="app-subpanel px-4 py-4">
                  <dt className="flex items-center gap-2 text-xs uppercase tracking-[0.18em] text-slate-400">
                    <Clock3 className="h-3.5 w-3.5" />
                    Timestamp
                  </dt>
                  <dd className="mt-3 text-sm font-medium text-slate-100">
                    {formatTimestamp(currentStep.transaction.timestamp)}
                  </dd>
                </div>
                <div className="app-subpanel px-4 py-4">
                  <dt className="flex items-center gap-2 text-xs uppercase tracking-[0.18em] text-slate-400">
                    <MapPinned className="h-3.5 w-3.5" />
                    Location
                  </dt>
                  <dd className="mt-3 text-sm font-medium text-slate-100">
                    {currentStep.transaction.location_city},{" "}
                    {currentStep.transaction.location_country}
                  </dd>
                </div>
                <div className="app-subpanel px-4 py-4">
                  <dt className="flex items-center gap-2 text-xs uppercase tracking-[0.18em] text-slate-400">
                    <CircleDollarSign className="h-3.5 w-3.5" />
                    Ground truth
                  </dt>
                  <dd className="mt-3 text-sm font-medium text-slate-100">
                    {currentStep.transaction.is_fraud ? "Fraud" : "Legit"}
                  </dd>
                </div>
              </dl>
            </div>
          </section>

          <div className="space-y-8">
            <section className="app-panel p-6">
              <p className="app-kicker">Criminal strategy</p>
              <h2 className="mt-2 text-2xl font-semibold text-slate-50">
                Why this step exists
              </h2>
              <blockquote className="mt-5 border-l border-white/10 pl-4 text-lg leading-8 text-slate-100">
                <span aria-hidden="true">&ldquo;</span>
                {currentStep.strategyNote}
                <span aria-hidden="true">&rdquo;</span>
              </blockquote>

              {currentStep.roundStrategy &&
              currentStep.roundStrategy !== currentStep.strategyNote ? (
                <div className="app-subpanel mt-5 p-4">
                  <p className="text-xs uppercase tracking-[0.18em] text-slate-400">
                    Round strategy
                  </p>
                  <p className="mt-3 text-sm leading-7 text-slate-300">
                    {currentStep.roundStrategy}
                  </p>
                </div>
              ) : null}

              {currentStep.adaptationReasoning ? (
                <div className="app-subpanel mt-4 p-4">
                  <p className="text-xs uppercase tracking-[0.18em] text-slate-400">
                    Adaptation reasoning
                  </p>
                  <p className="mt-3 text-sm leading-7 text-slate-300">
                    {currentStep.adaptationReasoning}
                  </p>
                </div>
              ) : null}

              {currentStep.notification ? (
                <div className="app-subpanel mt-4 p-4">
                  <p className="text-xs uppercase tracking-[0.18em] text-slate-400">
                    Banner moment
                  </p>
                  <p className="mt-3 text-sm leading-7 text-slate-300">
                    {currentStep.notification.banner_message}
                  </p>
                </div>
              ) : null}
            </section>

            <section className="app-panel p-6">
              <p className="app-kicker">Defender analysis</p>
              <h2 className="mt-2 text-2xl font-semibold text-slate-50">
                Decision context
              </h2>
              <dl className="mt-5 space-y-4">
                <div className="app-subpanel px-4 py-4">
                  <dt className="text-xs uppercase tracking-[0.18em] text-slate-400">
                    Verdict
                  </dt>
                  <dd className="mt-2 text-base font-medium text-slate-100">
                    {currentStep.defenderDecision.decision}
                  </dd>
                </div>
                <div className="app-subpanel px-4 py-4">
                  <dt className="text-xs uppercase tracking-[0.18em] text-slate-400">
                    Confidence
                  </dt>
                  <dd className="mt-2 text-base font-medium text-slate-100">
                    {formatConfidence(currentStep.defenderDecision.confidence)}
                  </dd>
                </div>
                <div className="app-subpanel px-4 py-4">
                  <dt className="text-xs uppercase tracking-[0.18em] text-slate-400">
                    Outcome
                  </dt>
                  <dd className="mt-2 text-base font-medium text-slate-100">
                    {currentStep.isCorrect ? "Correct call" : "Defender mistake"}
                  </dd>
                </div>
                <div className="app-subpanel px-4 py-4">
                  <dt className="text-xs uppercase tracking-[0.18em] text-slate-400">
                    Reason
                  </dt>
                  <dd className="mt-2 text-sm leading-7 text-slate-300">
                    {currentStep.defenderDecision.reason ||
                      "No defender explanation was captured for this step."}
                  </dd>
                </div>
              </dl>
            </section>

            <section className="app-panel p-6">
              <p className="app-kicker">Replay queue</p>
              <h2 className="mt-2 text-2xl font-semibold text-slate-50">
                Jump to any step
              </h2>
              <div className="mt-5 max-h-[22rem] space-y-2 overflow-y-auto pr-1">
                {replaySteps.map((step, index) => {
                  const stepTone = OUTCOME_TONES[step.outcome];
                  const isActive = index === currentStepIndex;

                  return (
                    <button
                      key={step.id}
                      type="button"
                      onClick={() => {
                        setIsPlaying(false);
                        setCurrentStepIndex(index);
                      }}
                      className={`w-full rounded-[18px] border px-4 py-3 text-left transition ${
                        isActive
                          ? "border-[rgba(154,182,232,0.28)] bg-[rgba(154,182,232,0.1)] shadow-[0_0_0_1px_rgba(154,182,232,0.08)]"
                          : "border-white/10 bg-white/[0.03] hover:bg-white/[0.05]"
                      }`}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div>
                          <p className="text-sm font-medium text-slate-100">
                            Step {index + 1} · Round {step.round}
                          </p>
                          <p className="mt-1 text-sm text-slate-400">
                            {step.transaction.merchant} ·{" "}
                            {formatAmount(
                              step.transaction.amount,
                              step.transaction.currency,
                            )}
                          </p>
                        </div>
                        <span className={stepTone.className}>
                          {stepTone.label}
                        </span>
                      </div>
                    </button>
                  );
                })}
              </div>
            </section>
          </div>
        </div>
      </div>
    </main>
  );
}
