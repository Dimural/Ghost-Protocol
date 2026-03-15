"use client";

import { BrainCircuit, RadioTower, Sparkles, X } from "lucide-react";

import type {
  AttackerAdaptingMessage,
  SocketConnectionState,
} from "@/lib/websocket";

type AdaptationBannerProps = {
  notification: AttackerAdaptingMessage;
  connectionState: SocketConnectionState;
  onDismiss: () => void;
};

const CONNECTION_LABELS: Record<
  SocketConnectionState,
  { label: string; className: string }
> = {
  connecting: {
    label: "Socket Syncing",
    className: "border-cyan-300/20 bg-cyan-400/10 text-cyan-100",
  },
  live: {
    label: "Socket Live",
    className: "border-emerald-300/20 bg-emerald-400/10 text-emerald-100",
  },
  offline: {
    label: "Socket Offline",
    className: "border-slate-300/20 bg-slate-400/10 text-slate-200",
  },
};

function formatNotificationTime(timestamp: string): string {
  return new Intl.DateTimeFormat("en-CA", {
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(timestamp));
}

export function AdaptationBanner({
  notification,
  connectionState,
  onDismiss,
}: AdaptationBannerProps) {
  const connectionBadge = CONNECTION_LABELS[connectionState];

  return (
    <section className="adaptation-banner-enter adaptation-banner-glow relative overflow-hidden rounded-[32px] border border-amber-300/20 bg-[linear-gradient(140deg,rgba(58,17,7,0.94),rgba(36,12,8,0.96)_38%,rgba(11,18,33,0.98))] px-6 py-6 shadow-[0_30px_90px_rgba(3,8,18,0.52)]">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(255,215,0,0.16),transparent_26%),radial-gradient(circle_at_80%_30%,rgba(0,212,255,0.14),transparent_28%)]" />
      <div className="adaptation-banner-scan pointer-events-none absolute inset-y-0 left-[-24%] w-[26%] bg-[linear-gradient(90deg,transparent,rgba(255,255,255,0.18),transparent)] blur-xl" />
      <div className="pointer-events-none absolute inset-0 opacity-30 [background-image:linear-gradient(rgba(255,255,255,0.08)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.08)_1px,transparent_1px)] [background-size:56px_56px]" />

      <div className="relative flex flex-wrap items-start justify-between gap-4">
        <div className="max-w-4xl">
          <div className="inline-flex items-center gap-2 rounded-full border border-amber-300/20 bg-amber-300/10 px-3 py-1 text-xs font-semibold uppercase tracking-[0.22em] text-amber-100">
            <Sparkles className="h-3.5 w-3.5" />
            Attacker Adapting
          </div>

          <div className="mt-4 flex flex-wrap items-center gap-3">
            <div className="rounded-full border border-rose-300/20 bg-rose-400/10 p-3 text-rose-100">
              <BrainCircuit className="h-5 w-5" />
            </div>
            <div>
              <h2 className="text-2xl font-semibold tracking-[0.02em] text-slate-50 sm:text-3xl">
                ATTACKER IS LEARNING... Round {notification.round} of{" "}
                {notification.total_rounds}
              </h2>
              <p className="mt-2 text-sm uppercase tracking-[0.22em] text-slate-300/80">
                {notification.banner_message}
              </p>
            </div>
          </div>

          <blockquote className="mt-5 max-w-3xl border-l border-amber-300/20 pl-4 text-lg leading-8 text-slate-100">
            <span aria-hidden="true">&ldquo;</span>
            {notification.reasoning}
            <span aria-hidden="true">&rdquo;</span>
          </blockquote>

          <div className="mt-5 flex flex-wrap gap-3">
            <div
              className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-semibold uppercase tracking-[0.18em] ${connectionBadge.className}`}
            >
              <RadioTower className="h-3.5 w-3.5" />
              {connectionBadge.label}
            </div>
            <div className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1.5 text-xs font-medium uppercase tracking-[0.18em] text-slate-200">
              Triggered {formatNotificationTime(notification.created_at)}
            </div>
          </div>
        </div>

        <button
          type="button"
          onClick={onDismiss}
          className="inline-flex items-center justify-center rounded-full border border-white/10 bg-white/5 p-2 text-slate-300 transition hover:border-white/20 hover:bg-white/10 hover:text-slate-50"
          aria-label="Dismiss adaptation banner"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
    </section>
  );
}
