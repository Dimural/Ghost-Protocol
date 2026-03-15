import type { CSSProperties } from "react";
import type { LucideIcon } from "lucide-react";
import {
  ArrowRightLeft,
  Banknote,
  BriefcaseBusiness,
  BusFront,
  Check,
  CreditCard,
  HeartPulse,
  Home,
  Landmark,
  MapPinned,
  Package,
  Pill,
  Plane,
  ShoppingBasket,
  ShoppingCart,
  Smartphone,
  Store,
  UtensilsCrossed,
  Wallet,
  X,
} from "lucide-react";

import type {
  DefenderDecisionPayload,
  OutcomeLabel,
  TransactionPayload,
} from "@/lib/websocket";

export type FeedConnectionState = "connecting" | "live" | "offline";

export type TransactionFeedItem = {
  id: string;
  transaction: TransactionPayload;
  defenderDecision: DefenderDecisionPayload;
  isCorrect: boolean;
  outcome: OutcomeLabel;
  source: "history" | "live";
};

type TransactionFeedProps = {
  entries: TransactionFeedItem[];
  processedCount: number;
  connectionState: FeedConnectionState;
};

type UserChip = {
  label: string;
  initials: string;
  accentClass: string;
  ringClass: string;
};

const USER_CHIPS: Record<string, UserChip> = {
  ghost_student: {
    label: "Alex C.",
    initials: "AC",
    accentClass: "bg-cyan-400/15 text-cyan-100",
    ringClass: "ring-cyan-300/25",
  },
  ghost_professional: {
    label: "Priya S.",
    initials: "PS",
    accentClass: "bg-emerald-400/15 text-emerald-100",
    ringClass: "ring-emerald-300/25",
  },
  ghost_retiree: {
    label: "Harold W.",
    initials: "HW",
    accentClass: "bg-amber-300/15 text-amber-100",
    ringClass: "ring-amber-300/25",
  },
  ghost_business: {
    label: "Sofia M.",
    initials: "SM",
    accentClass: "bg-rose-400/15 text-rose-100",
    ringClass: "ring-rose-300/25",
  },
  ghost_newcomer: {
    label: "James O.",
    initials: "JO",
    accentClass: "bg-blue-400/15 text-blue-100",
    ringClass: "ring-blue-300/25",
  },
};

const CONNECTION_BADGES: Record<
  FeedConnectionState,
  { label: string; className: string }
> = {
  connecting: {
    label: "Connecting",
    className: "border-amber-300/20 bg-amber-300/10 text-amber-100",
  },
  live: {
    label: "Live",
    className: "border-emerald-300/20 bg-emerald-400/10 text-emerald-100",
  },
  offline: {
    label: "Offline",
    className: "border-slate-300/20 bg-slate-400/10 text-slate-200",
  },
};

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
  }).format(new Date(timestamp));
}

function resolveUserChip(userId: string): UserChip {
  return (
    USER_CHIPS[userId] || {
      label: userId.replace(/_/g, " "),
      initials: userId.slice(0, 2).toUpperCase(),
      accentClass: "bg-slate-300/10 text-slate-100",
      ringClass: "ring-slate-300/20",
    }
  );
}

function resolveCountryCode(country: string): string | null {
  const normalized = country.trim().toLowerCase();
  const countryCodes: Record<string, string> = {
    canada: "CA",
    "united states": "US",
    usa: "US",
    us: "US",
    russia: "RU",
    nigeria: "NG",
    china: "CN",
    romania: "RO",
    mexico: "MX",
    france: "FR",
    germany: "DE",
    japan: "JP",
    australia: "AU",
    brazil: "BR",
    "united kingdom": "GB",
    uk: "GB",
    india: "IN",
    singapore: "SG",
    netherlands: "NL",
    "united arab emirates": "AE",
    uae: "AE",
  };

  return countryCodes[normalized] || null;
}

function toFlagEmoji(country: string): string {
  const code = resolveCountryCode(country);
  if (!code) {
    return "🏳";
  }

  return code
    .toUpperCase()
    .split("")
    .map((letter) => String.fromCodePoint(letter.charCodeAt(0) + 127397))
    .join("");
}

