"use client";

export type MatchViewMode = "owner" | "shared";

const OWNED_MATCHES_STORAGE_KEY = "ghost_protocol_owned_matches";

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
