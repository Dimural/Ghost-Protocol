"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, Gauge, ShieldCheck, Siren } from "lucide-react";

type RiskMeterProps = {
  processedCount: number;
  processedFraudCount: number;
  falseNegatives: number;
};

type RiskBand = {
  label: string;
  description: string;
  color: string;
  panelClassName: string;
  badgeClassName: string;
};

const GAUGE_RADIUS = 78;
const GAUGE_CIRCUMFERENCE = 2 * Math.PI * GAUGE_RADIUS;

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function calculateThreatLevel(
  falseNegatives: number,
  processedFraudCount: number,
): number {
  if (processedFraudCount === 0) {
    return 0;
  }

  return Math.round(
    clamp((falseNegatives / processedFraudCount) * 100, 0, 100),
  );
}

function getRiskBand(threatLevel: number): RiskBand {
  if (threatLevel >= 81) {
    return {
      label: "BREACH IN PROGRESS",
      description: "Missed fraud is overwhelming the defender.",
      color: "#ff3b3b",
      panelClassName: "bg-[rgba(255,255,255,0.04)]",
      badgeClassName:
        "app-chip app-chip-danger risk-meter-breach",
    };
  }

  if (threatLevel >= 61) {
    return {
      label: "Under Attack",
      description: "Missed fraud is compounding fast enough to threaten the match.",
      color: "#fb923c",
      panelClassName: "bg-[rgba(255,255,255,0.04)]",
      badgeClassName:
        "app-chip app-chip-warning",
    };
  }

  if (threatLevel >= 31) {
    return {
      label: "Anomalies Detected",
      description: "The defender is leaking suspicious traffic, but the breach is not runaway yet.",
      color: "#ffd700",
      panelClassName: "bg-[rgba(255,255,255,0.04)]",
      badgeClassName:
        "app-chip app-chip-warning",
    };
  }

  return {
      label: "System Secure",
      description: "Most processed fraud is being contained before it gets through.",
      color: "#00ff88",
      panelClassName: "bg-[rgba(255,255,255,0.04)]",
    badgeClassName:
      "app-chip app-chip-success",
  };
}

function getNextCheckpoint(processedCount: number): number {
  if (processedCount < 5) {
    return 5;
  }

  return Math.floor(processedCount / 5) * 5 + 5;
}

