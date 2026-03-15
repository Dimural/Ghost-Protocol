type DefenderMode = "police_ai" | "webhook";

export type ConnectionStatus = {
  state: "idle" | "ready" | "testing" | "success" | "error";
  label: string;
  detail: string;
};

type DefenderSetupProps = {
  defenderMode: DefenderMode;
  webhookUrl: string;
  connectionStatus: ConnectionStatus;
  onModeChange: (mode: DefenderMode) => void;
  onWebhookUrlChange: (value: string) => void;
  onTestConnection: () => void;
  isTesting: boolean;
};

const badgeStyles = {
  idle: "landing-pill",
  ready: "landing-pill landing-pill-accent",
  testing: "landing-pill",
  success: "landing-pill landing-pill-accent",
  error: "app-chip app-chip-danger",
} as const;

export function DefenderSetup({
  defenderMode,
  webhookUrl,
  connectionStatus,
  onModeChange,
  onWebhookUrlChange,
  onTestConnection,
  isTesting,
}: DefenderSetupProps) {
  const isWebhookMode = defenderMode === "webhook";

  return (
    <section className="app-panel p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-[0.28em] text-slate-500">
            Defender Setup
          </p>
          <h2 className="mt-2 text-2xl font-semibold text-slate-50">
            Pick how the blue team responds
          </h2>
        </div>
        <div className={badgeStyles[connectionStatus.state]}>
          {connectionStatus.label}
        </div>
      </div>

      <div className="mt-5 grid gap-3 sm:grid-cols-2">
        <button
          type="button"
          onClick={() => onModeChange("police_ai")}
          className={`rounded-[24px] border p-4 text-left transition ${
            defenderMode === "police_ai"
              ? "border-[rgba(214,255,87,0.26)] bg-[rgba(214,255,87,0.08)]"
              : "border-white/10 bg-[rgba(255,255,255,0.03)] hover:border-white/20"
          }`}
        >
          <p className="text-base font-semibold text-slate-50">Use Police AI</p>
          <p className="mt-2 text-sm leading-6 text-slate-300">
            Launch instantly with Ghost Protocol&apos;s built-in fallback
            defender. No setup needed.
          </p>
        </button>

        <button
          type="button"
          onClick={() => onModeChange("webhook")}
          className={`rounded-[24px] border p-4 text-left transition ${
            defenderMode === "webhook"
              ? "border-[rgba(214,255,87,0.26)] bg-[rgba(214,255,87,0.08)]"
              : "border-white/10 bg-[rgba(255,255,255,0.03)] hover:border-white/20"
          }`}
        >
          <p className="text-base font-semibold text-slate-50">
            Use my own API
          </p>
          <p className="mt-2 text-sm leading-6 text-slate-300">
            Send transaction payloads to your fraud endpoint and collect
            decisions in real time.
          </p>
        </button>
      </div>

      <div className="app-subpanel mt-5 p-5">
        {isWebhookMode ? (
          <>
            <label className="block">
              <span className="mb-2 block text-sm font-medium text-slate-200">
                Defender webhook URL
              </span>
              <input
                type="url"
                placeholder="https://your-defender.example.com/score"
                value={webhookUrl}
                onChange={(event) => onWebhookUrlChange(event.target.value)}
                className="app-input text-base"
              />
            </label>

            <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <p className="max-w-xl text-sm leading-6 text-slate-400">
                Ghost Protocol sends a transaction payload and expects a valid response back.
              </p>
              <button
                type="button"
                onClick={onTestConnection}
                disabled={isTesting || webhookUrl.trim().length === 0}
                className="landing-button disabled:cursor-not-allowed disabled:border-white/10 disabled:bg-white/5 disabled:text-slate-500"
              >
                {isTesting ? "Testing..." : "Test Connection"}
              </button>
            </div>
          </>
        ) : (
          <div className="space-y-3">
            <p className="text-sm leading-6 text-slate-300">
              Police AI is built in and ready for immediate use.
            </p>
            <p className="text-sm leading-6 text-slate-400">
              It keeps the launch flow simple and direct.
            </p>
          </div>
        )}
      </div>

      <p className="mt-4 text-sm leading-6 text-slate-400">
        {connectionStatus.detail}
      </p>
    </section>
  );
}
