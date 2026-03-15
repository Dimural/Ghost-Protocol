"use client";

import type { CriminalPersona } from "@/lib/scenarios";

export type MatchViewMode = "owner" | "shared";
export type TrackedDefenderMode = "police_ai" | "webhook";

export type TrackedMatchRecord = {
  matchId: string;
  shareUrl: string | null;
  scenarioId: string | null;
  scenarioName: string;
  criminalPersona: CriminalPersona | null;
  totalRounds: number | null;
  defenderMode: TrackedDefenderMode | null;
  webhookUrl: string;
  status: string;
  currentRound: number;
  launchedAt: string;
  updatedAt: string;
  endedAt: string | null;
  expiresAt: string | null;
};

export type TrackMatchLaunchInput = {
  matchId: string;
  shareUrl: string | null;
  scenarioId: string;
  scenarioName: string;
  criminalPersona: CriminalPersona;
  totalRounds: number;
  defenderMode: TrackedDefenderMode;
  webhookUrl?: string;
  status: string;
  currentRound?: number;
  expiresAt?: string | null;
};

export type MatchCatalogSnapshot = {
  matchId: string;
  shareUrl?: string | null;
  scenarioId?: string | null;
  scenarioName?: string | null;
  criminalPersona?: CriminalPersona | null;
  totalRounds?: number | null;
  defenderMode?: TrackedDefenderMode | null;
  status?: string | null;
  currentRound?: number | null;
  updatedAt?: string | null;
  endedAt?: string | null;
  expiresAt?: string | null;
};

const OWNED_MATCHES_STORAGE_KEY = "ghost_protocol_owned_matches";
const MATCH_CATALOG_STORAGE_KEY = "ghost_protocol_match_catalog";

function readOwnedMatchIds(): string[] {
  if (typeof window === "undefined") {
    return [];
  }

  const rawValue = window.localStorage.getItem(OWNED_MATCHES_STORAGE_KEY);
  if (!rawValue) {
    return [];
  }

  try {
    const parsed = JSON.parse(rawValue);
    if (!Array.isArray(parsed)) {
      return [];
    }

    return parsed.filter((value): value is string => typeof value === "string");
  } catch {
    return [];
  }
}

function writeOwnedMatchIds(matchIds: string[]): void {
  if (typeof window === "undefined") {
    return;
  }

  window.localStorage.setItem(
    OWNED_MATCHES_STORAGE_KEY,
    JSON.stringify(matchIds),
  );
}

function isTrackedMatchRecord(value: unknown): value is TrackedMatchRecord {
  if (!value || typeof value !== "object") {
    return false;
  }

  return "matchId" in value && typeof value.matchId === "string";
}

function readTrackedMatchCatalog(): TrackedMatchRecord[] {
  if (typeof window === "undefined") {
    return [];
  }

  const rawValue = window.localStorage.getItem(MATCH_CATALOG_STORAGE_KEY);
  if (!rawValue) {
    return [];
  }

  try {
    const parsed = JSON.parse(rawValue);
    if (!Array.isArray(parsed)) {
      return [];
    }

    return parsed.filter(isTrackedMatchRecord);
  } catch {
    return [];
  }
}

function writeTrackedMatchCatalog(records: TrackedMatchRecord[]): void {
  if (typeof window === "undefined") {
    return;
  }

  window.localStorage.setItem(
    MATCH_CATALOG_STORAGE_KEY,
    JSON.stringify(records),
  );
}

function buildTrackedMatchStub(matchId: string): TrackedMatchRecord {
  return {
    matchId,
    shareUrl: null,
    scenarioId: null,
    scenarioName: "Tracked Match",
    criminalPersona: null,
    totalRounds: null,
    defenderMode: null,
    webhookUrl: "",
    status: "unknown",
    currentRound: 0,
    launchedAt: "",
    updatedAt: "",
    endedAt: null,
    expiresAt: null,
  };
}

function sortTrackedMatches(records: TrackedMatchRecord[]): TrackedMatchRecord[] {
  return [...records].sort((left, right) => {
    const leftTime = Date.parse(left.updatedAt || left.launchedAt || "");
    const rightTime = Date.parse(right.updatedAt || right.launchedAt || "");
    const safeLeftTime = Number.isNaN(leftTime) ? 0 : leftTime;
    const safeRightTime = Number.isNaN(rightTime) ? 0 : rightTime;
    return safeRightTime - safeLeftTime;
  });
}

export function rememberOwnedMatch(matchId: string): void {
  const nextIds = Array.from(new Set([...readOwnedMatchIds(), matchId]));
  writeOwnedMatchIds(nextIds);
}

export function isOwnedMatch(matchId: string): boolean {
  return readOwnedMatchIds().includes(matchId);
}

export function getMatchViewMode(matchId: string): MatchViewMode {
  return isOwnedMatch(matchId) ? "owner" : "shared";
}

