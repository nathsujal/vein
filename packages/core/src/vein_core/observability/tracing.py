from __future__ import annotations
 
import time
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Iterator
 
from .context import snapshot


@dataclass(slots=True)
class Span:
    """A single timed unit of work inside a pipeline operation."""
    name: str
    start_ms: float
    end_ms: float | None = None
    context: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


    @property
    def duration_ms(self) -> float | None:
        if self.end_ms is None:
            return None
        return self.end_ms - self.start_ms

    @property
    def is_open(self) -> bool:
        return self.end_ms is None

    def _close(self, error: BaseException | None = None) -> None:
        """Stamp the end time and (optionally) the error string. Not
        usually called directly — the context managers do this."""
        self.end_ms = _now_ms()
        if error is not None:
            self.error = f"{type(error).__name__}: {error}"


@dataclass(slots=True)
class TraceSummary:
    """Finished trace for one pipeline operation.

    Produced by ``Tracer.finish()`` — attached to ``QueryResult`` for queries
    and logged directly for ingest jobs.
    """
    operation: str
    spans: list[Span]
    total_ms: float

    @property
    def slowest(self) -> Span | None:
        finished = [s for s in self.spans if s.duration_ms is not None]
        return max(finished, key=lambda s: s.duration_ms, default=None)

    @property
    def had_errors(self) -> bool:
        return any(s.error for s in self.spans)

    def to_dict(self) -> dict[str, Any]:
        """Serialise for JSON. Used both in API responses and in log lines,
        so keep the shape stable — anything in here is part of the public
        contract."""
        return {
            "operation": self.operation,
            "total_ms": round(self.total_ms, 3),
            "spans": [
                {
                    "name": s.name,
                    "duration_ms": round(s.duration_ms, 3) if s.duration_ms is not None else None,
                    "error": s.error,
                    "context": s.context,
                }
                for s in self.spans
            ],
        }


class Tracer:
    """Collects spans for a single pipeline operation.

    Not thread-safe by design — each asyncio Task (query/ingest job) creates
    its own ``Tracer`` and discards it when done. Don't share across tasks.
    """
    def __init__(self, operation: str) -> None:
        self.operation = operation
        self._start_ms = _now_ms()
        self._spans: list[Span] = []

    @contextmanager
    def span(self, name: str) -> Iterator[Span]:
        """Sync context manager that times the enclosed block.

        Example::
            with tracer.span("chunking") as s:
                chunks = chunker.run(doc)
            # s.duration_ms is now set
        """
        s = self._open(name)
        try:
            yield s
        except Exception as exc:
            s._close(error=exc)
            raise
        else:
            s._close()

    @asynccontextmanager
    async def async_span(self, name: str) -> AsyncIterator[Span]:
        """Async context manager that times the enclosed ``await`` block.

        Example::
            async with tracer.async_span("retrieval") as s:
                chunks = await retriever.run(query)
        """
        s = self._open(name)
        try:
            yield s
        except Exception as exc:
            s._close(error=exc)
            raise
        else:
            s._close()

    def finish(self) -> TraceSummary:
        """Close the tracer and return a ``TraceSummary``.

        Any spans still open at this point are closed with no error — this
        handles the case where a coroutine was cancelled mid-flight and
        never ran its normal exit path.
        """
        for s in self._spans:
            if s.is_open:
                s._close()

        total_ms = _now_ms() - self._start_ms
        return TraceSummary(
            operation=self.operation,
            spans=list(self._spans),
            total_ms=round(total_ms, 3),
        )

    def _open(self, name: str) -> Span:
        """Create and start a span. Captures the context *now* (at open time),
        not at close time — so the recorded context reflects what was
        happening when the work *started*, even if the caller mutates
        ContextVars mid-span. There's a test for this behaviour."""
        s = Span(
            name=name,
            start_ms=_now_ms(),
            context=snapshot(),
        )
        self._spans.append(s)
        return s


def _now_ms() -> float:
    """Monotonic wall clock in milliseconds."""
    return time.perf_counter() * 1000