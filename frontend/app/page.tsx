"use client";

import Link from "next/link";
import { Suspense, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  ArrowRight,
  BrainCircuit,
  Copy,
  ExternalLink,
  Radar,
  Share2,
  ShieldCheck,
  Siren,
  Swords,
} from "lucide-react";

import {
  DefenderSetup,
  type ConnectionStatus,
} from "@/components/DefenderSetup";
import { ScenarioSelector } from "@/components/ScenarioSelector";
import {
  createMatch,
  getErrorMessage,
  registerDefender,
  startMatch,
  testDefenderConnection,
} from "@/lib/api";
import { getBackendBaseUrl } from "@/lib/config";
import {
  copyTextToClipboard,
  getTrackedMatch,
  resolveAbsoluteShareUrl,
  trackMatchLaunch,
} from "@/lib/match-access";
import {
  DEFAULT_SCENARIO_ID,
  SCENARIOS,
  getScenarioById,
  type ScenarioDefinition,
} from "@/lib/scenarios";

type DefenderMode = "police_ai" | "webhook";

type LaunchSummary = {
  matchId: string;
  shareUrl: string;
  absoluteShareUrl: string;
  status: string;
  defenderMode: DefenderMode;
  defenderId: string;
};

type CloneNotice =
  | {
      state: "ready";
      sourceMatchId: string;
      scenarioName: string;
      detail: string;
    }
  | {
      state: "missing";
      sourceMatchId: string;
      detail: string;
    };

const READY_STATUS: ConnectionStatus = {
  state: "ready",
  label: "Ready",
  detail:
    "Police AI is armed and ready to defend in mock mode with automatic live activation once a Gemini key exists.",
};

const AWAITING_WEBHOOK_STATUS: ConnectionStatus = {
  state: "idle",
  label: "Awaiting Test",
  detail:
    "Enter a reachable webhook, then run Test Connection before launching the match.",
};

function buildClonedWebhookStatus(hasWebhookUrl: boolean): ConnectionStatus {
  if (!hasWebhookUrl) {
    return {
      state: "idle",
      label: "Clone Incomplete",
      detail:
        "The cloned webhook URL was not available. Enter it again, then run Test Connection before launching.",
    };
  }

  return {
    state: "idle",
    label: "Clone Loaded",
    detail:
      "The cloned webhook URL is pre-filled. Run Test Connection again before launching the new match.",
  };
}

const HOW_IT_WORKS = [
  {
    title: "1. Wire the defender",
    description:
      "Choose Police AI for the built-in fallback or point Ghost Protocol at your own scoring API.",
    icon: ShieldCheck,
  },
  {
    title: "2. Start the heist",
    description:
      "Spin up a sandbox match with a criminal persona tuned for loud, subtle, or distributed fraud.",
    icon: Swords,
  },
  {
    title: "3. Watch the referee",
    description:
      "The backend tracks every decision, every miss, and every adaptation for the live War Room.",
    icon: Radar,
  },
] as const;

function buildProbeMatchId(scenario: ScenarioDefinition): string {
  return `probe-${scenario.id}-${Date.now().toString(36)}`;
}