function pickCategoryIcon(category: string): LucideIcon {
  const normalized = category.trim().toLowerCase();

  if (normalized.includes("food") || normalized.includes("restaurant")) {
    return UtensilsCrossed;
  }
  if (normalized.includes("grocery")) {
    return ShoppingBasket;
  }
  if (normalized.includes("transit")) {
    return BusFront;
  }
  if (normalized.includes("streaming") || normalized.includes("cell")) {
    return Smartphone;
  }
  if (normalized.includes("travel")) {
    return Plane;
  }
  if (normalized.includes("medical")) {
    return HeartPulse;
  }
  if (normalized.includes("pharmacy")) {
    return Pill;
  }
  if (normalized.includes("utility") || normalized.includes("loan")) {
    return Home;
  }
  if (normalized.includes("payroll")) {
    return Wallet;
  }
  if (normalized.includes("supplier") || normalized.includes("equipment")) {
    return BriefcaseBusiness;
  }
  if (normalized.includes("transfer") || normalized.includes("remittance")) {
    return ArrowRightLeft;
  }
  if (normalized.includes("withdrawal")) {
    return Landmark;
  }
  if (normalized.includes("shopping") || normalized.includes("textbook")) {
    return ShoppingCart;
  }
  if (normalized.includes("gym")) {
    return HeartPulse;
  }
  if (normalized.includes("alcohol")) {
    return Store;
  }
  if (normalized.includes("purchase")) {
    return CreditCard;
  }

  return Package;
}

function buildRowAnimation(item: TransactionFeedItem): CSSProperties["animation"] {
  const animations: string[] = [];

  if (item.source === "live") {
    animations.push("feed-row-enter 420ms cubic-bezier(0.16, 1, 0.3, 1)");
  }

  if (!item.isCorrect) {
    animations.push("feed-row-alert 1100ms ease-out");
  }

  return animations.length > 0 ? animations.join(", ") : undefined;
}

