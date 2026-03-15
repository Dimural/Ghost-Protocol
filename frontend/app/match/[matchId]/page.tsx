"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import {
  ArrowLeft,
  Copy,
  ExternalLink,
  KeyRound,
  Lock,
  ShieldAlert,
} from "lucide-react";

import { AdaptationBanner } from "@/components/AdaptationBanner";
import { RiskMeter } from "@/components/RiskMeter";
import { Scoreboard } from "@/components/Scoreboard";
import {
  TransactionFeed,
  type TransactionFeedItem,
} from "@/components/TransactionFeed";
import { TransactionMap } from "@/components/TransactionMap";
import { getErrorMessage, getMatch, type MatchStateResponse } from "@/lib/api";
import {
  copyTextToClipboard,
  getMatchViewMode,
  resolveAbsoluteShareUrl,
  type MatchViewMode,
} from "@/lib/match-access";
import {
  type AttackerAdaptingMessage,
  MatchWebSocket,
  type OutcomeLabel,
  type SocketConnectionState,
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

function countProcessedFraudTransactions(match: MatchStateResponse): number {
  const transactionsById = new Map(
    match.transactions.map((transaction) => [transaction.id, transaction]),
  );

  return match.defender_decisions.reduce((count, decision) => {
    const transaction = transactionsById.get(decision.transaction_id);
    return transaction?.is_fraud ? count + 1 : count;
  }, 0);
}

function resolveDisplayRound(
  match: MatchStateResponse,
  processedCount: number,
): number {
  if (match.status === "complete") {
    return Math.max(match.current_round, match.total_rounds);
  }

  if (match.current_round === 0 && processedCount > 0) {
    return 1;
  }

  return match.current_round;
}

export default function MatchPage({ params }: MatchPageProps) {
  const matchId = params.matchId;
  const [match, setMatch] = useState<MatchStateResponse | null>(null);
  const [feedEntries, setFeedEntries] = useState<TransactionFeedItem[]>([]);
  const [processedCount, setProcessedCount] = useState(0);
  const [processedFraudCount, setProcessedFraudCount] = useState(0);
  const [connectionState, setConnectionState] =
    useState<SocketConnectionState>("connecting");
  const [isLoading, setIsLoading] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [activeBanner, setActiveBanner] =
    useState<AttackerAdaptingMessage | null>(null);
  const [viewMode, setViewMode] = useState<MatchViewMode>("shared");
  const [shareCopyState, setShareCopyState] = useState<
    "idle" | "copied" | "failed"
  >("idle");
  const seenTransactionIds = useRef<Set<string>>(new Set());

  useEffect(() => {
    setViewMode(getMatchViewMode(matchId));
  }, [matchId]);

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
        setActiveBanner(nextMatch.latest_notification || null);
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
      setConnectionState("connecting");
    });

    const unsubscribeClose = socket.onClose((event) => {
      setConnectionState(event.code === 4404 ? "offline" : "connecting");
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
              current_round:
                currentMatch.current_round === 0 ? 1 : currentMatch.current_round,
              score: event.score,
            }
          : currentMatch,
      );
    });

    const unsubscribeAdapting = socket.onAttackerAdapting((event) => {
      setActiveBanner(event);
      setMatch((currentMatch) =>
        currentMatch
          ? {
              ...currentMatch,
              current_round: event.round,
              latest_notification: event,
              status: "running",
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
              current_round: currentMatch.total_rounds,
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
      unsubscribeAdapting();
      unsubscribeMatchComplete();
      socket.disconnect();
    };
  }, [errorMessage, matchId]);

  async function handleCopyShareLink() {
    if (!match?.share_url) {
      return;
    }

    const copied = await copyTextToClipboard(
      resolveAbsoluteShareUrl(match.share_url),
    );
    setShareCopyState(copied ? "copied" : "failed");
  }

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

  const displayRound = resolveDisplayRound(match, processedCount);
  const absoluteShareUrl = match.share_url
    ? resolveAbsoluteShareUrl(match.share_url)
    : null;
  const isOwnerView = viewMode === "owner";

  return (
    <main className="px-6 py-8 sm:px-8 lg:px-12">
      <div className="mx-auto max-w-7xl space-y-8">
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
              <div className="mt-4 flex flex-wrap gap-3">
                <Link
                  href={`/replay/${matchId}`}
                  className="inline-flex items-center gap-2 rounded-full border border-amber-300/20 bg-amber-300/10 px-4 py-2 text-sm font-medium text-amber-100 transition hover:bg-amber-300/15"
                >
                  <ExternalLink className="h-4 w-4" />
                  Open Heist Replay
                </Link>
                {absoluteShareUrl ? (
                  <button
                    type="button"
                    onClick={handleCopyShareLink}
                    className="inline-flex items-center gap-2 rounded-full border border-cyan-300/20 bg-cyan-400/10 px-4 py-2 text-sm font-medium text-cyan-100 transition hover:bg-cyan-400/15"
                  >
                    <Copy className="h-4 w-4" />
                    {shareCopyState === "copied"
                      ? "Share link copied"
                      : shareCopyState === "failed"
                        ? "Copy failed"
                        : "Copy share link"}
                  </button>
                ) : null}
              </div>
              <p className="mt-5 text-xs uppercase tracking-[0.32em] text-cyan-300/80">
                War Room
              </p>
              <h1 className="mt-2 text-4xl font-semibold text-slate-50">
                {match.scenario_name}
              </h1>
              <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-400">
                Match <span className="font-mono text-slate-200">{matchId}</span>{" "}
                is live in the War Room with the transaction feed, threat gauge,
                scoreboard, world map, and attacker-learning banner all driven
                from the same websocket event stream.
              </p>
              <div
                className={`mt-5 inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-semibold uppercase tracking-[0.18em] ${
                  isOwnerView
                    ? "border-emerald-300/20 bg-emerald-400/10 text-emerald-100"
                    : "border-amber-300/20 bg-amber-300/10 text-amber-100"
                }`}
              >
                {isOwnerView ? (
                  <KeyRound className="h-3.5 w-3.5" />
                ) : (
                  <Lock className="h-3.5 w-3.5" />
                )}
                {isOwnerView ? "Owner view" : "Shared read-only view"}
              </div>
              <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-400">
                {isOwnerView
                  ? "This browser launched the match, so it is treated as the owner view."
                  : "This browser did not launch the match. The dashboard remains view-only and safe to share."}
              </p>
            </div>

            <div className="grid gap-3 sm:grid-cols-3">
              <div className="rounded-[24px] border border-white/10 bg-white/5 px-5 py-4">
                <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
                  Match Status
                </p>
                <p className="mt-2 text-xl font-semibold capitalize text-slate-50">
                  {match.status}
                </p>
              </div>
              <div className="rounded-[24px] border border-white/10 bg-white/5 px-5 py-4">
                <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
                  WebSocket
                </p>
                <p className="mt-2 text-xl font-semibold capitalize text-slate-50">
                  {connectionState}
                </p>
              </div>
              <div className="rounded-[24px] border border-white/10 bg-white/5 px-5 py-4">
                <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
                  View Mode
                </p>
                <p className="mt-2 text-xl font-semibold text-slate-50">
                  {isOwnerView ? "Owner" : "Read-only"}
                </p>
              </div>
            </div>
          </div>
        </section>

        {activeBanner ? (
          <AdaptationBanner
            key={`${activeBanner.round}-${activeBanner.created_at}`}
            notification={activeBanner}
            connectionState={connectionState}
            onDismiss={() => setActiveBanner(null)}
          />
        ) : null}

        <div className="grid gap-8 lg:grid-cols-[1.12fr_0.88fr]">
          <div className="space-y-8">
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

            <Scoreboard
              score={match.score}
              currentRound={displayRound}
              totalRounds={match.total_rounds}
              status={match.status}
            />

            <TransactionMap entries={feedEntries} />
          </div>
        </div>
      </div>
    </main>
  );
}