function HomeContent() {
  const searchParams = useSearchParams();
  const cloneMatchId = searchParams.get("clone");
  const [selectedScenarioId, setSelectedScenarioId] =
    useState<string>(DEFAULT_SCENARIO_ID);
  const [defenderMode, setDefenderMode] = useState<DefenderMode>("police_ai");
  const [webhookUrl, setWebhookUrl] = useState("");
  const [connectionStatus, setConnectionStatus] =
    useState<ConnectionStatus>(READY_STATUS);
  const [isTestingConnection, setIsTestingConnection] = useState(false);
  const [isLaunching, setIsLaunching] = useState(false);
  const [launchError, setLaunchError] = useState<string | null>(null);
  const [launchSummary, setLaunchSummary] = useState<LaunchSummary | null>(
    null,
  );
  const [shareCopyState, setShareCopyState] = useState<
    "idle" | "copied" | "failed"
  >("idle");
  const [cloneNotice, setCloneNotice] = useState<CloneNotice | null>(null);
  const lastAppliedCloneId = useRef<string | null>(null);

  const selectedScenario =
    SCENARIOS.find((scenario) => scenario.id === selectedScenarioId) ??
    SCENARIOS[0];
  const canLaunch =
    defenderMode === "police_ai" || connectionStatus.state === "success";
  const backendBaseUrl = getBackendBaseUrl();

  useEffect(() => {
    if (!cloneMatchId) {
      lastAppliedCloneId.current = null;
      setCloneNotice(null);
      return;
    }

    if (lastAppliedCloneId.current === cloneMatchId) {
      return;
    }

    const trackedMatch = getTrackedMatch(cloneMatchId);
    if (
      !trackedMatch ||
      !trackedMatch.scenarioId ||
      !trackedMatch.defenderMode
    ) {
      setCloneNotice({
        state: "missing",
        sourceMatchId: cloneMatchId,
        detail:
          "Clone data is not available in this browser anymore. Re-open the scenario library from the browser that launched the original match or choose a scenario manually.",
      });
      lastAppliedCloneId.current = cloneMatchId;
      return;
    }

    const clonedScenario =
      getScenarioById(trackedMatch.scenarioId) ?? SCENARIOS[0];
    const clonedWebhookUrl =
      trackedMatch.defenderMode === "webhook" ? trackedMatch.webhookUrl : "";

    setSelectedScenarioId(clonedScenario.id);
    setDefenderMode(trackedMatch.defenderMode);
    setWebhookUrl(clonedWebhookUrl);
    setConnectionStatus(
      trackedMatch.defenderMode === "police_ai"
        ? READY_STATUS
        : buildClonedWebhookStatus(clonedWebhookUrl.trim().length > 0),
    );
    setLaunchError(null);
    setLaunchSummary(null);
    setShareCopyState("idle");
    setCloneNotice({
      state: "ready",
      sourceMatchId: cloneMatchId,
      scenarioName: trackedMatch.scenarioName,
      detail:
        trackedMatch.defenderMode === "police_ai"
          ? "Police AI mode and scenario settings were cloned. Review them, then launch a fresh match."
          : "Scenario and webhook settings were cloned. Re-test the webhook before launching the fresh match.",
    });
    lastAppliedCloneId.current = cloneMatchId;
  }, [cloneMatchId]);

  function handleScenarioSelect(scenarioId: string) {
    setSelectedScenarioId(scenarioId);
    setLaunchError(null);
    setLaunchSummary(null);
    setShareCopyState("idle");
  }

  function handleModeChange(mode: DefenderMode) {
    setDefenderMode(mode);
    setLaunchError(null);
    setLaunchSummary(null);
    setShareCopyState("idle");
    setConnectionStatus(mode === "police_ai" ? READY_STATUS : AWAITING_WEBHOOK_STATUS);
  }

  function handleWebhookUrlChange(value: string) {
    setWebhookUrl(value);
    setLaunchError(null);
    setLaunchSummary(null);
    setShareCopyState("idle");
    if (defenderMode === "webhook") {
      setConnectionStatus(
        value.trim().length > 0
          ? AWAITING_WEBHOOK_STATUS
          : {
              state: "idle",
              label: "Missing URL",
              detail:
                "A webhook endpoint is required when using your own defender API.",
            },
      );
    }
  }

  async function handleTestConnection() {
    if (webhookUrl.trim().length === 0) {
      setConnectionStatus({
        state: "error",
        label: "Missing URL",
        detail: "Enter a webhook URL before running the connectivity probe.",
      });
      return;
    }

    setIsTestingConnection(true);
    setLaunchError(null);
    setConnectionStatus({
      state: "testing",
      label: "Testing",
      detail: "Sending a defender-safe dummy transaction to your endpoint.",
    });

    try {
      const response = await testDefenderConnection({
        match_id: buildProbeMatchId(selectedScenario),
        webhook_url: webhookUrl.trim(),
      });

      if (response.status === "reachable") {
        setConnectionStatus({
          state: "success",
          label: "Connected",
          detail:
            "Webhook is reachable. Launch will still validate the defender response contract during registration.",
        });
        return;
      }

      setConnectionStatus({
        state: "error",
        label: "Unreachable",
        detail: response.error || "The webhook probe failed.",
      });
    } catch (error) {
      setConnectionStatus({
        state: "error",
        label: "Probe Failed",
        detail: getErrorMessage(error),
      });
    } finally {
      setIsTestingConnection(false);
    }
  }

  async function handleLaunchMatch() {
    if (!canLaunch || isLaunching) {
      return;
    }

    setIsLaunching(true);
    setLaunchError(null);
    setLaunchSummary(null);
    setShareCopyState("idle");

    try {
      const createdMatch = await createMatch({
        scenario_name: selectedScenario.name,
        criminal_persona: selectedScenario.criminalPersona,
        total_rounds: selectedScenario.totalRounds,
      });

      const defenderRegistration = await registerDefender({
        match_id: createdMatch.match_id,
        webhook_url:
          defenderMode === "webhook" ? webhookUrl.trim() : undefined,
        use_police_ai: defenderMode === "police_ai",
      });

      const startedMatch = await startMatch(createdMatch.match_id);
      const absoluteShareUrl = resolveAbsoluteShareUrl(createdMatch.share_url);
      trackMatchLaunch({
        matchId: createdMatch.match_id,
        shareUrl: createdMatch.share_url,
        scenarioId: selectedScenario.id,
        scenarioName: selectedScenario.name,
        criminalPersona: selectedScenario.criminalPersona,
        totalRounds: selectedScenario.totalRounds,
        defenderMode,
        webhookUrl: defenderMode === "webhook" ? webhookUrl.trim() : "",
        status: startedMatch.status,
        currentRound: startedMatch.current_round ?? 0,
        expiresAt: startedMatch.expires_at ?? null,
      });

      setLaunchSummary({
        matchId: createdMatch.match_id,
        shareUrl: createdMatch.share_url,
        absoluteShareUrl,
        status: startedMatch.status,
        defenderMode,
        defenderId: defenderRegistration.defender_id,
      });
    } catch (error) {
      setLaunchError(getErrorMessage(error));
    } finally {
      setIsLaunching(false);
    }
  }

  async function handleCopyShareLink() {
    if (!launchSummary) {
      return;
    }

    const copied = await copyTextToClipboard(launchSummary.absoluteShareUrl);
    setShareCopyState(copied ? "copied" : "failed");
  }

  return (
    <main className="relative overflow-hidden px-6 py-8 sm:px-8 lg:px-12">
      <div className="mx-auto max-w-7xl">
        <section className="grid gap-8 lg:grid-cols-[1.08fr_0.92fr] lg:items-start">
          <div className="space-y-8">
            <div className="overflow-hidden rounded-[32px] border border-white/10 bg-[linear-gradient(145deg,rgba(15,22,41,0.95),rgba(10,14,26,0.88))] p-8 shadow-[0_30px_120px_rgba(2,6,23,0.55)]">
              <div className="flex flex-wrap items-center gap-3">
                <div className="inline-flex items-center gap-2 rounded-full border border-cyan-300/25 bg-cyan-400/10 px-3 py-1 text-xs font-medium uppercase tracking-[0.22em] text-cyan-200">
                  <Siren className="h-3.5 w-3.5" />
                  Ghost Protocol
                </div>
                <div className="inline-flex items-center gap-2 rounded-full border border-rose-300/20 bg-rose-400/10 px-3 py-1 text-xs font-medium uppercase tracking-[0.22em] text-rose-200">
                  War Room Setup
                </div>
              </div>

              <div className="mt-8 max-w-3xl">
                <p className="text-sm uppercase tracking-[0.38em] text-slate-400">
                  Adversarial AI Simulation Lab
                </p>
                <h1 className="mt-4 text-4xl font-semibold leading-tight text-slate-50 sm:text-5xl">
                  Don&apos;t build a better lock. Build a smarter thief.
                </h1>
                <p className="mt-5 max-w-2xl text-base leading-7 text-slate-300 sm:text-lg">
                  Stage a synthetic fraud heist, route transactions into your
                  detector, and let Ghost Protocol score every hit, miss, and
                  blind spot without touching real customer data.
                </p>
              </div>

              <div className="mt-8 grid gap-4 sm:grid-cols-3">
                <div className="rounded-[24px] border border-white/10 bg-white/5 p-4">
                  <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
                    Active backend
                  </p>
                  <p className="mt-2 break-all text-sm font-medium text-slate-100">
                    {backendBaseUrl}
                  </p>
                </div>
                <div className="rounded-[24px] border border-white/10 bg-white/5 p-4">
                  <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
                    LLM mode
                  </p>
                  <p className="mt-2 text-sm font-medium text-slate-100">
                    Mock/stub fallback until `GEMINI_API_KEY` exists
                  </p>
                </div>
                <div className="rounded-[24px] border border-white/10 bg-white/5 p-4">
                  <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
                    Sandbox source
                  </p>
                  <p className="mt-2 text-sm font-medium text-slate-100">
                    Native Ghost Protocol match engine
                  </p>
                </div>
              </div>

              <div className="mt-6 flex flex-wrap gap-3">
                <Link
                  href="/scenarios"
                  className="inline-flex items-center gap-2 rounded-full border border-cyan-300/20 bg-cyan-400/10 px-4 py-2 text-sm font-medium text-cyan-100 transition hover:bg-cyan-400/15"
                >
                  <ExternalLink className="h-4 w-4" />
                  Open Scenario Library
                </Link>
              </div>
            </div>

            {cloneNotice ? (
              <section
                className={`rounded-[28px] border p-5 shadow-[0_24px_80px_rgba(3,8,18,0.45)] backdrop-blur ${
                  cloneNotice.state === "ready"
                    ? "border-cyan-300/20 bg-cyan-400/10"
                    : "border-amber-300/20 bg-amber-300/10"
                }`}
              >
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div>
                    <p className="text-xs uppercase tracking-[0.32em] text-slate-100/80">
                      {cloneNotice.state === "ready"
                        ? "Clone Loaded"
                        : "Clone Unavailable"}
                    </p>
                    <h2 className="mt-2 text-2xl font-semibold text-slate-50">
                      {cloneNotice.state === "ready"
                        ? `Cloned from ${cloneNotice.scenarioName}`
                        : "Original scenario data could not be restored"}
                    </h2>
                  </div>
                  <div className="rounded-full border border-white/10 bg-white/10 px-3 py-1 text-xs font-medium uppercase tracking-[0.22em] text-slate-100">
                    Source match {cloneNotice.sourceMatchId}
                  </div>
                </div>
                <p className="mt-4 max-w-3xl text-sm leading-6 text-slate-200/90">
                  {cloneNotice.detail}
                </p>
              </section>
            ) : null}

            <ScenarioSelector
              scenarios={SCENARIOS}
              selectedScenarioId={selectedScenarioId}
              onSelect={handleScenarioSelect}
            />

            <section className="rounded-[28px] border border-white/10 bg-[rgba(15,22,41,0.74)] p-6 shadow-[0_24px_80px_rgba(3,8,18,0.45)] backdrop-blur">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="text-xs uppercase tracking-[0.32em] text-cyan-300/80">
                    How It Works
                  </p>
                  <h2 className="mt-2 text-2xl font-semibold text-slate-50">
                    Three quick steps to a live heist
                  </h2>
                </div>
                <div className="rounded-full border border-amber-300/20 bg-amber-300/10 p-3 text-amber-100">
                  <BrainCircuit className="h-5 w-5" />
                </div>
              </div>

              <div className="mt-6 grid gap-4 md:grid-cols-3">
                {HOW_IT_WORKS.map((step) => {
                  const Icon = step.icon;

                  return (
                    <article
                      key={step.title}
                      className="rounded-[24px] border border-white/10 bg-slate-950/35 p-5"
                    >
                      <div className="rounded-2xl border border-white/10 bg-white/5 p-3 text-cyan-200">
                        <Icon className="h-5 w-5" />
                      </div>
                      <h3 className="mt-4 text-lg font-semibold text-slate-50">
                        {step.title}
                      </h3>
                      <p className="mt-3 text-sm leading-6 text-slate-300">
                        {step.description}
                      </p>
                    </article>
                  );
                })}
              </div>
            </section>
          </div>

          <div className="space-y-8">
            <DefenderSetup
              defenderMode={defenderMode}
              webhookUrl={webhookUrl}
              connectionStatus={connectionStatus}
              onModeChange={handleModeChange}
              onWebhookUrlChange={handleWebhookUrlChange}
              onTestConnection={handleTestConnection}
              isTesting={isTestingConnection}
            />

            <section className="rounded-[28px] border border-white/10 bg-[linear-gradient(145deg,rgba(18,26,47,0.94),rgba(8,13,24,0.92))] p-6 shadow-[0_24px_80px_rgba(3,8,18,0.45)] backdrop-blur">
              <p className="text-xs uppercase tracking-[0.32em] text-cyan-300/80">
                Launch Control
              </p>
              <h2 className="mt-2 text-2xl font-semibold text-slate-50">
                Arm the sandbox
              </h2>

              <div className="mt-5 rounded-[24px] border border-white/10 bg-slate-950/45 p-5">
                <dl className="grid gap-4 sm:grid-cols-2">
                  <div>
                    <dt className="text-xs uppercase tracking-[0.22em] text-slate-400">
                      Scenario
                    </dt>
                    <dd className="mt-2 text-base font-medium text-slate-50">
                      {selectedScenario.name}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs uppercase tracking-[0.22em] text-slate-400">
                      Defender mode
                    </dt>
                    <dd className="mt-2 text-base font-medium text-slate-50">
                      {defenderMode === "police_ai" ? "Police AI" : "Webhook API"}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs uppercase tracking-[0.22em] text-slate-400">
                      Criminal persona
                    </dt>
                    <dd className="mt-2 text-base font-medium capitalize text-slate-50">
                      {selectedScenario.criminalPersona}
                    </dd>
                  </div>
                  <div>
                    <dt className="text-xs uppercase tracking-[0.22em] text-slate-400">
                      Match rounds
                    </dt>
                    <dd className="mt-2 text-base font-medium text-slate-50">
                      {selectedScenario.totalRounds}
                    </dd>
                  </div>
                </dl>
              </div>

              <button
                type="button"
                onClick={handleLaunchMatch}
                disabled={!canLaunch || isLaunching}
                className="mt-6 inline-flex w-full items-center justify-center gap-2 rounded-full border border-cyan-300/30 bg-[linear-gradient(90deg,rgba(0,212,255,0.24),rgba(255,59,59,0.22))] px-6 py-4 text-sm font-semibold uppercase tracking-[0.24em] text-slate-50 transition hover:shadow-[0_0_30px_rgba(34,211,238,0.15)] disabled:cursor-not-allowed disabled:border-white/10 disabled:bg-white/5 disabled:text-slate-500"
              >
                <span>{isLaunching ? "Launching Match..." : "Launch Match"}</span>
                <ArrowRight className="h-4 w-4" />
              </button>

              <p className="mt-4 text-sm leading-6 text-slate-400">
                Launch stays locked until Ghost Protocol has a configured
                defender path. Police AI is instantly ready. Custom webhook mode
                requires a successful connectivity test first.
              </p>

              {launchError ? (
                <div className="mt-5 rounded-[24px] border border-rose-400/20 bg-rose-400/10 p-4 text-sm leading-6 text-rose-100">
                  {launchError}
                </div>
              ) : null}

              {launchSummary ? (
                <div className="mt-5 rounded-[24px] border border-emerald-400/20 bg-emerald-400/10 p-5">
                  <div className="flex items-center gap-3">
                    <div className="rounded-full border border-emerald-300/20 bg-emerald-400/10 p-2 text-emerald-100">
                      <ShieldCheck className="h-4 w-4" />
                    </div>
                    <div>
                      <p className="text-sm uppercase tracking-[0.22em] text-emerald-200/80">
                        Match Live
                      </p>
                      <p className="text-lg font-semibold text-emerald-50">
                        Sandbox launched successfully
                      </p>
                    </div>
                  </div>

                  <div className="mt-4 inline-flex items-center gap-2 rounded-full border border-emerald-200/20 bg-emerald-300/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-emerald-50">
                    <Share2 className="h-3.5 w-3.5" />
                    This browser is the owner view
                  </div>

                  <dl className="mt-4 grid gap-4 sm:grid-cols-2">
                    <div>
                      <dt className="text-xs uppercase tracking-[0.2em] text-emerald-100/70">
                        Match ID
                      </dt>
                      <dd className="mt-2 break-all font-mono text-sm text-emerald-50">
                        {launchSummary.matchId}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-xs uppercase tracking-[0.2em] text-emerald-100/70">
                        Status
                      </dt>
                      <dd className="mt-2 text-sm font-medium capitalize text-emerald-50">
                        {launchSummary.status}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-xs uppercase tracking-[0.2em] text-emerald-100/70">
                        Defender ID
                      </dt>
                      <dd className="mt-2 break-all font-mono text-sm text-emerald-50">
                        {launchSummary.defenderId}
                      </dd>
                    </div>
                    <div>
                      <dt className="text-xs uppercase tracking-[0.2em] text-emerald-100/70">
                        Share URL
                      </dt>
                      <dd className="mt-2 break-all font-mono text-sm text-emerald-50">
                        {launchSummary.absoluteShareUrl}
                      </dd>
                    </div>
                  </dl>

                  <div className="mt-5 flex flex-wrap gap-3">
                    <button
                      type="button"
                      onClick={handleCopyShareLink}
                      className="inline-flex items-center gap-2 rounded-full border border-emerald-200/20 bg-emerald-300/10 px-4 py-2 text-sm font-medium text-emerald-50 transition hover:bg-emerald-300/15"
                    >
                      <Copy className="h-4 w-4" />
                      {shareCopyState === "copied"
                        ? "Share link copied"
                        : shareCopyState === "failed"
                          ? "Copy failed"
                          : "Copy share link"}
                    </button>

                    <Link
                      href={launchSummary.shareUrl}
                      className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/10 px-4 py-2 text-sm font-medium text-emerald-50 transition hover:bg-white/15"
                    >
                      <ExternalLink className="h-4 w-4" />
                      Open War Room
                    </Link>

                    <Link
                      href="/scenarios"
                      className="inline-flex items-center gap-2 rounded-full border border-emerald-200/20 bg-emerald-300/10 px-4 py-2 text-sm font-medium text-emerald-50 transition hover:bg-emerald-300/15"
                    >
                      <ExternalLink className="h-4 w-4" />
                      Scenario Library
                    </Link>
                  </div>

                  <p className="mt-4 text-sm leading-6 text-emerald-50/80">
                    Anyone opening this share link from a different browser or
                    device gets a read-only match view.
                  </p>
                </div>
              ) : null}
            </section>
          </div>
        </section>
      </div>
    </main>
  );
}

function HomePageFallback() {
  return (
    <main className="px-6 py-8 sm:px-8 lg:px-12">
      <div className="mx-auto max-w-7xl">
        <div className="rounded-[32px] border border-white/10 bg-[rgba(15,22,41,0.82)] p-8 text-slate-200 shadow-[0_24px_80px_rgba(3,8,18,0.45)]">
          Loading setup...
        </div>
      </div>
    </main>
  );
}

export default function Home() {
  return (
    <Suspense fallback={<HomePageFallback />}>
      <HomeContent />
    </Suspense>
  );
}
