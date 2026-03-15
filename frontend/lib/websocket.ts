import { getMatchWebSocketUrl } from "@/lib/config";

export type SocketConnectionState = "connecting" | "live" | "offline";

export type OutcomeLabel =
  | "true_positive"
  | "false_positive"
  | "false_negative"
  | "true_negative";

export type MatchScorePayload = {
  true_positives: number;
  false_positives: number;
  false_negatives: number;
  true_negatives: number;
  false_negative_amount_total: number;
  false_positive_amount_total: number;
  precision?: number;
  recall?: number;
  f1_score?: number;
  money_lost?: number;
  money_blocked_legitimately?: number;
};

export type TransactionPayload = {
  id: string;
  timestamp: string;
  user_id: string;
  amount: number;
  currency: string;
  merchant: string;
  category: string;
  location_city: string;
  location_country: string;
  transaction_type: string;
  is_fraud: boolean;
  fraud_type?: string | null;
  notes?: string | null;
};

export type DefenderDecisionPayload = {
  transaction_id: string;
  decision: "APPROVE" | "DENY";
  confidence: number;
  reason?: string | null;
};

export type TransactionProcessedMessage = {
  type: "TRANSACTION_PROCESSED";
  transaction: TransactionPayload;
  defender_decision: DefenderDecisionPayload;
  is_correct: boolean;
  outcome: OutcomeLabel;
  score: MatchScorePayload;
};

export type AttackerAdaptingMessage = {
  type: "ATTACKER_ADAPTING";
  title: string;
  round: number;
  total_rounds: number;
  reasoning: string;
  banner_message: string;
  created_at: string;
};

export type MatchCompleteMessage = {
  type: "MATCH_COMPLETE";
  final_score: MatchScorePayload;
  report_id?: string | null;
};

export type MatchSocketMessage =
  | TransactionProcessedMessage
  | AttackerAdaptingMessage
  | MatchCompleteMessage;

type TransactionProcessedListener = (payload: TransactionProcessedMessage) => void;
type AttackerAdaptingListener = (payload: AttackerAdaptingMessage) => void;
type MatchCompleteListener = (payload: MatchCompleteMessage) => void;
type SocketEventListener = (event: Event) => void;
type SocketCloseListener = (event: CloseEvent) => void;

export class MatchWebSocket {
  private socket: WebSocket | null = null;

  private reconnectTimer: number | null = null;

  private reconnectAttempts = 0;

  private matchId: string | null = null;

  private shouldReconnect = false;

  private transactionProcessedListeners =
    new Set<TransactionProcessedListener>();

  private attackerAdaptingListeners = new Set<AttackerAdaptingListener>();

  private matchCompleteListeners = new Set<MatchCompleteListener>();

  private openListeners = new Set<SocketEventListener>();

  private errorListeners = new Set<SocketEventListener>();

  private closeListeners = new Set<SocketCloseListener>();

  connect(matchId: string): void {
    if (typeof window === "undefined") {
      throw new Error("MatchWebSocket can only connect in the browser.");
    }

    this.disconnect();
    this.matchId = matchId;
    this.shouldReconnect = true;
    this.reconnectAttempts = 0;
    this.openSocket();
  }

  disconnect(): void {
    this.shouldReconnect = false;
    this.matchId = null;
    this.clearReconnectTimer();

    if (!this.socket) {
      return;
    }

    const socket = this.socket;
    this.socket = null;
    socket.close();
  }

  onTransactionProcessed(cb: TransactionProcessedListener): () => void {
    this.transactionProcessedListeners.add(cb);
    return () => this.transactionProcessedListeners.delete(cb);
  }

  onAttackerAdapting(cb: AttackerAdaptingListener): () => void {
    this.attackerAdaptingListeners.add(cb);
    return () => this.attackerAdaptingListeners.delete(cb);
  }

  onMatchComplete(cb: MatchCompleteListener): () => void {
    this.matchCompleteListeners.add(cb);
    return () => this.matchCompleteListeners.delete(cb);
  }

  onOpen(cb: SocketEventListener): () => void {
    this.openListeners.add(cb);
    return () => this.openListeners.delete(cb);
  }

  onError(cb: SocketEventListener): () => void {
    this.errorListeners.add(cb);
    return () => this.errorListeners.delete(cb);
  }

  onClose(cb: SocketCloseListener): () => void {
    this.closeListeners.add(cb);
    return () => this.closeListeners.delete(cb);
  }

  private openSocket(): void {
    if (!this.matchId) {
      return;
    }

    this.clearReconnectTimer();

    const socket = new WebSocket(getMatchWebSocketUrl(this.matchId));
    socket.addEventListener("open", (event) => {
      if (this.socket !== socket) {
        return;
      }

      this.reconnectAttempts = 0;
      this.emitSocketEvent(this.openListeners, event);
    });
    socket.addEventListener("error", (event) => {
      if (this.socket !== socket) {
        return;
      }

      this.emitSocketEvent(this.errorListeners, event);
    });
    socket.addEventListener("close", (event) => {
      if (this.socket !== socket) {
        return;
      }

      this.socket = null;
      this.emitSocketClose(event);

      if (this.shouldReconnect && this.matchId && event.code !== 4404) {
        this.scheduleReconnect();
      }
    });
    socket.addEventListener("message", (event) => {
      if (this.socket !== socket) {
        return;
      }

      this.handleMessage(event.data);
    });

    this.socket = socket;
  }

  private handleMessage(rawPayload: string): void {
    let payload: MatchSocketMessage;
    try {
      payload = JSON.parse(rawPayload) as MatchSocketMessage;
    } catch {
      this.emitSocketEvent(this.errorListeners, new Event("error"));
      return;
    }

    switch (payload.type) {
      case "TRANSACTION_PROCESSED":
        this.transactionProcessedListeners.forEach((listener) =>
          listener(payload),
        );
        return;
      case "ATTACKER_ADAPTING":
        this.attackerAdaptingListeners.forEach((listener) =>
          listener(payload),
        );
        return;
      case "MATCH_COMPLETE":
        this.matchCompleteListeners.forEach((listener) => listener(payload));
        return;
      default:
        return;
    }
  }

  private scheduleReconnect(): void {
    if (typeof window === "undefined" || this.reconnectTimer !== null) {
      return;
    }

    const delayMs = Math.min(4000, 500 * 2 ** this.reconnectAttempts);
    this.reconnectAttempts += 1;
    this.reconnectTimer = window.setTimeout(() => {
      this.reconnectTimer = null;

      if (!this.shouldReconnect || !this.matchId || this.socket) {
        return;
      }

      this.openSocket();
    }, delayMs);
  }

  private clearReconnectTimer(): void {
    if (this.reconnectTimer === null || typeof window === "undefined") {
      return;
    }

    window.clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
  }

  private emitSocketEvent(
    listeners: Set<SocketEventListener>,
    event: Event,
  ): void {
    listeners.forEach((listener) => listener(event));
  }

  private emitSocketClose(event: CloseEvent): void {
    this.closeListeners.forEach((listener) => listener(event));
  }
}
