"""JSONL recorder for simulation runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .protocol import TRIGGER_EVENT, TRIGGER_PERIODIC, message_kind, message_trigger_type, now_ms


class JsonlRecorder:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path) if path else None
        self._file = None
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._file = self.path.open("a", encoding="utf-8")

    def record(self, event_type: str, payload: dict[str, Any]) -> None:
        if not self._file:
            return
        trigger_type = self._trigger_type(payload)
        event = {
            "timestamp_ms": now_ms(),
            "event_type": event_type,
            "trigger_type": trigger_type,
            "payload": payload,
        }
        if "packet_id" in payload or "control_id" in payload:
            event["message_kind"] = message_kind(payload)
            event["trigger_reason"] = payload.get("trigger_reason", "")
        elif payload.get("transition") or payload.get("alerts"):
            event["trigger_reason"] = payload.get("transition") or "; ".join(payload.get("alerts", []))
        self._file.write(json.dumps(event, ensure_ascii=False) + "\n")
        self._file.flush()

    @staticmethod
    def _trigger_type(payload: dict[str, Any]) -> str:
        if "packet_id" in payload or "control_id" in payload:
            return message_trigger_type(payload)
        if payload.get("trigger_type") == TRIGGER_EVENT:
            return TRIGGER_EVENT
        if payload.get("transition") or payload.get("alerts"):
            return TRIGGER_EVENT
        return TRIGGER_PERIODIC

    def close(self) -> None:
        if self._file:
            self._file.close()
            self._file = None
