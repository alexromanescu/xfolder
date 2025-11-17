from __future__ import annotations

import asyncio
import json
import threading
import time
from datetime import datetime, timezone
from typing import Optional, Set, Tuple

from .store import ScanManager

Subscriber = Tuple[asyncio.Queue[str], asyncio.AbstractEventLoop]


class ProgressBroadcaster:
    def __init__(self, manager: ScanManager, interval_seconds: float = 1.0) -> None:
        self.manager = manager
        self.interval = interval_seconds
        self._subscribers: Set[Subscriber] = set()
        self._lock = threading.Lock()
        self._latest_payload: Optional[str] = None
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        if not self._thread.is_alive():
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=1)

    def subscribe(self) -> Subscriber:
        queue: asyncio.Queue[str] = asyncio.Queue()
        loop = asyncio.get_running_loop()
        subscriber: Subscriber = (queue, loop)
        with self._lock:
            self._subscribers.add(subscriber)
        if self._latest_payload:
            loop.call_soon_threadsafe(queue.put_nowait, self._latest_payload)
        return subscriber

    def unsubscribe(self, subscriber: Subscriber) -> None:
        with self._lock:
            self._subscribers.discard(subscriber)

    def history(self) -> list[str]:
        if not self._latest_payload:
            return []
        return [self._latest_payload]

    def _broadcast(self, payload: str) -> None:
        with self._lock:
            subscribers = list(self._subscribers)
        for queue, loop in subscribers:
            loop.call_soon_threadsafe(queue.put_nowait, payload)

    def _run(self) -> None:
        while not self._stop.is_set():
            payload = self._build_payload()
            if payload:
                self._latest_payload = payload
                self._broadcast(payload)
            time.sleep(self.interval)

    def _build_payload(self) -> Optional[str]:
        jobs = self.manager.list_jobs()
        if not jobs:
            return None
        scans = []
        for job in jobs:
            progress = self.manager.get_progress(job.scan_id)
            scans.append(json.loads(progress.json()))
        if not scans:
            return None
        event = {
            "type": "scan_progress",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "scans": scans,
        }
        return json.dumps(event)
