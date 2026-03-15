"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import {
  ArrowLeft,
  Copy,
  ExternalLink,
  Fingerprint,
  Network,
  ShieldAlert,
} from "lucide-react";

import { getErrorMessage, getMatch } from "@/lib/api";
import {
  buildCloneSetupUrl,
  isCloneReady,
  isTrackedMatchArchived,
  listTrackedMatches,
  upsertTrackedMatch,
  type TrackedMatchRecord,
} from "@/lib/match-access";
import {
  inferScenarioFromMatchConfig,
  type CriminalPersona,
} from "@/lib/scenarios";

type ScenarioLibraryItem = TrackedMatchRecord & {
  refreshError: string | null;
};

const personaIcons = {
  amateur: ShieldAlert,
  patient: Fingerprint,
  botnet: Network,
} as const satisfies Record<CriminalPersona, typeof ShieldAlert>;

function sortScenarioLibraryItems(
  items: ScenarioLibraryItem[],
): ScenarioLibraryItem[] {
  return [...items].sort((left, right) => {
    const leftTime = Date.parse(left.updatedAt || left.launchedAt || "");
    const rightTime = Date.parse(right.updatedAt || right.launchedAt || "");
    const safeLeftTime = Number.isNaN(leftTime) ? 0 : leftTime;
    const safeRightTime = Number.isNaN(rightTime) ? 0 : rightTime;
    return safeRightTime - safeLeftTime;
  });
}

function formatTimestamp(value: string | null): string {
  if (!value) {
    return "Unavailable";
  }

  const timestamp = Date.parse(value);
  if (Number.isNaN(timestamp)) {
    return "Unavailable";
  }

  return new Intl.DateTimeFormat("en-CA", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(timestamp));
}

function getStatusTone(status: string): string {
  switch (status) {
    case "complete":
      return "border-emerald-300/20 bg-emerald-400/10 text-emerald-100";
    case "running":
      return "border-rose-300/20 bg-rose-400/10 text-rose-100";
    case "paused":
      return "border-amber-300/20 bg-amber-300/10 text-amber-100";
    case "setup":
      return "border-cyan-300/20 bg-cyan-400/10 text-cyan-100";
    default:
      return "border-slate-300/20 bg-slate-400/10 text-slate-200";
  }
}

function getArchiveTone(): string {
  return "border-fuchsia-300/20 bg-fuchsia-400/10 text-fuchsia-100";
}

function getPersonaLabel(persona: CriminalPersona | null): string {
  if (!persona) {
    return "Unknown persona";
  }

  return persona;
}

function buildScenarioLibraryItem(record: TrackedMatchRecord): ScenarioLibraryItem {
  return {
    ...record,
    refreshError: null,
  };
}

