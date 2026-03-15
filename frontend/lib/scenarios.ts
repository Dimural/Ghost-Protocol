export type CriminalPersona = "amateur" | "patient" | "botnet";

export type ScenarioDefinition = {
  id: string;
  name: string;
  tagline: string;
  description: string;
  durationLabel: string;
  transactionVolumeLabel: string;
  threatFocus: string;
  criminalPersona: CriminalPersona;
  totalRounds: number;
};

export const SCENARIOS: ScenarioDefinition[] = [
  {
    id: "quick-smash",
    name: "The Quick Smash",
    tagline: "Impulsive theft with loud signals.",
    description:
      "A fast hit from an amateur attacker using large, obvious purchases and abrupt location shifts.",
    durationLabel: "5 minutes",
    transactionVolumeLabel: "100 transactions",
    threatFocus: "Single large purchases, foreign merchants, luxury spend.",
    criminalPersona: "amateur",
    totalRounds: 3,
  },
  {
    id: "long-con",
    name: "The Long Con",
    tagline: "Slow-burn infiltration and patient extraction.",
    description:
      "A disciplined insider warms up the account, blends into normal behavior, then drains value in measured steps.",
    durationLabel: "15 minutes",
    transactionVolumeLabel: "500 transactions",
    threatFocus: "Behavior mimicry, weekend timing, subtle value leakage.",
    criminalPersona: "patient",
    totalRounds: 3,
  },
  {
    id: "ghost-army",
    name: "The Ghost Army",
    tagline: "Distributed swarm across many accounts.",
    description:
      "A botnet floods the system with coordinated micro-transactions designed to slip under threshold-based rules.",
    durationLabel: "10 minutes",
    transactionVolumeLabel: "1,000 transactions",
    threatFocus: "Smurfing, rapid-fire timing, merchant fan-out.",
    criminalPersona: "botnet",
    totalRounds: 3,
  },
];

export const DEFAULT_SCENARIO_ID = SCENARIOS[0].id;

export function getScenarioById(
  scenarioId: string | null | undefined,
): ScenarioDefinition | null {
  if (!scenarioId) {
    return null;
  }

  return SCENARIOS.find((scenario) => scenario.id === scenarioId) ?? null;
}

export function findScenarioByName(
  scenarioName: string | null | undefined,
): ScenarioDefinition | null {
  if (!scenarioName) {
    return null;
  }

  return SCENARIOS.find((scenario) => scenario.name === scenarioName) ?? null;
}

export function inferScenarioFromMatchConfig(input: {
  scenarioName?: string | null;
  criminalPersona?: CriminalPersona | null;
  totalRounds?: number | null;
}): ScenarioDefinition | null {
  const byName = findScenarioByName(input.scenarioName);
  if (byName) {
    return byName;
  }

  const byPersonaAndRounds = SCENARIOS.find(
    (scenario) =>
      scenario.criminalPersona === input.criminalPersona &&
      scenario.totalRounds === input.totalRounds,
  );
  if (byPersonaAndRounds) {
    return byPersonaAndRounds;
  }

  return (
    SCENARIOS.find(
      (scenario) => scenario.criminalPersona === input.criminalPersona,
    ) ?? null
  );
}
