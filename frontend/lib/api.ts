import { getApiUrl } from "@/lib/config";
import type { CriminalPersona } from "@/lib/scenarios";
import type {
  AttackerAdaptingMessage,
  DefenderDecisionPayload,
  MatchScorePayload,
  TransactionPayload,
} from "@/lib/websocket";

type RequestOptions = Omit<RequestInit, "body"> & {
  body?: unknown;
};

export class ApiError extends Error {
  status: number;

  detail: unknown;

  constructor(message: string, status: number, detail: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

export type CreateMatchRequest = {
  scenario_name: string;
  criminal_persona: CriminalPersona;
  total_rounds: number;
};

export type CreateMatchResponse = {
  match_id: string;
  status: string;
  share_url: string;
};

export type RegisterDefenderRequest = {
  match_id: string;
  webhook_url?: string;
  use_police_ai: boolean;
};

export type RegisterDefenderResponse = {
  defender_id: string;
  status: "registered";
};

export type TestDefenderRequest = {
  match_id: string;
  webhook_url: string;
};

export type TestDefenderResponse = {
  status: "reachable" | "unreachable";
  raw_response?: Record<string, unknown> | null;
  error?: string | null;
};

export type MatchStateSummary = {
  match_id: string;
  status: string;
  share_url?: string | null;
  current_round?: number;
  total_rounds?: number;
};

export type MatchStateResponse = {
  match_id: string;
  scenario_name: string;
  status: "setup" | "running" | "paused" | "complete";
  current_round: number;
  total_rounds: number;
  transactions: TransactionPayload[];
  defender_decisions: DefenderDecisionPayload[];
  score: MatchScorePayload;
  started_at: string;
  ended_at?: string | null;
  share_url?: string | null;
  expires_at?: string | null;
  criminal_persona?: CriminalPersona | null;
  target_persona_id?: string | null;
  latest_notification?: AttackerAdaptingMessage | null;
  updated_at: string;
};

async function requestJson<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const headers = new Headers(options.headers);
  const hasJsonBody = options.body !== undefined;

  if (hasJsonBody) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(getApiUrl(path), {
    ...options,
    headers,
    cache: "no-store",
    body: hasJsonBody ? JSON.stringify(options.body) : undefined,
  });

  const rawText = await response.text();
  let payload: unknown = null;

  if (rawText) {
    try {
      payload = JSON.parse(rawText);
    } catch {
      payload = rawText;
    }
  }

  if (!response.ok) {
    const message =
      extractDetailMessage(payload) ||
      `Request failed with status ${response.status}.`;
    throw new ApiError(message, response.status, payload);
  }

  return payload as T;
}

function extractDetailMessage(payload: unknown): string | null {
  if (typeof payload === "string" && payload.trim()) {
    return payload.trim();
  }

  if (
    payload &&
    typeof payload === "object" &&
    "detail" in payload &&
    typeof payload.detail === "string"
  ) {
    return payload.detail;
  }

  return null;
}

export function getErrorMessage(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }

  return "Unexpected request failure.";
}

export function createMatch(
  body: CreateMatchRequest,
): Promise<CreateMatchResponse> {
  return requestJson<CreateMatchResponse>("/api/match/create", {
    method: "POST",
    body,
  });
}

export function registerDefender(
  body: RegisterDefenderRequest,
): Promise<RegisterDefenderResponse> {
  return requestJson<RegisterDefenderResponse>("/api/defender/register", {
    method: "POST",
    body,
  });
}

export function testDefenderConnection(
  body: TestDefenderRequest,
): Promise<TestDefenderResponse> {
  return requestJson<TestDefenderResponse>("/api/defender/test", {
    method: "POST",
    body,
  });
}

export function startMatch(matchId: string): Promise<MatchStateSummary> {
  return requestJson<MatchStateSummary>(`/api/match/${matchId}/start`, {
    method: "POST",
  });
}

export function getMatch(matchId: string): Promise<MatchStateResponse> {
  return requestJson<MatchStateResponse>(`/api/match/${matchId}`);
}
