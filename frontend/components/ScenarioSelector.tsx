import {
  Clock3,
  Fingerprint,
  Network,
  Radar,
  ShieldAlert,
} from "lucide-react";

import type { ScenarioDefinition } from "@/lib/scenarios";

type ScenarioSelectorProps = {
  scenarios: ScenarioDefinition[];
  selectedScenarioId: string;
  onSelect: (scenarioId: string) => void;
};

const personaIcons = {
  amateur: ShieldAlert,
  patient: Fingerprint,
  botnet: Network,
} as const;

export function ScenarioSelector({
  scenarios,
  selectedScenarioId,
  onSelect,
}: ScenarioSelectorProps) {
  const selectedScenario =
    scenarios.find((scenario) => scenario.id === selectedScenarioId) ??
    scenarios[0];
  const PersonaIcon = personaIcons[selectedScenario.criminalPersona];

  return (
    <section className="rounded-[28px] border border-white/10 bg-[rgba(15,22,41,0.8)] p-6 shadow-[0_24px_80px_rgba(3,8,18,0.45)] backdrop-blur">
      <div className="mb-5 flex items-start justify-between gap-4">
        <div>
          <p className="text-xs uppercase tracking-[0.32em] text-cyan-300/80">
            Scenario Selection
          </p>
          <h2 className="mt-2 text-2xl font-semibold text-slate-50">
            Choose the heist profile
          </h2>
        </div>
        <div className="rounded-full border border-cyan-400/20 bg-cyan-400/10 p-3 text-cyan-200">
          <Radar className="h-5 w-5" />
        </div>
      </div>

      <label className="block">
        <span className="mb-2 block text-sm font-medium text-slate-200">
          Scenario
        </span>
        <select
          className="w-full rounded-2xl border border-white/10 bg-slate-950/70 px-4 py-3 text-base text-slate-100 outline-none transition focus:border-cyan-300/60 focus:ring-2 focus:ring-cyan-400/20"
          value={selectedScenarioId}
          onChange={(event) => onSelect(event.target.value)}
        >
          {scenarios.map((scenario) => (
            <option key={scenario.id} value={scenario.id}>
              {scenario.name}
            </option>
          ))}
        </select>
      </label>

      <div className="mt-5 overflow-hidden rounded-[24px] border border-white/10 bg-[linear-gradient(145deg,rgba(11,18,34,0.95),rgba(8,13,24,0.86))]">
        <div className="border-b border-white/10 px-5 py-4">
          <div className="flex items-center gap-3">
            <div className="rounded-2xl border border-white/10 bg-white/5 p-3 text-cyan-200">
              <PersonaIcon className="h-5 w-5" />
            </div>
            <div>
              <p className="text-lg font-semibold text-slate-50">
                {selectedScenario.name}
              </p>
              <p className="text-sm text-slate-400">
                {selectedScenario.tagline}
              </p>
            </div>
          </div>
          <p className="mt-4 text-sm leading-6 text-slate-300">
            {selectedScenario.description}
          </p>
        </div>

        <dl className="grid gap-4 px-5 py-4 sm:grid-cols-3">
          <div className="rounded-2xl border border-white/8 bg-white/5 p-4">
            <dt className="flex items-center gap-2 text-xs uppercase tracking-[0.22em] text-slate-400">
              <Clock3 className="h-4 w-4" />
              Runtime
            </dt>
            <dd className="mt-2 text-base font-medium text-slate-50">
              {selectedScenario.durationLabel}
            </dd>
          </div>
          <div className="rounded-2xl border border-white/8 bg-white/5 p-4">
            <dt className="text-xs uppercase tracking-[0.22em] text-slate-400">
              Volume
            </dt>
            <dd className="mt-2 text-base font-medium text-slate-50">
              {selectedScenario.transactionVolumeLabel}
            </dd>
          </div>
          <div className="rounded-2xl border border-white/8 bg-white/5 p-4">
            <dt className="text-xs uppercase tracking-[0.22em] text-slate-400">
              Attack Rounds
            </dt>
            <dd className="mt-2 text-base font-medium text-slate-50">
              {selectedScenario.totalRounds}
            </dd>
          </div>
        </dl>

        <div className="border-t border-white/10 px-5 py-4">
          <p className="text-xs uppercase tracking-[0.22em] text-slate-400">
            Threat focus
          </p>
          <p className="mt-2 text-sm leading-6 text-slate-300">
            {selectedScenario.threatFocus}
          </p>
        </div>
      </div>
    </section>
  );
}
