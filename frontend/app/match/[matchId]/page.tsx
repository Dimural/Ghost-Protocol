"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import {
  Activity,
  ArrowLeft,
  RadioTower,
  Shield,
  ShieldAlert,
} from "lucide-react";

import { RiskMeter } from "@/components/RiskMeter";
import {
  type FeedConnectionState,
  TransactionFeed,
  type TransactionFeedItem,
} from "@/components/TransactionFeed";
import { getErrorMessage, getMatch, type MatchStateResponse } from "@/lib/api";
import {
  MatchWebSocket,
  type OutcomeLabel,
  type TransactionProcessedMessage,
} from "@/lib/websocket";

type MatchPageProps = {
  params: {
    matchId: string;
  };
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

function buildFeedItemFromEvent(
  event: TransactionProcessedMessage,
  source: "history" | "live",
): TransactionFeedItem {
  return {
    id: event.transaction.id,
    transaction: event.transaction,
    defenderDecision: event.defender_decision,
    isCorrect: event.is_correct,
    outcome: event.outcome,
    source,
  };
}

function buildHistoricalFeed(match: MatchStateResponse): TransactionFeedItem[] {
  const transactionsById = new Map(
    match.transactions.map((transaction) => [transaction.id, transaction]),
  );

  return [...match.defender_decisions]
    .reverse()
    .flatMap((decision) => {
      const transaction = transactionsById.get(decision.transaction_id);
      if (!transaction) {
        return [];
      }

      const outcome = classifyOutcome(transaction.is_fraud, decision.decision);

      return [
        {
          id: transaction.id,
          transaction,
          defenderDecision: decision,
          isCorrect:
            outcome === "true_positive" || outcome === "true_negative",
          outcome,
          source: "history" as const,
        },
      ];
    })
    .slice(0, 50);
}

function formatPersona(persona: string | null | undefined): string {
  if (!persona) {
    return "Unassigned";
  }

  return persona
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function countProcessedFraudTransactions(match: MatchStateResponse): number {
  const transactionsById = new Map(
    match.transactions.map((transaction) => [transaction.id, transaction]),
  );

  return match.defender_decisions.reduce((count, decision) => {
    const transaction = transactionsById.get(decision.transaction_id);
    return transaction?.is_fraud ? count + 1 : count;
  }, 0);
}

export default function MatchPage({ params }: MatchPageProps) {
  const matchId = params.matchId;
  const [match, setMatch] = useState<MatchStateResponse | null>(null);
  const [feedEntries, setFeedEntries] = useState<TransactionFeedItem[]>([]);
  const [processedCount, setProcessedCount] = useState(0);
  const [processedFraudCount, setProcessedFraudCount] = useState(0);
  const [connectionState, setConnectionState] =
    useState<FeedConnectionState>("connecting");
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const seenTransactionIds = useRef<Set<string>>(new Set());

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

        const nextFeedEntries = buildHistoricalFeed(nextMatch);
        seenTransactionIds.current = new Set(
          nextMatch.defender_decisions.map((decision) => decision.transaction_id),
        );
        setMatch(nextMatch);
        setFeedEntries(nextFeedEntries);
        setProcessedCount(nextMatch.defender_decisions.length);
        setProcessedFraudCount(countProcessedFraudTransactions(nextMatch));
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

  useEffect(() => {
    if (errorMessage) {
      setConnectionState("offline");
      return;
    }

    const socket = new MatchWebSocket();
    setConnectionState("connecting");

    const unsubscribeOpen = socket.onOpen(() => {
      setConnectionState("live");
    });

    const unsubscribeError = socket.onError(() => {
      setConnectionState("offline");
    });

    const unsubscribeClose = socket.onClose(() => {
      setConnectionState("offline");
    });

    const unsubscribeProcessed = socket.onTransactionProcessed((event) => {
      const nextItem = buildFeedItemFromEvent(event, "live");
      if (!seenTransactionIds.current.has(nextItem.id)) {
        seenTransactionIds.current.add(nextItem.id);
        setProcessedCount((currentCount) => currentCount + 1);
        if (event.transaction.is_fraud) {
          setProcessedFraudCount((currentCount) => currentCount + 1);
        }
      }

      setFeedEntries((currentEntries) =>
        [nextItem, ...currentEntries.filter((entry) => entry.id !== nextItem.id)]
          .slice(0, 50),
      );
      setMatch((currentMatch) =>
        currentMatch
          ? {
              ...currentMatch,
              transactions: currentMatch.transactions.some(
                (transaction) => transaction.id === event.transaction.id,
              )
                ? currentMatch.transactions
                : [...currentMatch.transactions, event.transaction],
              defender_decisions: currentMatch.defender_decisions.some(
                (decision) =>
                  decision.transaction_id === event.defender_decision.transaction_id,
              )
                ? currentMatch.defender_decisions
                : [...currentMatch.defender_decisions, event.defender_decision],
              score: event.score,
            }
          : currentMatch,
      );
    });

    const unsubscribeMatchComplete = socket.onMatchComplete((event) => {
      setMatch((currentMatch) =>
        currentMatch
          ? {
              ...currentMatch,
              status: "complete",
              score: event.final_score,
            }
          : currentMatch,
      );
    });

    socket.connect(matchId);

    return () => {
      unsubscribeOpen();
      unsubscribeError();
      unsubscribeClose();
      unsubscribeProcessed();
      unsubscribeMatchComplete();
      socket.disconnect();
    };
  }, [errorMessage, matchId]);

  if (isLoading) {
    return (
      <main className="px-6 py-8 sm:px-8 lg:px-12">
        <div className="mx-auto max-w-7xl">
          <div className="rounded-[32px] border border-white/10 bg-[rgba(15,22,41,0.82)] p-8 text-slate-200 shadow-[0_24px_80px_rgba(3,8,18,0.45)]">
            Loading match {matchId}...
          </div>
        </div>
      </main>
    );
  }

  if (errorMessage || !match) {
    return (
      <main className="px-6 py-8 sm:px-8 lg:px-12">
        <div className="mx-auto max-w-4xl">
          <div className="rounded-[32px] border border-rose-300/20 bg-rose-400/10 p-8 shadow-[0_24px_80px_rgba(3,8,18,0.45)]">
            <div className="flex items-center gap-3 text-rose-100">
              <ShieldAlert className="h-6 w-6" />
              <h1 className="text-2xl font-semibold">Match unavailable</h1>
            </div>
            <p className="mt-4 text-sm leading-6 text-rose-50/90">
              {errorMessage || "This match could not be loaded."}
            </p>
            <Link
              href="/"
              className="mt-6 inline-flex items-center gap-2 rounded-full border border-rose-200/20 bg-white/10 px-5 py-2.5 text-sm font-medium text-rose-50 transition hover:bg-white/15"
            >
              <ArrowLeft className="h-4 w-4" />
              Back to setup
            </Link>
          </div>
        </div>
      </main>
    );
  }

  return (
    <main className="px-6 py-8 sm:px-8 lg:px-12">
      <div className="mx-auto max-w-7xl">
        <div className="grid gap-8 lg:grid-cols-[1.12fr_0.88fr]">
          <div className="space-y-8">
            <section className="rounded-[32px] border border-white/10 bg-[linear-gradient(145deg,rgba(15,22,41,0.95),rgba(10,14,26,0.9))] p-8 shadow-[0_24px_80px_rgba(3,8,18,0.45)]">
              <div className="flex flex-wrap items-center justify-between gap-4">
                <div>
                  <Link
                    href="/"
                    className="inline-flex items-center gap-2 text-sm text-slate-400 transition hover:text-slate-200"
                  >
                    <ArrowLeft className="h-4 w-4" />
                    Back to setup
                  </Link>
                  <p className="mt-5 text-xs uppercase tracking-[0.32em] text-cyan-300/80">
                    War Room
                  </p>
                  <h1 className="mt-2 text-4xl font-semibold text-slate-50">
                    {match.scenario_name}
                  </h1>
                  <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-400">
                    Match <span className="font-mono text-slate-200">{matchId}</span>{" "}
                    is streaming into the left-panel feed, and the right-side
                    threat gauge is now sampling missed fraud in real time.
                    Upcoming tasks will add the map and scoreboard layers.
                  </p>
                </div>

                <div className="rounded-[24px] border border-white/10 bg-white/5 px-5 py-4">
                  <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
                    Status
                  </p>
                  <p className="mt-2 text-xl font-semibold capitalize text-slate-50">
                    {match.status}
                  </p>
                </div>
              </div>
            </section>

            <TransactionFeed
              entries={feedEntries}
              processedCount={processedCount}
              connectionState={connectionState}
            />
          </div>

          <div className="space-y-8">
            <RiskMeter
              processedCount={processedCount}
              processedFraudCount={processedFraudCount}
              falseNegatives={match.score.false_negatives}
            />

            <section className="rounded-[28px] border border-white/10 bg-[rgba(15,22,41,0.84)] p-6 shadow-[0_24px_80px_rgba(3,8,18,0.45)] backdrop-blur">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="text-xs uppercase tracking-[0.32em] text-cyan-300/80">
                    Match Summary
                  </p>
                  <h2 className="mt-2 text-2xl font-semibold text-slate-50">
                    Current telemetry
                  </h2>
                </div>
                <div className="rounded-full border border-cyan-300/20 bg-cyan-400/10 p-3 text-cyan-100">
                  <Activity className="h-5 w-5" />
                </div>
              </div>

              <dl className="mt-6 grid gap-4 sm:grid-cols-2">
                <div className="rounded-[22px] border border-white/10 bg-slate-950/40 p-4">
                  <dt className="text-xs uppercase tracking-[0.22em] text-slate-400">
                    Criminal persona
                  </dt>
                  <dd className="mt-2 text-base font-medium text-slate-50">
                    {formatPersona(match.criminal_persona)}
                  </dd>
                </div>
                <div className="rounded-[22px] border border-white/10 bg-slate-950/40 p-4">
                  <dt className="text-xs uppercase tracking-[0.22em] text-slate-400">
                    Round
                  </dt>
                  <dd className="mt-2 text-base font-medium text-slate-50">
                    {match.current_round}/{match.total_rounds}
                  </dd>
                </div>
                <div className="rounded-[22px] border border-white/10 bg-slate-950/40 p-4">
                  <dt className="text-xs uppercase tracking-[0.22em] text-slate-400">
                    Share URL
                  </dt>
                  <dd className="mt-2 break-all font-mono text-sm text-slate-50">
                    {match.share_url || "Pending"}
                  </dd>
                </div>
                <div className="rounded-[22px] border border-white/10 bg-slate-950/40 p-4">
                  <dt className="text-xs uppercase tracking-[0.22em] text-slate-400">
                    Score stream
                  </dt>
                  <dd className="mt-2 text-base font-medium text-slate-50">
                    F1 {(match.score.f1_score || 0).toFixed(2)} · Recall{" "}
                    {(match.score.recall || 0).toFixed(2)}
                  </dd>
                </div>
              </dl>
            </section>

            <section className="rounded-[28px] border border-white/10 bg-[rgba(15,22,41,0.84)] p-6 shadow-[0_24px_80px_rgba(3,8,18,0.45)] backdrop-blur">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="text-xs uppercase tracking-[0.32em] text-cyan-300/80">
                    Feed Legend
                  </p>
                  <h2 className="mt-2 text-2xl font-semibold text-slate-50">
                    What this panel is telling you
                  </h2>
                </div>
                <div className="rounded-full border border-emerald-300/20 bg-emerald-400/10 p-3 text-emerald-100">
                  <Shield className="h-5 w-5" />
                </div>
              </div>

              <div className="mt-6 space-y-3">
                <div className="rounded-[22px] border border-white/10 bg-slate-950/40 p-4 text-sm leading-6 text-slate-300">
                  Red-glow rows are confirmed fraud. Amber-highlighted rows are
                  defender mistakes that deserve immediate attention during the
                  demo.
                </div>
                <div className="rounded-[22px] border border-white/10 bg-slate-950/40 p-4 text-sm leading-6 text-slate-300">
                  The feed is capped at the newest 50 processed transactions so
                  the panel stays readable even once later scenarios begin
                  flooding hundreds of events through the websocket.
                </div>
                <div className="rounded-[22px] border border-white/10 bg-slate-950/40 p-4 text-sm leading-6 text-slate-300">
                  <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-cyan-300/20 bg-cyan-400/10 px-3 py-1 text-xs font-medium uppercase tracking-[0.22em] text-cyan-100">
                    <RadioTower className="h-3.5 w-3.5" />
                    Connection
                  </div>
                  Transaction rows update live from `WS /ws/match/{matchId}`.
                  Broader websocket-driven dashboard wiring is still coming in
                  later Phase 5 tasks.
                </div>
              </div>
            </section>
          </div>
        </div>
      </div>
    </main>
  );
}