export function TransactionFeed({
  entries,
  processedCount,
  connectionState,
}: TransactionFeedProps) {
  const connectionBadge = CONNECTION_BADGES[connectionState];

  return (
    <section className="rounded-[28px] border border-white/10 bg-[rgba(15,22,41,0.84)] p-6 shadow-[0_24px_80px_rgba(3,8,18,0.45)] backdrop-blur">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-xs uppercase tracking-[0.32em] text-cyan-300/80">
            Left Panel
          </p>
          <h2 className="mt-2 text-2xl font-semibold text-slate-50">
            Live transaction feed
          </h2>
          <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-400">
            Latest defender decisions appear at the top. Fraud rows glow red,
            misses flare amber, and older entries fade out to keep the signal
            dense.
          </p>
        </div>

        <div className="space-y-3">
          <div
            className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-medium uppercase tracking-[0.22em] ${connectionBadge.className}`}
          >
            <span className="h-2 w-2 rounded-full bg-current" />
            {connectionBadge.label}
          </div>
          <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-right">
            <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
              Processed
            </p>
            <p className="mt-2 text-2xl font-semibold text-slate-50">
              {processedCount}
            </p>
          </div>
        </div>
      </div>

      <div className="mt-6 max-h-[calc(100vh-14rem)] min-h-[28rem] space-y-3 overflow-y-auto pr-2">
        {entries.length === 0 ? (
          <div className="flex h-full min-h-[28rem] items-center justify-center rounded-[24px] border border-dashed border-white/12 bg-slate-950/35 px-8 text-center">
            <div className="max-w-md">
              <p className="text-sm uppercase tracking-[0.24em] text-slate-500">
                Awaiting traffic
              </p>
              <p className="mt-4 text-lg font-medium text-slate-100">
                No processed transactions yet.
              </p>
              <p className="mt-3 text-sm leading-6 text-slate-400">
                Once the defender starts approving or denying transactions, this
                panel will stream the latest 50 with ground-truth reveal and
                accuracy badges.
              </p>
            </div>
          </div>
        ) : (
          entries.map((item, index) => {
            const user = resolveUserChip(item.transaction.user_id);
            const CategoryIcon = pickCategoryIcon(item.transaction.category);
            const opacity = Math.max(0.34, 1 - index * 0.055);
            const isFraud = item.transaction.is_fraud;
            const decisionDenied = item.defenderDecision.decision === "DENY";

            return (
              <article
                key={item.id}
                className={`rounded-[24px] border border-white/10 px-4 py-4 transition ${
                  isFraud
                    ? "border-l-4 border-l-rose-400 bg-rose-400/[0.08] shadow-[0_0_34px_rgba(255,59,59,0.08)]"
                    : "border-l-4 border-l-cyan-400/0 bg-white/[0.03]"
                } ${!item.isCorrect ? "ring-1 ring-amber-300/20" : ""}`}
                style={{
                  opacity,
                  animation: buildRowAnimation(item),
                }}
              >
                <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
                  <div className="flex min-w-0 items-start gap-4">
                    <div
                      className={`flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl ring-1 ${user.accentClass} ${user.ringClass}`}
                    >
                      <span className="text-sm font-semibold">
                        {user.initials}
                      </span>
                    </div>

                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2 text-xs uppercase tracking-[0.18em] text-slate-500">
                        <span>{formatTimestamp(item.transaction.timestamp)}</span>
                        <span className="h-1 w-1 rounded-full bg-slate-600" />
                        <span>{user.label}</span>
                      </div>

                      <div className="mt-2 flex flex-wrap items-center gap-3">
                        <div className="inline-flex items-center gap-2 text-slate-50">
                          <div className="rounded-xl border border-white/10 bg-white/5 p-2 text-cyan-100">
                            <CategoryIcon className="h-4 w-4" />
                          </div>
                          <div className="min-w-0">
                            <p className="truncate text-base font-semibold">
                              {item.transaction.merchant}
                            </p>
                            <p className="text-sm text-slate-400">
                              {item.transaction.category}
                            </p>
                          </div>
                        </div>

                        <div className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-slate-950/55 px-3 py-1.5 text-sm text-slate-200">
                          <MapPinned className="h-4 w-4 text-slate-400" />
                          <span>
                            {toFlagEmoji(item.transaction.location_country)}{" "}
                            {item.transaction.location_city},{" "}
                            {item.transaction.location_country}
                          </span>
                        </div>
                      </div>
                    </div>
                  </div>

                  <div className="flex flex-wrap items-center gap-2 xl:justify-end">
                    <div className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-slate-950/55 px-3 py-2 text-sm font-medium text-slate-100">
                      <Banknote className="h-4 w-4 text-cyan-200" />
                      {formatAmount(
                        item.transaction.amount,
                        item.transaction.currency,
                      )}
                    </div>

                    <div
                      className={`inline-flex items-center gap-2 rounded-full border px-3 py-2 text-xs font-semibold uppercase tracking-[0.16em] ${
                        decisionDenied
                          ? "border-rose-300/20 bg-rose-400/10 text-rose-100"
                          : "border-emerald-300/20 bg-emerald-400/10 text-emerald-100"
                      }`}
                    >
                      {decisionDenied ? (
                        <X className="h-3.5 w-3.5" />
                      ) : (
                        <Check className="h-3.5 w-3.5" />
                      )}
                      {decisionDenied ? "Denied" : "Approved"}
                    </div>

                    <div
                      className={`inline-flex items-center gap-2 rounded-full border px-3 py-2 text-xs font-semibold uppercase tracking-[0.16em] ${
                        isFraud
                          ? "border-rose-300/20 bg-rose-400/10 text-rose-100"
                          : "border-slate-300/20 bg-white/5 text-slate-200"
                      }`}
                    >
                      {isFraud ? (
                        <CreditCard className="h-3.5 w-3.5" />
                      ) : (
                        <Store className="h-3.5 w-3.5" />
                      )}
                      {isFraud ? "Fraud" : "Legit"}
                    </div>

                    <div
                      className={`inline-flex items-center gap-2 rounded-full border px-3 py-2 text-xs font-semibold uppercase tracking-[0.16em] ${
                        item.isCorrect
                          ? "border-emerald-300/20 bg-emerald-400/10 text-emerald-100"
                          : "border-amber-300/20 bg-amber-300/10 text-amber-100"
                      }`}
                    >
                      {item.isCorrect ? (
                        <Check className="h-3.5 w-3.5" />
                      ) : (
                        <X className="h-3.5 w-3.5" />
                      )}
                      {item.isCorrect ? "Correct" : "Wrong"}
                    </div>
                  </div>
                </div>
              </article>
            );
          })
        )}
      </div>
    </section>
  );
}