export function RiskMeter({
  processedCount,
  processedFraudCount,
  falseNegatives,
}: RiskMeterProps) {
  const [displayedThreatLevel, setDisplayedThreatLevel] = useState(0);
  const [lastCheckpoint, setLastCheckpoint] = useState(0);
  const actualThreatLevel = calculateThreatLevel(
    falseNegatives,
    processedFraudCount,
  );

  useEffect(() => {
    if (processedCount === 0) {
      setDisplayedThreatLevel(0);
      setLastCheckpoint(0);
      return;
    }

    if (lastCheckpoint === 0 || processedCount < lastCheckpoint) {
      setDisplayedThreatLevel(actualThreatLevel);
      setLastCheckpoint(processedCount);
      return;
    }

    const isCheckpoint = processedCount < 5 || processedCount % 5 === 0;
    if (isCheckpoint && processedCount !== lastCheckpoint) {
      setDisplayedThreatLevel(actualThreatLevel);
      setLastCheckpoint(processedCount);
    }
  }, [actualThreatLevel, lastCheckpoint, processedCount]);

  const riskBand = getRiskBand(displayedThreatLevel);
  const dashOffset =
    GAUGE_CIRCUMFERENCE * (1 - clamp(displayedThreatLevel / 100, 0, 1));
  const gaugeProgressStyle = {
    strokeDasharray: GAUGE_CIRCUMFERENCE,
    strokeDashoffset: dashOffset,
    stroke: riskBand.color,
  };
  const gaugeFaceStyle = {
    background: `radial-gradient(circle at 50% 35%, rgba(255,255,255,0.12), rgba(15,22,41,0.95) 58%), conic-gradient(from 220deg, ${riskBand.color}22 0deg, ${riskBand.color} 80deg, rgba(255,255,255,0.06) 240deg, rgba(255,255,255,0.02) 360deg)`,
  };
  const nextCheckpoint = getNextCheckpoint(processedCount);
  const holdCount = Math.max(nextCheckpoint - processedCount, 0);

  return (
    <section
      className={`app-panel p-6 transition ${riskBand.panelClassName}`}
    >
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-xs uppercase tracking-[0.32em] text-slate-500">
            Section Threat
          </p>
          <h2 className="mt-2 text-2xl font-semibold text-slate-50">
            Real-time risk meter
          </h2>
          <p className="mt-3 max-w-xl text-sm leading-7 text-slate-300">
            A live signal of how much fraud is slipping through.
          </p>
        </div>

        <div className="landing-pill landing-pill-accent rounded-full p-3">
          <Gauge className="h-5 w-5" />
        </div>
      </div>

      <div className="mt-8 grid gap-8 lg:grid-cols-[1.15fr_0.85fr] lg:items-center">
        <div className="flex justify-center">
          <div className="relative h-[19rem] w-[19rem]">
            <div
              className="absolute inset-0 rounded-full shadow-[inset_0_0_24px_rgba(255,255,255,0.03)]"
              style={gaugeFaceStyle}
            />

            <svg
              viewBox="0 0 220 220"
              className="absolute inset-0 h-full w-full -rotate-90"
              aria-hidden="true"
            >
              <circle
                cx="110"
                cy="110"
                r={GAUGE_RADIUS}
                fill="none"
                stroke="rgba(255,255,255,0.09)"
                strokeWidth="14"
              />
              <circle
                cx="110"
                cy="110"
                r={GAUGE_RADIUS}
                fill="none"
                strokeWidth="14"
                strokeLinecap="round"
                className="transition-all duration-700 ease-out"
                style={gaugeProgressStyle}
              />
            </svg>

            <div className="absolute inset-[22%] rounded-full bg-[rgba(12,14,19,0.92)] shadow-[inset_0_0_18px_rgba(255,255,255,0.02)]" />

            <div className="absolute inset-0 flex flex-col items-center justify-center text-center">
              <p className="text-xs uppercase tracking-[0.24em] text-slate-400">
                Threat Level
              </p>
              <div className="mt-3 flex items-start justify-center gap-1">
                <span className="text-6xl font-semibold leading-none text-slate-50">
                  {displayedThreatLevel}
                </span>
                <span className="pt-1 text-lg font-medium text-slate-400">
                  /100
                </span>
              </div>
              <div className={`mt-4 ${riskBand.badgeClassName}`}>
                {displayedThreatLevel >= 81 ? (
                  <Siren className="h-3.5 w-3.5" />
                ) : displayedThreatLevel >= 31 ? (
                  <AlertTriangle className="h-3.5 w-3.5" />
                ) : (
                  <ShieldCheck className="h-3.5 w-3.5" />
                )}
                {riskBand.label}
              </div>
            </div>

            <div className="pointer-events-none absolute inset-x-5 bottom-5 flex justify-between text-xs uppercase tracking-[0.18em] text-slate-500">
              <span>0</span>
              <span>25</span>
              <span>50</span>
              <span>75</span>
              <span>100</span>
            </div>
          </div>
        </div>

        <div className="space-y-4">
          <div className="app-subpanel p-5">
            <p className="text-sm font-medium text-slate-100">
              {riskBand.description}
            </p>
            <p className="mt-3 text-sm leading-6 text-slate-400">
              Updates as the match unfolds.
            </p>
          </div>

          <div className="grid gap-4 sm:grid-cols-2">
            <div className="app-subpanel p-4">
              <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
                Missed Fraud
              </p>
              <p className="mt-2 text-2xl font-semibold text-slate-50">
                {falseNegatives}
              </p>
            </div>
            <div className="app-subpanel p-4">
              <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
                Processed Fraud
              </p>
              <p className="mt-2 text-2xl font-semibold text-slate-50">
                {processedFraudCount}
              </p>
            </div>
          </div>

          <div className="app-subpanel p-5">
            <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
              Refresh Cadence
            </p>
            <p className="mt-2 text-base font-medium text-slate-50">
              Last recalculation at {lastCheckpoint} processed transactions
            </p>
            <p className="mt-3 text-sm leading-6 text-slate-400">
              {processedCount === 0
                ? "Waiting for the first decisions."
                : holdCount === 0
                  ? `Next refresh at ${nextCheckpoint} processed transactions.`
                  : `Holding for ${holdCount} more transaction${holdCount === 1 ? "" : "s"}.`}
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
