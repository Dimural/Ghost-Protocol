"use client";

import Link from "next/link";
import { Suspense, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import {
  ArrowDown,
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
    "Police AI is armed and ready to defend in mock mode with automatic live activation once a Groq key exists.",
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
    <main className="landing-shell relative overflow-hidden">
      <section className="landing-section">
        <div className="landing-grid">
          <div className="landing-frame home-reveal-up lg:col-span-2">
            <div className="landing-orbit" aria-hidden="true">
              <span className="landing-orbit-line landing-orbit-line-ghost" />
              <span className="landing-orbit-line landing-orbit-line-main" />
              <span className="landing-orbit-line landing-orbit-line-accent" />
            </div>

            <div className="relative z-10 flex min-h-[78svh] flex-col justify-between p-8 sm:p-12 lg:p-16">
              <div className="flex flex-wrap items-center gap-3">
                <div className="landing-pill landing-pill-accent">
                  <Siren className="h-3.5 w-3.5" />
                  Ghost Protocol
                </div>
                <div className="landing-pill">Adversarial fraud simulation</div>
              </div>

              <div className="max-w-5xl">
                <p className="text-xs uppercase tracking-[0.38em] text-slate-500">
                  Black-box pressure testing for fraud teams
                </p>
                <h1 className="mt-6 max-w-5xl text-6xl font-semibold leading-[0.92] tracking-[-0.05em] text-white sm:text-7xl lg:text-[7.5rem]">
                  Fraud defense is only real when the attacker evolves.
                </h1>
                <p className="mt-8 max-w-3xl text-base leading-8 text-slate-300 sm:text-lg">
                  Run a synthetic heist, route transactions into your detector,
                  and watch Ghost Protocol score every catch, miss, and blind
                  spot in a controlled sandbox designed for live adversarial
                  testing.
                </p>

                <div className="mt-10 flex flex-wrap gap-3">
                  <Link href="#configure" className="landing-button">
                    Begin setup
                    <ArrowRight className="h-4 w-4" />
                  </Link>
                  <Link
                    href="/scenarios"
                    className="landing-button landing-button-secondary"
                  >
                    <ExternalLink className="h-4 w-4" />
                    Scenario library
                  </Link>
                </div>
              </div>

              <div className="relative z-10 mt-12 grid gap-4 lg:grid-cols-[0.82fr_0.18fr] lg:items-end">
                <div className="grid gap-4 sm:grid-cols-3">
                  <div className="app-subpanel p-4">
                    <p className="text-xs uppercase tracking-[0.22em] text-slate-500">
                      Active backend
                    </p>
                    <p className="mt-2 break-all text-sm font-medium text-white">
                      {backendBaseUrl}
                    </p>
                  </div>
                  <div className="app-subpanel p-4">
                    <p className="text-xs uppercase tracking-[0.22em] text-slate-500">
                      Runtime path
                    </p>
                    <p className="mt-2 text-sm font-medium text-white">
                      Groq live with automatic mock fallback
                    </p>
                  </div>
                  <div className="app-subpanel p-4">
                    <p className="text-xs uppercase tracking-[0.22em] text-slate-500">
                      Match engine
                    </p>
                    <p className="mt-2 text-sm font-medium text-white">
                      Native Ghost Protocol sandbox
                    </p>
                  </div>
                </div>

                <div className="landing-scroll-cue flex items-center gap-3 text-xs uppercase tracking-[0.3em] text-slate-500">
                  <ArrowDown className="h-4 w-4" />
                  Scroll
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section id="configure" className="landing-section">
        <div className="landing-grid lg:items-start">
          <div className="home-reveal-up home-reveal-delay-1 space-y-6 lg:sticky lg:top-10">
            <div className="landing-frame p-8">
              <p className="text-xs uppercase tracking-[0.36em] text-slate-500">
                Section 01
              </p>
              <h2 className="mt-4 text-4xl font-semibold leading-tight text-white sm:text-5xl">
                Build the heist before you pull the trigger.
              </h2>
              <p className="mt-5 max-w-xl text-base leading-8 text-slate-300">
                Configure the attack profile, choose the defender path, and
                keep the entire flow on a single scroll narrative instead of a
                compressed dashboard block.
              </p>
            </div>

            <section className="app-panel p-6">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <p className="text-xs uppercase tracking-[0.28em] text-slate-500">
                    Sequence
                  </p>
                  <h3 className="mt-2 text-2xl font-semibold text-white">
                    Setup in three moves
                  </h3>
                </div>
                <div className="landing-pill landing-pill-accent rounded-full p-3">
                  <BrainCircuit className="h-5 w-5" />
                </div>
              </div>

              <div className="mt-6 space-y-3">
                {HOW_IT_WORKS.map((step) => {
                  const Icon = step.icon;

                  return (
                    <article
                      key={step.title}
                      className="app-subpanel flex items-start gap-4 p-4"
                    >
                      <div className="app-subpanel-strong rounded-2xl p-3 text-slate-100">
                        <Icon className="h-5 w-5" />
                      </div>
                      <div>
                        <h4 className="text-base font-semibold text-white">
                          {step.title}
                        </h4>
                        <p className="mt-2 text-sm leading-6 text-slate-300">
                          {step.description}
                        </p>
                      </div>
                    </article>
                  );
                })}
              </div>
            </section>
          </div>

          <div className="space-y-6">
            {cloneNotice ? (
              <section className="app-panel home-reveal-up home-reveal-delay-1 p-5">
                <div className="flex flex-wrap items-start justify-between gap-4">
                  <div>
                    <p className="text-xs uppercase tracking-[0.28em] text-slate-500">
                      {cloneNotice.state === "ready"
                        ? "Clone Loaded"
                        : "Clone Unavailable"}
                    </p>
                    <h2 className="mt-2 text-2xl font-semibold text-white">
                      {cloneNotice.state === "ready"
                        ? `Cloned from ${cloneNotice.scenarioName}`
                        : "Original scenario data could not be restored"}
                    </h2>
                  </div>
                  <div className="landing-pill">Source {cloneNotice.sourceMatchId}</div>
                </div>
                <p className="mt-4 max-w-3xl text-sm leading-6 text-slate-300">
                  {cloneNotice.detail}
                </p>
              </section>
            ) : null}

            <div className="home-reveal-up home-reveal-delay-2">
              <ScenarioSelector
                scenarios={SCENARIOS}
                selectedScenarioId={selectedScenarioId}
                onSelect={handleScenarioSelect}
              />
            </div>

            <div className="home-reveal-up home-reveal-delay-3">
              <DefenderSetup
                defenderMode={defenderMode}
                webhookUrl={webhookUrl}
                connectionStatus={connectionStatus}
                onModeChange={handleModeChange}
                onWebhookUrlChange={handleWebhookUrlChange}
                onTestConnection={handleTestConnection}
                isTesting={isTestingConnection}
              />
            </div>
          </div>
        </div>
      </section>

      <section id="launch" className="landing-section">
        <div className="landing-grid lg:items-start">
          <div className="home-reveal-up home-reveal-delay-1 space-y-6 lg:sticky lg:top-10">
            <div className="landing-frame p-8">
              <p className="text-xs uppercase tracking-[0.36em] text-slate-500">
                Section 02
              </p>
              <h2 className="mt-4 text-4xl font-semibold leading-tight text-white sm:text-5xl">
                Launch once the defender path is clean.
              </h2>
              <p className="mt-5 max-w-xl text-base leading-8 text-slate-300">
                This final section turns configuration into a live match, gives
                you the owner share link, and keeps the launch state visible in
                one dedicated stage.
              </p>
            </div>

            <section className="app-panel p-6">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div>
                  <p className="text-xs uppercase tracking-[0.28em] text-slate-500">
                    Current loadout
                  </p>
                  <h3 className="mt-2 text-2xl font-semibold text-white">
                    Match profile
                  </h3>
                </div>
                <div className="landing-pill landing-pill-accent">
                  <Radar className="h-3.5 w-3.5" />
                  {canLaunch ? "Ready to arm" : "Waiting on defender"}
                </div>
              </div>

              <dl className="mt-6 grid gap-4 sm:grid-cols-2">
                <div className="app-subpanel p-4">
                  <dt className="text-xs uppercase tracking-[0.22em] text-slate-500">
                    Scenario
                  </dt>
                  <dd className="mt-2 text-base font-medium text-white">
                    {selectedScenario.name}
                  </dd>
                </div>
                <div className="app-subpanel p-4">
                  <dt className="text-xs uppercase tracking-[0.22em] text-slate-500">
                    Defender mode
                  </dt>
                  <dd className="mt-2 text-base font-medium text-white">
                    {defenderMode === "police_ai" ? "Police AI" : "Webhook API"}
                  </dd>
                </div>
                <div className="app-subpanel p-4">
                  <dt className="text-xs uppercase tracking-[0.22em] text-slate-500">
                    Criminal persona
                  </dt>
                  <dd className="mt-2 text-base font-medium capitalize text-white">
                    {selectedScenario.criminalPersona}
                  </dd>
                </div>
                <div className="app-subpanel p-4">
                  <dt className="text-xs uppercase tracking-[0.22em] text-slate-500">
                    Attack rounds
                  </dt>
                  <dd className="mt-2 text-base font-medium text-white">
                    {selectedScenario.totalRounds}
                  </dd>
                </div>
              </dl>

              <div className="mt-5 flex flex-wrap gap-3">
                <Link href="/scenarios" className="landing-button landing-button-secondary">
                  <ExternalLink className="h-4 w-4" />
                  Review scenario library
                </Link>
              </div>
            </section>
          </div>

          <div className="space-y-6">
            <section className="app-panel home-reveal-up home-reveal-delay-2 p-6">
              <p className="text-xs uppercase tracking-[0.28em] text-slate-500">
                Launch Control
              </p>
              <h2 className="mt-2 text-2xl font-semibold text-white">
                Arm the sandbox
              </h2>

              <p className="mt-4 max-w-2xl text-sm leading-7 text-slate-300">
                Launch stays locked until Ghost Protocol has a configured
                defender path. Police AI is immediately ready. Custom webhook
                mode requires a successful connectivity test first.
              </p>

              <button
                type="button"
                onClick={handleLaunchMatch}
                disabled={!canLaunch || isLaunching}
                className="landing-button mt-8 w-full px-6 py-4 text-sm font-semibold uppercase tracking-[0.24em] disabled:cursor-not-allowed disabled:border-white/10 disabled:bg-white/5 disabled:text-slate-500"
              >
                <span>{isLaunching ? "Launching Match..." : "Launch Match"}</span>
                <ArrowRight className="h-4 w-4" />
              </button>

              {launchError ? (
                <div className="app-subpanel mt-5 border-[rgba(219,138,138,0.24)] bg-[rgba(219,138,138,0.11)] p-4 text-sm leading-6 text-rose-100">
                  {launchError}
                </div>
              ) : null}
            </section>

            {launchSummary ? (
              <div className="app-panel home-reveal-up home-reveal-delay-3 p-6">
                <div className="flex flex-wrap items-center justify-between gap-4">
                  <div className="flex items-center gap-3">
                    <div className="landing-pill landing-pill-accent rounded-full p-2">
                      <ShieldCheck className="h-4 w-4" />
                    </div>
                    <div>
                      <p className="text-xs uppercase tracking-[0.28em] text-slate-500">
                        Match Live
                      </p>
                      <p className="text-xl font-semibold text-white">
                        Sandbox launched successfully
                      </p>
                    </div>
                  </div>

                  <div className="landing-pill">
                    <Share2 className="h-3.5 w-3.5" />
                    Owner view
                  </div>
                </div>

                <dl className="mt-6 grid gap-4 sm:grid-cols-2">
                  <div className="app-subpanel p-4">
                    <dt className="text-xs uppercase tracking-[0.22em] text-slate-500">
                      Match ID
                    </dt>
                    <dd className="mt-2 break-all font-mono text-sm text-white">
                      {launchSummary.matchId}
                    </dd>
                  </div>
                  <div className="app-subpanel p-4">
                    <dt className="text-xs uppercase tracking-[0.22em] text-slate-500">
                      Status
                    </dt>
                    <dd className="mt-2 text-sm font-medium capitalize text-white">
                      {launchSummary.status}
                    </dd>
                  </div>
                  <div className="app-subpanel p-4">
                    <dt className="text-xs uppercase tracking-[0.22em] text-slate-500">
                      Defender ID
                    </dt>
                    <dd className="mt-2 break-all font-mono text-sm text-white">
                      {launchSummary.defenderId}
                    </dd>
                  </div>
                  <div className="app-subpanel p-4">
                    <dt className="text-xs uppercase tracking-[0.22em] text-slate-500">
                      Share URL
                    </dt>
                    <dd className="mt-2 break-all font-mono text-sm text-white">
                      {launchSummary.absoluteShareUrl}
                    </dd>
                  </div>
                </dl>

                <div className="mt-6 flex flex-wrap gap-3">
                  <button
                    type="button"
                    onClick={handleCopyShareLink}
                    className="landing-button"
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
                    className="landing-button landing-button-secondary"
                  >
                    <ExternalLink className="h-4 w-4" />
                    Open War Room
                  </Link>

                  <Link
                    href="/scenarios"
                    className="landing-button landing-button-secondary"
                  >
                    <ExternalLink className="h-4 w-4" />
                    Scenario Library
                  </Link>
                </div>

                <p className="mt-5 text-sm leading-6 text-slate-300">
                  Anyone opening this share link from a different browser or
                  device gets a read-only match view.
                </p>
              </div>
            ) : null}
          </div>
        </div>
      </section>
    </main>
  );
}

function HomePageFallback() {
  return (
    <main className="app-page">
      <div className="mx-auto max-w-7xl">
        <div className="app-panel p-8 text-slate-200">
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
