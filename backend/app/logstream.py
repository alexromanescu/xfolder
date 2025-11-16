from __future__ import annotations

import asyncio
import logging
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Deque, List, Set, Tuple

from .models import LogEntry


Subscriber = Tuple[asyncio.Queue[LogEntry], asyncio.AbstractEventLoop]


class LogStreamHandler(logging.Handler):
    """In-memory buffer + async fan-out for streaming server logs."""

    def __init__(self, capacity: int = 400) -> None:
        super().__init__()
        self.capacity = capacity
        self._buffer: Deque[LogEntry] = deque(maxlen=capacity)
        self._subscribers: Set[Subscriber] = set()
        self._lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:  # type: ignore[override]
        entry = LogEntry(
            timestamp=datetime.fromtimestamp(record.created, tz=timezone.utc),
            level=record.levelname.lower(),
            level_no=int(record.levelno),
            message=record.getMessage(),
            logger=record.name,
        )
        with self._lock:
            self._buffer.append(entry)
            subscribers = list(self._subscribers)
        for queue, loop in subscribers:
            loop.call_soon_threadsafe(queue.put_nowait, entry)

    def subscribe(self) -> Subscriber:
        queue: asyncio.Queue[LogEntry] = asyncio.Queue()
        loop = asyncio.get_running_loop()
        with self._lock:
            self._subscribers.add((queue, loop))
        return queue, loop

    def unsubscribe(self, subscriber: Subscriber) -> None:
        with self._lock:
            self._subscribers.discard(subscriber)

    def history(self, min_level: int) -> List[LogEntry]:
        with self._lock:
            return [entry for entry in list(self._buffer) if entry.level_no >= min_level]

    def clear(self) -> None:
        with self._lock:
            self._buffer.clear()
            self._subscribers.clear()
