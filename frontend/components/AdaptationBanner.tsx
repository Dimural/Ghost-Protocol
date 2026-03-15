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
    className: "app-chip app-chip-accent",
  },
  live: {
    label: "Socket Live",
    className: "app-chip app-chip-success",
  },
  offline: {
    label: "Socket Offline",
    className: "app-chip",
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
    <section className="adaptation-banner-enter relative overflow-hidden rounded-[28px] border border-[rgba(207,176,122,0.24)] bg-[linear-gradient(180deg,rgba(31,24,17,0.92),rgba(20,22,28,0.95))] px-6 py-6 shadow-[0_24px_64px_rgba(0,0,0,0.24)]">
      <div className="pointer-events-none absolute inset-y-0 left-0 w-px bg-[rgba(207,176,122,0.45)]" />

      <div className="relative flex flex-wrap items-start justify-between gap-4">
        <div className="max-w-4xl">
          <div className="app-chip app-chip-warning">
            <Sparkles className="h-3.5 w-3.5" />
            Attacker Adapting
          </div>

          <div className="mt-4 flex flex-wrap items-center gap-3">
            <div className="app-chip app-chip-danger rounded-full p-3">
              <BrainCircuit className="h-5 w-5" />
            </div>
            <div>
              <h2 className="text-2xl font-semibold tracking-[0.02em] text-slate-50 sm:text-3xl">
                ATTACKER IS LEARNING... Round {notification.round} of{" "}
                {notification.total_rounds}
              </h2>
              <p className="mt-2 text-sm uppercase tracking-[0.2em] text-slate-400">
                {notification.banner_message}
              </p>
            </div>
          </div>

          <blockquote className="mt-5 max-w-3xl border-l border-white/10 pl-4 text-lg leading-8 text-slate-100">
            <span aria-hidden="true">&ldquo;</span>
            {notification.reasoning}
            <span aria-hidden="true">&rdquo;</span>
          </blockquote>

          <div className="mt-5 flex flex-wrap gap-3">
            <div className={connectionBadge.className}>
              <RadioTower className="h-3.5 w-3.5" />
              {connectionBadge.label}
            </div>
            <div className="app-chip">
              Triggered {formatNotificationTime(notification.created_at)}
            </div>
          </div>
        </div>

        <button
          type="button"
          onClick={onDismiss}
          className="app-button app-button-secondary h-10 w-10 p-0 text-slate-300 hover:text-slate-50"
          aria-label="Dismiss adaptation banner"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
    </section>
  );
}
