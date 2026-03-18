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
    <section className="app-panel p-6">
      <div className="mb-5 flex items-start justify-between gap-4">
        <div>
          <p className="text-xs uppercase tracking-[0.28em] text-slate-500">
            Scenario Selection
          </p>
          <h2 className="mt-2 text-2xl font-semibold text-slate-50">
            Choose the heist profile
          </h2>
        </div>
        <div className="landing-pill landing-pill-accent rounded-full p-3">
          <Radar className="h-5 w-5" />
        </div>
      </div>

      <label className="block">
        <span className="mb-2 block text-sm font-medium text-slate-200">
          Scenario
        </span>
        <select
          className="app-input text-base"
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

      <div className="app-subpanel mt-5 overflow-hidden">
        <div className="border-b border-white/10 px-5 py-5">
          <div className="flex items-center gap-3">
            <div className="app-subpanel-strong rounded-2xl p-3 text-slate-200">
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

          <div className="mt-5 flex flex-wrap gap-2">
            <div className="landing-pill landing-pill-accent">
              Live persona
            </div>
            <div className="landing-pill">
              {selectedScenario.criminalPersona}
            </div>
            <div className="landing-pill">
              {selectedScenario.transactionVolumeLabel}
            </div>
          </div>
        </div>

        <dl className="grid gap-4 px-5 py-4 sm:grid-cols-3">
          <div className="landing-metric-card">
            <dt className="flex items-center gap-2 text-xs uppercase tracking-[0.22em] text-slate-400">
              <Clock3 className="h-4 w-4" />
              Runtime
            </dt>
            <dd className="mt-2 text-base font-medium text-slate-50">
              {selectedScenario.durationLabel}
            </dd>
          </div>
          <div className="landing-metric-card">
            <dt className="text-xs uppercase tracking-[0.22em] text-slate-400">
              Volume
            </dt>
            <dd className="mt-2 text-base font-medium text-slate-50">
              {selectedScenario.transactionVolumeLabel}
            </dd>
          </div>
          <div className="landing-metric-card">
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
