"""
Ghost Protocol — Match WebSocket Route

Streams live match events to connected dashboard clients. The manager keeps
connections match-scoped so upcoming Referee, Criminal, and Report events can
reuse the same broadcast path.
"""
from __future__ import annotations

import asyncio
import copy
import threading
import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from backend.core.match_state import AdaptationNotification, MATCH_STATE_STORE
from backend.core.referee import MatchScore

router = APIRouter(tags=["websocket"])


@dataclass
class MatchSocketConnection:
    websocket: WebSocket
    queue: asyncio.Queue[dict[str, Any]]
    loop: asyncio.AbstractEventLoop


class MatchCompleteMessage(BaseModel):
    type: str = "MATCH_COMPLETE"
    final_score: MatchScore
    report_id: str | None = None


class MatchEventManager:
    def __init__(self) -> None:
        self._connections: dict[str, dict[str, MatchSocketConnection]] = {}
        self._lock = threading.Lock()

    async def connect(self, match_id: str, websocket: WebSocket) -> tuple[str, asyncio.Queue[dict[str, Any]]]:
        await websocket.accept()
        connection_id = uuid.uuid4().hex
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        connection = MatchSocketConnection(
            websocket=websocket,
            queue=queue,
            loop=asyncio.get_running_loop(),
        )
        with self._lock:
            self._connections.setdefault(match_id, {})[connection_id] = connection
        return connection_id, queue

    def disconnect(self, match_id: str, connection_id: str) -> None:
        with self._lock:
            match_connections = self._connections.get(match_id)
            if match_connections is None:
                return

            match_connections.pop(connection_id, None)
            if not match_connections:
                self._connections.pop(match_id, None)

    async def broadcast(self, match_id: str, message: dict[str, Any] | BaseModel) -> int:
        payload = self._normalize_message(message)
        stale_connections: list[str] = []

        with self._lock:
            connections = dict(self._connections.get(match_id, {}))

        for connection_id, connection in connections.items():
            if connection.loop.is_closed():
                stale_connections.append(connection_id)
                continue
            self._enqueue(connection, payload)

        for connection_id in stale_connections:
            self.disconnect(match_id, connection_id)

        return len(connections) - len(stale_connections)

    def connection_count(self, match_id: str) -> int:
        with self._lock:
            return len(self._connections.get(match_id, {}))

    def clear(self) -> None:
        with self._lock:
            self._connections.clear()

    def _enqueue(self, connection: MatchSocketConnection, payload: dict[str, Any]) -> None:
        message = copy.deepcopy(payload)

        def push() -> None:
            connection.queue.put_nowait(message)

        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None

        if current_loop is connection.loop:
            push()
            return

        connection.loop.call_soon_threadsafe(push)

    def _normalize_message(self, message: dict[str, Any] | BaseModel) -> dict[str, Any]:
        if isinstance(message, BaseModel):
            return message.model_dump(mode="json")
        return copy.deepcopy(message)


MATCH_EVENT_MANAGER = MatchEventManager()


@router.websocket("/ws/match/{match_id}")
async def match_event_stream(websocket: WebSocket, match_id: str) -> None:
    if MATCH_STATE_STORE.load(match_id) is None:
        await websocket.close(code=4404)
        return

    connection_id, queue = await MATCH_EVENT_MANAGER.connect(match_id, websocket)

    try:
        while True:
            queue_task = asyncio.create_task(queue.get())
            receive_task = asyncio.create_task(websocket.receive())
            done, pending = await asyncio.wait(
                {queue_task, receive_task},
                return_when=asyncio.FIRST_COMPLETED,
            )

            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)

            if queue_task in done:
                message = queue_task.result()
                await websocket.send_json(message)
                continue

            inbound = receive_task.result()
            if inbound["type"] == "websocket.disconnect":
                break

    except (WebSocketDisconnect, asyncio.CancelledError):
        pass
    finally:
        MATCH_EVENT_MANAGER.disconnect(match_id, connection_id)


def build_match_event_emitter(match_id: str):
    async def emitter(payload: dict[str, Any]) -> None:
        await MATCH_EVENT_MANAGER.broadcast(match_id, payload)

    return emitter


async def emit_match_event(match_id: str, payload: dict[str, Any] | BaseModel) -> int:
    return await MATCH_EVENT_MANAGER.broadcast(match_id, payload)


async def emit_attacker_adapting(match_id: str, notification: AdaptationNotification) -> int:
    return await emit_match_event(match_id, notification)


async def emit_match_complete(
    match_id: str,
    final_score: MatchScore,
    report_id: str | None = None,
) -> int:
    return await emit_match_event(
        match_id,
        MatchCompleteMessage(final_score=final_score, report_id=report_id),
    )