export default function ScenarioLibraryPage() {
  const [items, setItems] = useState<ScenarioLibraryItem[]>([]);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    let isActive = true;

    async function loadScenarioLibrary() {
      const trackedMatches = listTrackedMatches();
      if (!isActive) {
        return;
      }

      if (trackedMatches.length === 0) {
        setItems([]);
        setIsLoading(false);
        return;
      }

      const initialItems = sortScenarioLibraryItems(
        trackedMatches.map(buildScenarioLibraryItem),
      );
      setItems(initialItems);

      const refreshedMatches = await Promise.allSettled(
        trackedMatches.map((record) => getMatch(record.matchId)),
      );
      if (!isActive) {
        return;
      }

      const nextItems = sortScenarioLibraryItems(
        trackedMatches.map((record, index) => {
          const result = refreshedMatches[index];
          if (result.status === "rejected") {
            return {
              ...record,
              refreshError: getErrorMessage(result.reason),
            };
          }

          const match = result.value;
          const inferredScenario = inferScenarioFromMatchConfig({
            scenarioName: match.scenario_name,
            criminalPersona: match.criminal_persona ?? record.criminalPersona,
            totalRounds: match.total_rounds,
          });

          const nextRecord = upsertTrackedMatch({
            matchId: match.match_id,
            shareUrl: match.share_url ?? record.shareUrl,
            scenarioId: record.scenarioId ?? inferredScenario?.id ?? null,
            scenarioName: match.scenario_name,
            criminalPersona:
              match.criminal_persona ??
              record.criminalPersona ??
              inferredScenario?.criminalPersona ??
              null,
            totalRounds:
              match.total_rounds ??
              record.totalRounds ??
              inferredScenario?.totalRounds ??
              null,
            defenderMode: match.defender_mode ?? record.defenderMode ?? null,
            status: match.status,
            currentRound: match.current_round,
            updatedAt: match.updated_at,
            endedAt: match.ended_at ?? null,
            expiresAt: match.expires_at ?? null,
          });

          return {
            ...nextRecord,
            refreshError: null,
          };
        }),
      );

      setItems(nextItems);
      setIsLoading(false);
    }

    loadScenarioLibrary();

    return () => {
      isActive = false;
    };
  }, []);

  const archivedMatches = items.filter((item) => isTrackedMatchArchived(item));
  const completedMatches = items.filter(
    (item) => item.status === "complete" && !isTrackedMatchArchived(item),
  );
  const inProgressMatches = items.filter(
    (item) => item.status !== "complete" && !isTrackedMatchArchived(item),
  );

  if (isLoading) {
    return (
      <main className="px-6 py-8 sm:px-8 lg:px-12">
        <div className="mx-auto max-w-7xl">
          <div className="rounded-[32px] border border-white/10 bg-[rgba(15,22,41,0.82)] p-8 text-slate-200 shadow-[0_24px_80px_rgba(3,8,18,0.45)]">
            Loading scenario library...
          </div>
        </div>
      </main>
    );
  }

  if (items.length === 0) {
    return (
      <main className="px-6 py-8 sm:px-8 lg:px-12">
        <div className="mx-auto max-w-4xl">
          <section className="rounded-[32px] border border-white/10 bg-[linear-gradient(145deg,rgba(15,22,41,0.95),rgba(10,14,26,0.9))] p-8 shadow-[0_24px_80px_rgba(3,8,18,0.45)]">
            <Link
              href="/"
              className="inline-flex items-center gap-2 text-sm text-slate-400 transition hover:text-slate-200"
            >
              <ArrowLeft className="h-4 w-4" />
              Back to setup
            </Link>
            <p className="mt-6 text-xs uppercase tracking-[0.32em] text-cyan-300/80">
              Scenario Library
            </p>
            <h1 className="mt-2 text-4xl font-semibold text-slate-50">
              No tracked matches yet
            </h1>
            <p className="mt-4 max-w-2xl text-sm leading-6 text-slate-300">
              Launch a match from the setup page first. Ghost Protocol stores
              owned match configurations in this browser so completed runs can
              be cloned into fresh scenarios later.
            </p>
            <Link
              href="/"
              className="mt-6 inline-flex items-center gap-2 rounded-full border border-cyan-300/20 bg-cyan-400/10 px-5 py-2.5 text-sm font-medium text-cyan-100 transition hover:bg-cyan-400/15"
            >
              <ExternalLink className="h-4 w-4" />
              Open setup
            </Link>
          </section>
        </div>
      </main>
    );
  }

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
              <p className="mt-5 text-xs uppercase tracking-[0.32em] text-cyan-300/80">
                Scenario Library
              </p>
              <h1 className="mt-2 text-4xl font-semibold text-slate-50">
                Clone proven attack setups into fresh matches
              </h1>
              <p className="mt-4 max-w-3xl text-sm leading-6 text-slate-300">
                This browser tracks owned Ghost Protocol matches and refreshes
                them against the canonical backend state. Completed matches can
                be cloned back into setup without altering the original run.
              </p>
            </div>

            <div className="grid gap-3 sm:grid-cols-3">
              <div className="rounded-[24px] border border-white/10 bg-white/5 px-5 py-4">
                <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
                  Completed
                </p>
                <p className="mt-2 text-2xl font-semibold text-slate-50">
                  {completedMatches.length}
                </p>
              </div>
              <div className="rounded-[24px] border border-white/10 bg-white/5 px-5 py-4">
                <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
                  Archived
                </p>
                <p className="mt-2 text-2xl font-semibold text-slate-50">
                  {archivedMatches.length}
                </p>
              </div>
              <div className="rounded-[24px] border border-white/10 bg-white/5 px-5 py-4">
                <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
                  Tracked Total
                </p>
                <p className="mt-2 text-2xl font-semibold text-slate-50">
                  {items.length}
                </p>
              </div>
            </div>
          </div>
        </section>

        <section className="space-y-5">
          <div className="flex items-center justify-between gap-4">
            <div>
              <p className="text-xs uppercase tracking-[0.32em] text-cyan-300/80">
                Completed Matches
              </p>
              <h2 className="mt-2 text-2xl font-semibold text-slate-50">
                Ready to clone
              </h2>
            </div>
          </div>

          {completedMatches.length === 0 ? (
            <div className="rounded-[28px] border border-white/10 bg-[rgba(15,22,41,0.8)] p-6 text-sm leading-6 text-slate-300 shadow-[0_24px_80px_rgba(3,8,18,0.45)]">
              No completed matches yet. Finish a match and it will appear here
              with a `Clone this Scenario` action.
            </div>
          ) : (
            <div className="grid gap-5 xl:grid-cols-2">
              {completedMatches.map((item) => {
                const PersonaIcon = item.criminalPersona
                  ? personaIcons[item.criminalPersona]
                  : ShieldAlert;
                const cloneReady = isCloneReady(item);

                return (
                  <article
                    key={item.matchId}
                    className="rounded-[28px] border border-white/10 bg-[rgba(15,22,41,0.82)] p-6 shadow-[0_24px_80px_rgba(3,8,18,0.45)]"
                  >
                    <div className="flex flex-wrap items-start justify-between gap-4">
                      <div>
                        <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
                          {item.matchId}
                        </p>
                        <h3 className="mt-2 text-2xl font-semibold text-slate-50">
                          {item.scenarioName}
                        </h3>
                      </div>
                      <div className="flex flex-wrap items-center gap-2">
                        <div
                          className={`rounded-full border px-3 py-1 text-xs font-medium uppercase tracking-[0.22em] ${getStatusTone(item.status)}`}
                        >
                          {item.status}
                        </div>
                      </div>
                    </div>

                    <div className="mt-5 grid gap-4 sm:grid-cols-2">
                      <div className="rounded-[22px] border border-white/10 bg-slate-950/35 p-4">
                        <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
                          Criminal Persona
                        </p>
                        <p className="mt-2 inline-flex items-center gap-2 text-base font-medium capitalize text-slate-50">
                          <PersonaIcon className="h-4 w-4 text-cyan-200" />
                          {getPersonaLabel(item.criminalPersona)}
                        </p>
                      </div>
                      <div className="rounded-[22px] border border-white/10 bg-slate-950/35 p-4">
                        <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
                          Defender Mode
                        </p>
                        <p className="mt-2 text-base font-medium text-slate-50">
                          {item.defenderMode === "police_ai"
                            ? "Police AI"
                            : item.defenderMode === "webhook"
                              ? "Webhook API"
                              : "Unknown"}
                        </p>
                      </div>
                      <div className="rounded-[22px] border border-white/10 bg-slate-950/35 p-4">
                        <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
                          Rounds
                        </p>
                        <p className="mt-2 text-base font-medium text-slate-50">
                          {item.totalRounds ? `${item.totalRounds}` : "Unknown"}
                        </p>
                      </div>
                      <div className="rounded-[22px] border border-white/10 bg-slate-950/35 p-4">
                        <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
                          Last Updated
                        </p>
                        <p className="mt-2 text-base font-medium text-slate-50">
                          {formatTimestamp(item.updatedAt || item.endedAt)}
                        </p>
                      </div>
                    </div>

                    {item.refreshError ? (
                      <div className="mt-4 rounded-[22px] border border-amber-300/20 bg-amber-300/10 p-4 text-sm leading-6 text-amber-100">
                        Latest backend refresh failed: {item.refreshError}
                      </div>
                    ) : null}

                    <div className="mt-5 flex flex-wrap gap-3">
                      {cloneReady ? (
                        <Link
                          href={buildCloneSetupUrl(item.matchId)}
                          className="inline-flex items-center gap-2 rounded-full border border-cyan-300/20 bg-cyan-400/10 px-4 py-2 text-sm font-medium text-cyan-100 transition hover:bg-cyan-400/15"
                        >
                          <Copy className="h-4 w-4" />
                          Clone this Scenario
                        </Link>
                      ) : (
                        <span className="inline-flex items-center gap-2 rounded-full border border-slate-300/15 bg-white/5 px-4 py-2 text-sm font-medium text-slate-400">
                          <Copy className="h-4 w-4" />
                          Clone unavailable
                        </span>
                      )}

                      <Link
                        href={item.shareUrl || `/match/${item.matchId}`}
                        className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/10 px-4 py-2 text-sm font-medium text-slate-100 transition hover:bg-white/15"
                      >
                        <ExternalLink className="h-4 w-4" />
                        Open War Room
                      </Link>

                      <Link
                        href={`/replay/${item.matchId}`}
                        className="inline-flex items-center gap-2 rounded-full border border-amber-300/20 bg-amber-300/10 px-4 py-2 text-sm font-medium text-amber-100 transition hover:bg-amber-300/15"
                      >
                        <ExternalLink className="h-4 w-4" />
                        Open Replay
                      </Link>
                    </div>

                    {!cloneReady ? (
                      <p className="mt-4 text-sm leading-6 text-slate-400">
                        Clone requires a stored scenario ID and defender setup.
                        For webhook defenders, the original webhook URL must
                        still be available in this browser.
                      </p>
                    ) : null}
                  </article>
                );
              })}
            </div>
          )}
        </section>

        <section className="space-y-5">
          <div>
            <p className="text-xs uppercase tracking-[0.32em] text-cyan-300/80">
              Archived Matches
            </p>
            <h2 className="mt-2 text-2xl font-semibold text-slate-50">
              Read-only after 24 hours
            </h2>
          </div>

          {archivedMatches.length === 0 ? (
            <div className="rounded-[28px] border border-white/10 bg-[rgba(15,22,41,0.8)] p-6 text-sm leading-6 text-slate-300 shadow-[0_24px_80px_rgba(3,8,18,0.45)]">
              No archived matches yet. Once a tracked match passes its 24-hour
              expiry, it stays viewable here with an `Archived` badge and
              read-only behavior.
            </div>
          ) : (
            <div className="grid gap-5 xl:grid-cols-2">
              {archivedMatches.map((item) => {
                const PersonaIcon = item.criminalPersona
                  ? personaIcons[item.criminalPersona]
                  : ShieldAlert;
                const cloneReady =
                  item.status === "complete" && isCloneReady(item);

                return (
                  <article
                    key={item.matchId}
                    className="rounded-[28px] border border-white/10 bg-[rgba(15,22,41,0.82)] p-6 shadow-[0_24px_80px_rgba(3,8,18,0.45)]"
                  >
                    <div className="flex flex-wrap items-start justify-between gap-4">
                      <div>
                        <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
                          {item.matchId}
                        </p>
                        <h3 className="mt-2 text-2xl font-semibold text-slate-50">
                          {item.scenarioName}
                        </h3>
                      </div>
                      <div className="flex flex-wrap items-center gap-2">
                        <div
                          className={`rounded-full border px-3 py-1 text-xs font-medium uppercase tracking-[0.22em] ${getArchiveTone()}`}
                        >
                          Archived
                        </div>
                        <div
                          className={`rounded-full border px-3 py-1 text-xs font-medium uppercase tracking-[0.22em] ${getStatusTone(item.status)}`}
                        >
                          {item.status}
                        </div>
                      </div>
                    </div>

                    <div className="mt-5 grid gap-4 sm:grid-cols-2">
                      <div className="rounded-[22px] border border-white/10 bg-slate-950/35 p-4">
                        <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
                          Criminal Persona
                        </p>
                        <p className="mt-2 inline-flex items-center gap-2 text-base font-medium capitalize text-slate-50">
                          <PersonaIcon className="h-4 w-4 text-cyan-200" />
                          {getPersonaLabel(item.criminalPersona)}
                        </p>
                      </div>
                      <div className="rounded-[22px] border border-white/10 bg-slate-950/35 p-4">
                        <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
                          Defender Mode
                        </p>
                        <p className="mt-2 text-base font-medium text-slate-50">
                          {item.defenderMode === "police_ai"
                            ? "Police AI"
                            : item.defenderMode === "webhook"
                              ? "Webhook API"
                              : "Unknown"}
                        </p>
                      </div>
                      <div className="rounded-[22px] border border-white/10 bg-slate-950/35 p-4">
                        <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
                          Archived At
                        </p>
                        <p className="mt-2 text-base font-medium text-slate-50">
                          {formatTimestamp(item.expiresAt)}
                        </p>
                      </div>
                      <div className="rounded-[22px] border border-white/10 bg-slate-950/35 p-4">
                        <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
                          Last Updated
                        </p>
                        <p className="mt-2 text-base font-medium text-slate-50">
                          {formatTimestamp(item.updatedAt || item.endedAt)}
                        </p>
                      </div>
                    </div>

                    {item.refreshError ? (
                      <div className="mt-4 rounded-[22px] border border-amber-300/20 bg-amber-300/10 p-4 text-sm leading-6 text-amber-100">
                        Latest backend refresh failed: {item.refreshError}
                      </div>
                    ) : null}

                    <div className="mt-5 flex flex-wrap gap-3">
                      {cloneReady ? (
                        <Link
                          href={buildCloneSetupUrl(item.matchId)}
                          className="inline-flex items-center gap-2 rounded-full border border-cyan-300/20 bg-cyan-400/10 px-4 py-2 text-sm font-medium text-cyan-100 transition hover:bg-cyan-400/15"
                        >
                          <Copy className="h-4 w-4" />
                          Clone this Scenario
                        </Link>
                      ) : null}

                      <Link
                        href={item.shareUrl || `/match/${item.matchId}`}
                        className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/10 px-4 py-2 text-sm font-medium text-slate-100 transition hover:bg-white/15"
                      >
                        <ExternalLink className="h-4 w-4" />
                        Open War Room
                      </Link>

                      <Link
                        href={`/replay/${item.matchId}`}
                        className="inline-flex items-center gap-2 rounded-full border border-amber-300/20 bg-amber-300/10 px-4 py-2 text-sm font-medium text-amber-100 transition hover:bg-amber-300/15"
                      >
                        <ExternalLink className="h-4 w-4" />
                        Open Replay
                      </Link>
                    </div>

                    <p className="mt-4 text-sm leading-6 text-slate-400">
                      Archived matches stay viewable for replay and review, but
                      Ghost Protocol treats them as read-only and blocks further
                      match changes.
                    </p>
                  </article>
                );
              })}
            </div>
          )}
        </section>

        <section className="space-y-5">
          <div>
            <p className="text-xs uppercase tracking-[0.32em] text-cyan-300/80">
              Active / Pending
            </p>
            <h2 className="mt-2 text-2xl font-semibold text-slate-50">
              Still in motion
            </h2>
          </div>

          {inProgressMatches.length === 0 ? (
            <div className="rounded-[28px] border border-white/10 bg-[rgba(15,22,41,0.8)] p-6 text-sm leading-6 text-slate-300 shadow-[0_24px_80px_rgba(3,8,18,0.45)]">
              No active tracked matches. Everything in this browser is already
              complete and clone-ready.
            </div>
          ) : (
            <div className="grid gap-5 xl:grid-cols-2">
              {inProgressMatches.map((item) => (
                <article
                  key={item.matchId}
                  className="rounded-[28px] border border-white/10 bg-[rgba(15,22,41,0.82)] p-6 shadow-[0_24px_80px_rgba(3,8,18,0.45)]"
                >
                  <div className="flex flex-wrap items-start justify-between gap-4">
                    <div>
                      <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
                        {item.matchId}
                      </p>
                      <h3 className="mt-2 text-2xl font-semibold text-slate-50">
                        {item.scenarioName}
                      </h3>
                    </div>
                    <div
                      className={`rounded-full border px-3 py-1 text-xs font-medium uppercase tracking-[0.22em] ${getStatusTone(item.status)}`}
                    >
                      {item.status}
                    </div>
                  </div>

                  <p className="mt-4 text-sm leading-6 text-slate-300">
                    Current round: {item.currentRound || 0}
                    {item.totalRounds ? ` / ${item.totalRounds}` : ""}
                  </p>

                  {item.refreshError ? (
                    <div className="mt-4 rounded-[22px] border border-amber-300/20 bg-amber-300/10 p-4 text-sm leading-6 text-amber-100">
                      Latest backend refresh failed: {item.refreshError}
                    </div>
                  ) : null}

                  <div className="mt-5 flex flex-wrap gap-3">
                    <Link
                      href={item.shareUrl || `/match/${item.matchId}`}
                      className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/10 px-4 py-2 text-sm font-medium text-slate-100 transition hover:bg-white/15"
                    >
                      <ExternalLink className="h-4 w-4" />
                      Open War Room
                    </Link>
                  </div>

                  <p className="mt-4 text-sm leading-6 text-slate-400">
                    Clone unlocks here automatically once the match reaches
                    `complete`.
                  </p>
                </article>
              ))}
            </div>
          )}
        </section>
      </div>
    </main>
  );
}
