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
  idle: "border-slate-400/20 bg-slate-400/10 text-slate-300",
  ready: "border-emerald-400/20 bg-emerald-400/10 text-emerald-200",
  testing: "border-amber-400/20 bg-amber-400/10 text-amber-200",
  success: "border-emerald-400/20 bg-emerald-400/10 text-emerald-200",
  error: "border-rose-400/20 bg-rose-400/10 text-rose-200",
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
    <section className="rounded-[28px] border border-white/10 bg-[rgba(15,22,41,0.8)] p-6 shadow-[0_24px_80px_rgba(3,8,18,0.45)] backdrop-blur">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-[0.32em] text-cyan-300/80">
            Defender Setup
          </p>
          <h2 className="mt-2 text-2xl font-semibold text-slate-50">
            Pick how the blue team responds
          </h2>
        </div>
        <div
          className={`rounded-full border px-3 py-1 text-xs font-medium uppercase tracking-[0.22em] ${badgeStyles[connectionStatus.state]}`}
        >
          {connectionStatus.label}
        </div>
      </div>

      <div className="mt-5 grid gap-3 sm:grid-cols-2">
        <button
          type="button"
          onClick={() => onModeChange("police_ai")}
          className={`rounded-[24px] border p-4 text-left transition ${
            defenderMode === "police_ai"
              ? "border-emerald-300/40 bg-emerald-400/10 shadow-[0_0_0_1px_rgba(52,211,153,0.2)]"
              : "border-white/10 bg-slate-950/40 hover:border-cyan-300/30"
          }`}
        >
          <p className="text-base font-semibold text-slate-50">Use Police AI</p>
          <p className="mt-2 text-sm leading-6 text-slate-300">
            Launch instantly with Ghost Protocol&apos;s built-in fallback
            defender. No webhook required.
          </p>
        </button>

        <button
          type="button"
          onClick={() => onModeChange("webhook")}
          className={`rounded-[24px] border p-4 text-left transition ${
            defenderMode === "webhook"
              ? "border-cyan-300/40 bg-cyan-400/10 shadow-[0_0_0_1px_rgba(34,211,238,0.18)]"
              : "border-white/10 bg-slate-950/40 hover:border-cyan-300/30"
          }`}
        >
          <p className="text-base font-semibold text-slate-50">
            Use my own API
          </p>
          <p className="mt-2 text-sm leading-6 text-slate-300">
            Send transaction payloads to your fraud endpoint and collect
            APPROVE or DENY decisions in real time.
          </p>
        </button>
      </div>

      <div className="mt-5 rounded-[24px] border border-white/10 bg-slate-950/45 p-5">
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
                className="w-full rounded-2xl border border-white/10 bg-slate-950/70 px-4 py-3 text-base text-slate-100 outline-none transition focus:border-cyan-300/60 focus:ring-2 focus:ring-cyan-400/20"
              />
            </label>

            <div className="mt-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <p className="max-w-xl text-sm leading-6 text-slate-400">
                Ghost Protocol sends defender-safe transaction JSON and expects
                a matching `transaction_id`, `decision`, and `confidence` in
                return.
              </p>
              <button
                type="button"
                onClick={onTestConnection}
                disabled={isTesting || webhookUrl.trim().length === 0}
                className="inline-flex items-center justify-center rounded-full border border-cyan-300/30 bg-cyan-400/10 px-5 py-2.5 text-sm font-medium text-cyan-100 transition hover:bg-cyan-400/18 disabled:cursor-not-allowed disabled:border-white/10 disabled:bg-white/5 disabled:text-slate-500"
              >
                {isTesting ? "Testing..." : "Test Connection"}
              </button>
            </div>
          </>
        ) : (
          <div className="space-y-3">
            <p className="text-sm leading-6 text-slate-300">
              Police AI is pre-wired for mock mode and will automatically switch
              to live Gemini-backed reasoning once `GEMINI_API_KEY` is present.
            </p>
            <p className="text-sm leading-6 text-slate-400">
              This path is the safest demo default because it avoids external
              network dependencies while keeping the launch flow intact.
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