export function trackMatchLaunch(input: TrackMatchLaunchInput): TrackedMatchRecord {
  const timestamp = new Date().toISOString();
  const nextRecord: TrackedMatchRecord = {
    matchId: input.matchId,
    shareUrl: input.shareUrl,
    scenarioId: input.scenarioId,
    scenarioName: input.scenarioName,
    criminalPersona: input.criminalPersona,
    totalRounds: input.totalRounds,
    defenderMode: input.defenderMode,
    webhookUrl: input.webhookUrl?.trim() ?? "",
    status: input.status,
    currentRound: input.currentRound ?? 0,
    launchedAt: timestamp,
    updatedAt: timestamp,
    endedAt: null,
    expiresAt: input.expiresAt ?? null,
  };

  upsertTrackedMatch(nextRecord);
  rememberOwnedMatch(input.matchId);
  return nextRecord;
}

export function upsertTrackedMatch(
  record: TrackedMatchRecord | MatchCatalogSnapshot,
): TrackedMatchRecord {
  const existingCatalog = readTrackedMatchCatalog();
  const existingRecord =
    existingCatalog.find((entry) => entry.matchId === record.matchId) ??
    buildTrackedMatchStub(record.matchId);
  const nextRecord: TrackedMatchRecord = {
    ...existingRecord,
    shareUrl:
      "shareUrl" in record && record.shareUrl !== undefined
        ? record.shareUrl
        : existingRecord.shareUrl,
    scenarioId:
      "scenarioId" in record && record.scenarioId !== undefined
        ? record.scenarioId
        : existingRecord.scenarioId,
    scenarioName:
      "scenarioName" in record &&
      typeof record.scenarioName === "string" &&
      record.scenarioName.length > 0
        ? record.scenarioName
        : existingRecord.scenarioName,
    criminalPersona:
      "criminalPersona" in record && record.criminalPersona !== undefined
        ? record.criminalPersona
        : existingRecord.criminalPersona,
    totalRounds:
      "totalRounds" in record && record.totalRounds !== undefined
        ? record.totalRounds
        : existingRecord.totalRounds,
    defenderMode:
      "defenderMode" in record && record.defenderMode !== undefined
        ? record.defenderMode
        : existingRecord.defenderMode,
    webhookUrl:
      "webhookUrl" in record && typeof record.webhookUrl === "string"
        ? record.webhookUrl.trim()
        : existingRecord.webhookUrl,
    status:
      "status" in record &&
      typeof record.status === "string" &&
      record.status.length > 0
        ? record.status
        : existingRecord.status,
    currentRound:
      "currentRound" in record && typeof record.currentRound === "number"
        ? record.currentRound
        : existingRecord.currentRound,
    launchedAt: existingRecord.launchedAt || new Date().toISOString(),
    updatedAt:
      "updatedAt" in record &&
      typeof record.updatedAt === "string" &&
      record.updatedAt.length > 0
        ? record.updatedAt
        : new Date().toISOString(),
    endedAt:
      "endedAt" in record && record.endedAt !== undefined
        ? record.endedAt
        : existingRecord.endedAt,
    expiresAt:
      "expiresAt" in record && record.expiresAt !== undefined
        ? record.expiresAt
        : existingRecord.expiresAt,
  };

  const dedupedCatalog = existingCatalog.filter(
    (entry) => entry.matchId !== nextRecord.matchId,
  );
  writeTrackedMatchCatalog(sortTrackedMatches([...dedupedCatalog, nextRecord]));
  return nextRecord;
}

export function listTrackedMatches(): TrackedMatchRecord[] {
  const catalogById = new Map(
    readTrackedMatchCatalog().map((record) => [record.matchId, record]),
  );

  for (const matchId of readOwnedMatchIds()) {
    if (!catalogById.has(matchId)) {
      catalogById.set(matchId, buildTrackedMatchStub(matchId));
    }
  }

  return sortTrackedMatches(Array.from(catalogById.values()));
}

export function getTrackedMatch(matchId: string): TrackedMatchRecord | null {
  return listTrackedMatches().find((record) => record.matchId === matchId) ?? null;
}

export function buildCloneSetupUrl(matchId: string): string {
  const params = new URLSearchParams({ clone: matchId });
  return `/?${params.toString()}`;
}

export function isCloneReady(record: TrackedMatchRecord): boolean {
  if (!record.scenarioId || !record.defenderMode) {
    return false;
  }

  if (record.defenderMode === "police_ai") {
    return true;
  }

  return record.webhookUrl.trim().length > 0;
}

export function isExpiredMatchTimestamp(expiresAt: string | null): boolean {
  if (!expiresAt) {
    return false;
  }

  const expiryTime = Date.parse(expiresAt);
  if (Number.isNaN(expiryTime)) {
    return false;
  }

  return expiryTime <= Date.now();
}

export function isTrackedMatchArchived(record: {
  expiresAt: string | null;
}): boolean {
  return isExpiredMatchTimestamp(record.expiresAt);
}

export function resolveAbsoluteShareUrl(shareUrl: string): string {
  if (typeof window === "undefined") {
    return shareUrl;
  }

  try {
    return new URL(shareUrl, window.location.origin).toString();
  } catch {
    return shareUrl;
  }
}

export async function copyTextToClipboard(value: string): Promise<boolean> {
  if (typeof navigator === "undefined" || !navigator.clipboard) {
    return false;
  }

  try {
    await navigator.clipboard.writeText(value);
    return true;
  } catch {
    return false;
  }
}
