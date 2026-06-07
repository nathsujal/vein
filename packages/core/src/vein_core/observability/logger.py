from __future__ import annotations
 
import os
import sys
from datetime import datetime
from typing import TYPE_CHECKING, Any, TextIO
import logging
from logging.handlers import RotatingFileHandler
import warnings
import threading
 
import structlog

from .context import (
    collection_var,
    correlation_id_var,
    document_id_var,
    job_id_var,
    pipeline_var,
    stage_var,
    task_var,
    _SENTINELS,
)
 
if TYPE_CHECKING:
    from collections.abc import MutableMapping
    from structlog.types import Processor
    from vein_core.config import Log

# We tag every handler we add with a private attribute so that on
# re-configure we can find and remove *only* ours — never touch handlers
# other libraries attached to the root logger.
_VEIN_HANDLER_ATTR  = "_vein_handler"
_VEIN_HANDLER_NAMES = {"vein_file", "vein_stdout"}


_configured: bool = False
# Guards _do_configure so a swarm of concurrent first-call get_logger()'s
# only runs the (kinda expensive) setup once.
_configure_lock   = threading.Lock()

# These spam at INFO/DEBUG — silenced to WARNING so they don't drown out
# our own logs. Add more here when you find a new offender.
_NOISY_LOGGERS = (
    "httpx",
    "httpcore",
    "urllib3",
    "asyncio",
    "multipart",
    "qdrant_client",
    "sentence_transformers",
)


def _inject_contextvar(
    _logger: object,
    _method: str,
    event_dict: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    """structlog processor — stamps any set ContextVars onto the log record.

    Callers never pass correlation_id / job_id etc. explicitly; they just
    show up. Sentinels and empty strings are skipped so log lines don't
    carry `job_id: "---------"` noise.
    """
    pairs = [
        ("correlation_id", correlation_id_var),
        ("job_id",         job_id_var),
        ("pipeline",       pipeline_var),
        ("stage",          stage_var),
        ("task",           task_var),
        ("document_id",    document_id_var),
        ("collection",     collection_var),
    ]
    for key, var in pairs:
        value = var.get("")
        if value and value not in _SENTINELS:
            event_dict[key] = value

    return event_dict


# --- Public API --- 
def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """
    Return a structlog logger, auto-configuring logging on first call.

    Pass ``__name__`` so the logger name appears in every log line::

        log = get_logger(__name__)

    Thread-safe — concurrent first callers serialize on a lock and only
    one actually runs the setup.
    """
    _ensure_configured()
    return structlog.get_logger(name or __name__)


def _ensure_configured() -> None:
    """Configure logging if not already done.  Called by get_logger()."""
    global _configured

    if _configured:        # fast path — no lock needed after first call
        return

    with _configure_lock:
        if _configured:    # another thread beat us here
            return
        _do_configure()
        _configured = True

def _do_configure() -> None:
    """Build and attach all handlers.  Called exactly once."""
    from vein_core.config import get_config  # type: ignore[import]
    cfg = get_config().log

    structlog.reset_defaults()

    root = logging.getLogger()
    _remove_vein_handlers(root)
    # Root stays at DEBUG — the *handlers* are the level filter, so the file
    # handler can capture DEBUG even when stdout is gated to INFO.
    root.setLevel(logging.DEBUG)

    pre_chain = _build_pre_chain()

    # stdout — pretty console at cfg.level (default INFO)
    stdout_level = getattr(logging, cfg.level.upper(), logging.INFO)
    stdout_handler = _SmartStreamHandler(sys.stdout)
    stdout_handler.setLevel(stdout_level)
    stdout_handler.setFormatter(_make_formatter(pre_chain, json=False))
    setattr(stdout_handler, _VEIN_HANDLER_ATTR, "vein_stdout")
    root.addHandler(stdout_handler)

    # rotating file — always JSON, always DEBUG
    log_dir = cfg.dir.expanduser().resolve()
    log_dir.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(
        filename=log_dir / _log_filename(),
        maxBytes=cfg.max_bytes,
        backupCount=cfg.backup_count,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(_make_formatter(pre_chain, json=True))
    setattr(file_handler, _VEIN_HANDLER_ATTR, "vein_file")
    root.addHandler(file_handler)

    structlog.configure(
        processors=[
            *pre_chain,
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        # False so tests can re-configure and have get_logger(name) actually
        # rebuild against the new config instead of returning a cached one.
        cache_logger_on_first_use=False,
    )

    for noisy in _NOISY_LOGGERS:
        logging.getLogger(noisy).setLevel(logging.WARNING)


def _build_pre_chain() -> list[Processor]:
    return [
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        _inject_contextvar,
        structlog.stdlib.PositionalArgumentsFormatter(),
    ]

def _make_formatter(pre_chain: list[Processor], *, json: bool) -> structlog.stdlib.ProcessorFormatter:
    if json:
        tail: list[Processor] = [
            structlog.processors.format_exc_info,
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ]
    else:
        tail = [
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.dev.ConsoleRenderer(colors=True),
            # ConsoleRenderer handles exceptions itself — adding format_exc_info
            # here would cause structlog to "format exception twice" warnings.
        ]
    return structlog.stdlib.ProcessorFormatter(
        processors=tail,
        foreign_pre_chain=pre_chain,
    )

def _remove_vein_handlers(root: logging.Logger) -> None:
    # Filter to only our tagged handlers — never touch anything another
    # library has attached to the root logger.
    for handler in list(root.handlers):
        if getattr(handler, _VEIN_HANDLER_ATTR, None) in _VEIN_HANDLER_NAMES:
            handler.close()
            root.removeHandler(handler)

def _log_filename() -> str:
    # Timestamp + pid: two restarts in the same second on the same host
    # would still produce different filenames because the pid differs.
    now = datetime.now()
    return (
        f"{now.year:04d}-{now.month:02d}-{now.day:02d}"
        f".{now.hour:02d}{now.minute:02d}{now.second:02d}"
        f".{os.getpid()}.log"
    )


class _SmartStreamHandler(logging.StreamHandler):
    """Flush only on WARNING+ — avoids per-record flush overhead at DEBUG/INFO.

    Python's stdout is line-buffered when attached to a TTY but block-buffered
    when piped (e.g. captured by `docker logs` / a file redirect). Flushing
    every line on the piped path tanks throughput; gating the flush by
    severity gets us near-line-buffered behaviour where it matters and
    cheap batched flushes everywhere else.
    """
 
    def __init__(self, stream: TextIO | None = None) -> None:
        super().__init__(stream)
        self._suppress_flush = False
 
    def emit(self, record: logging.LogRecord) -> None:
        self._suppress_flush = record.levelno < logging.WARNING
        try:
            super().emit(record)
        finally:
            self._suppress_flush = False
 
    def flush(self) -> None:
        if not self._suppress_flush:
            super().flush()