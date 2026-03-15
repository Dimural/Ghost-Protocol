const DEFAULT_BACKEND_URL = "http://localhost:8000";

function trimTrailingSlash(value: string): string {
  return value.replace(/\/+$/, "");
}

export function getBackendBaseUrl(): string {
  return trimTrailingSlash(
    process.env.NEXT_PUBLIC_BACKEND_URL || DEFAULT_BACKEND_URL,
  );
}

export function getWebSocketBaseUrl(): string {
  const explicitUrl = process.env.NEXT_PUBLIC_WS_URL;
  if (explicitUrl) {
    return trimTrailingSlash(explicitUrl);
  }

  const backendUrl = new URL(getBackendBaseUrl());
  backendUrl.protocol = backendUrl.protocol === "https:" ? "wss:" : "ws:";
  return trimTrailingSlash(backendUrl.toString());
}

export function getApiUrl(path: string): string {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${getBackendBaseUrl()}${normalizedPath}`;
}

export function getMatchWebSocketUrl(matchId: string): string {
  const encodedMatchId = encodeURIComponent(matchId);
  return `${getWebSocketBaseUrl()}/ws/match/${encodedMatchId}`;
}
