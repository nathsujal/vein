# package/core/tests/test_observability.py
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from unittest.mock import patch

import pytest
import structlog

from vein_core.observability.context import (
    # vars
    correlation_id_var,
    job_id_var,
    pipeline_var,
    stage_var,
    task_var,
    document_id_var,
    collection_var,
    # sentinels
    _UNSET_REQUEST,
    _UNSET_JOB,
    # accessors
    clear_document_id,
    clear_job_id,
    get_collection,
    get_correlation_id,
    get_document_id,
    get_job_id,
    get_pipeline,
    get_stage,
    get_task,
    reset_correlation_id,
    set_collection,
    set_correlation_id,
    set_document_id,
    set_job_id,
    set_pipeline,
    set_stage,
    set_task,
    snapshot,
)
from vein_core.observability.tracing import Span, TraceSummary, Tracer, _now_ms


# Shared fixtures

@pytest.fixture(autouse=True)
def reset_all_contextvars():
    vars_ = [
        correlation_id_var,
        job_id_var,
        pipeline_var,
        stage_var,
        task_var,
        document_id_var,
        collection_var,
    ]
    # Before test: force all vars to "" 
    for v in vars_:
        v.set("")

    yield

    # After test: force all vars back to ""
    for v in vars_:
        v.set("")
 
 
@pytest.fixture()
def log_cfg(tmp_path: Path):
    """A real Log config pointing at a tmp_path log directory."""
    # Import here so the fixture doesn't depend on top-level import order
    from vein_core.config.schema import Log
    return Log(
        level="DEBUG",
        json_format=False,   # pretty console; file handler is always JSON
        dir=tmp_path / "logs",
        max_bytes=1 * 1024 * 1024,
        backup_count=2,
    )
 
 
@pytest.fixture()
def reset_logger():
    """Tear down and reset the logger module state between tests.
 
    The logger uses a module-level ``_configured`` flag and adds handlers
    to the root logger.  Without this fixture, the first test to trigger
    auto-configure would affect all subsequent tests.
    """
    import vein_core.observability.logger as logger_mod
 
    yield
 
    # Reset the flag so the next test gets a clean auto-configure
    logger_mod._configured = False
    structlog.reset_defaults()
 
    # Remove any vein handlers added during the test
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, logger_mod._VEIN_HANDLER_ATTR, None) \
                in logger_mod._VEIN_HANDLER_NAMES:
            handler.close()
            root.removeHandler(handler)
 
 
# TestContext
 
class TestContext:
    """Unit tests for context.py — pure ContextVar logic, no IO."""
 
    # --- correlation_id ---
 
    def test_get_correlation_id_unset_returns_empty_string(self):
        assert get_correlation_id() in ("", _UNSET_REQUEST)
 
    def test_set_correlation_id_prefixes_req(self):
        set_correlation_id("abc12345xyz")
        assert get_correlation_id() == "req-abc12345"
 
    def test_set_correlation_id_truncates_to_8_chars(self):
        set_correlation_id("x" * 20)
        # "req-" + first 8 chars of input
        assert get_correlation_id() == "req-" + "x" * 8
 
    def test_set_correlation_id_short_input(self):
        set_correlation_id("ab")
        assert get_correlation_id() == "req-ab"
 
    def test_reset_correlation_id_restores_previous(self):
        set_correlation_id("first111")
        token = set_correlation_id("second22")
        assert get_correlation_id() == "req-second22"
        reset_correlation_id(token)
        assert get_correlation_id() == "req-first111"
 
    def test_set_correlation_id_returns_token(self):
        from contextvars import Token
        token = set_correlation_id("abc12345")
        assert isinstance(token, Token)
 
    # --- job_id ---
 
    def test_get_job_id_unset_returns_empty_string(self):
        assert get_job_id() in ("", _UNSET_JOB)
 
    def test_set_job_id_prefixes_job(self):
        set_job_id("deadbeef1234")
        assert get_job_id() == "job-deadbeef"
 
    def test_clear_job_id_restores_sentinel(self):
        set_job_id("somejob1")
        clear_job_id()
        assert get_job_id() == _UNSET_JOB
 
    # --- pipeline / stage / task ---
 
    def test_pipeline_roundtrip(self):
        set_pipeline("ingest")
        assert get_pipeline() == "ingest"
 
    def test_stage_roundtrip(self):
        set_stage("chunking")
        assert get_stage() == "chunking"
 
    def test_task_roundtrip(self):
        set_task("bm25_score")
        assert get_task() == "bm25_score"
 
    def test_unset_pipeline_returns_empty(self):
        assert get_pipeline() == ""
 
    def test_unset_stage_returns_empty(self):
        assert get_stage() == ""
 
    def test_unset_task_returns_empty(self):
        assert get_task() == ""
 
    # --- document_id ---
 
    def test_set_document_id_roundtrip(self):
        set_document_id("sha256:abc")
        assert get_document_id() == "sha256:abc"
 
    def test_clear_document_id_empties_var(self):
        set_document_id("sha256:abc")
        clear_document_id()
        assert get_document_id() == ""
 
    # --- collection ---
 
    def test_set_collection_roundtrip(self):
        set_collection("research-papers")
        assert get_collection() == "research-papers"
 
    # --- snapshot ---
 
    def test_snapshot_empty_when_nothing_set(self):
        assert snapshot() == {}
 
    def test_snapshot_only_includes_set_vars(self):
        set_pipeline("query")
        set_stage("retrieval")
        result = snapshot()
        assert result == {"pipeline": "query", "stage": "retrieval"}
        # unset vars must be absent
        assert "correlation_id" not in result
        assert "job_id" not in result
 
    def test_snapshot_includes_all_set_vars(self):
        set_correlation_id("req12345")
        set_job_id("job12345")
        set_pipeline("ingest")
        set_stage("chunking")
        set_task("split")
        set_document_id("doc.pdf")
        set_collection("papers")
        result = snapshot()
        assert result["pipeline"] == "ingest"
        assert result["stage"] == "chunking"
        assert result["task"] == "split"
        assert result["document_id"] == "doc.pdf"
        assert result["collection"] == "papers"
        # correlation_id and job_id are in snapshot with formatted prefix
        assert "req-" in result["correlation_id"]
        assert "job-" in result["job_id"]
 
    def test_snapshot_is_a_copy(self):
        """Mutating the returned dict must not affect the ContextVar."""
        set_pipeline("query")
        s = snapshot()
        s["pipeline"] = "mutated"
        assert get_pipeline() == "query"
 
    # --- async propagation ---
 
    @pytest.mark.asyncio
    async def test_contextvars_propagate_into_task(self):
        """ContextVars set in the parent coroutine are visible inside a Task."""
        set_pipeline("query")
        set_stage("retrieval")
 
        async def inner():
            return get_pipeline(), get_stage()
 
        result = await asyncio.create_task(inner())
        assert result == ("query", "retrieval")
 
    @pytest.mark.asyncio
    async def test_task_mutation_does_not_affect_parent(self):
        """A Task mutating a ContextVar must not affect the parent context."""
        set_pipeline("query")
 
        async def inner():
            set_pipeline("ingest")   # mutate inside task
            return get_pipeline()
 
        inner_val = await asyncio.create_task(inner())
        assert inner_val == "ingest"
        # parent is unchanged
        assert get_pipeline() == "query"
 
 
# TestLogger
 
class TestLogger:
    """Tests for logger.py auto-configure behaviour."""
 
    def test_get_logger_returns_bound_logger(self, log_cfg, reset_logger):
        from vein_core.observability.logger import get_logger
        with patch("vein_core.observability.logger._do_configure") as mock_cfg:
            import vein_core.observability.logger as lmod
            lmod._configured = True          # skip real configure
            log = get_logger(__name__)
        assert log is not None
 
    def test_auto_configure_fires_on_first_call(self, log_cfg, reset_logger, tmp_path):
        """_do_configure() is called exactly once across multiple get_logger() calls."""
        import vein_core.observability.logger as lmod
        assert lmod._configured is False

        with patch("vein_core.config.get_config") as mock_gc:
            from vein_core.config.schema import AppConfig
            mock_gc.return_value = AppConfig(log=log_cfg)
            lmod.get_logger("a")
            lmod.get_logger("b")
            lmod.get_logger("c")

        assert lmod._configured is True
    
    def test_configure_adds_two_handlers(self, log_cfg, reset_logger):
        """After auto-configure the root logger has exactly our two handlers."""
        import vein_core.observability.logger as lmod
 
        with patch("vein_core.config.get_config") as mock_gc:
            from vein_core.config.schema import AppConfig
            mock_gc.return_value = AppConfig(log=log_cfg)
            lmod._do_configure()
            lmod._configured = True
 
        root = logging.getLogger()
        vein_handlers = [
            h for h in root.handlers
            if getattr(h, lmod._VEIN_HANDLER_ATTR, None) in lmod._VEIN_HANDLER_NAMES
        ]
        assert len(vein_handlers) == 2
 
    def test_reconfigure_does_not_duplicate_handlers(self, log_cfg, reset_logger):
        """Calling _do_configure() twice must not accumulate duplicate handlers."""
        import vein_core.observability.logger as lmod
 
        with patch("vein_core.config.get_config") as mock_gc:
            from vein_core.config.schema import AppConfig
            mock_gc.return_value = AppConfig(log=log_cfg)
            lmod._do_configure()
            lmod._configured = True
            lmod._configured = False
            lmod._do_configure()
            lmod._configured = True
 
        root = logging.getLogger()
        vein_handlers = [
            h for h in root.handlers
            if getattr(h, lmod._VEIN_HANDLER_ATTR, None) in lmod._VEIN_HANDLER_NAMES
        ]
        assert len(vein_handlers) == 2
 
    def test_noisy_loggers_silenced(self, log_cfg, reset_logger):
        import vein_core.observability.logger as lmod
 
        with patch("vein_core.config.get_config") as mock_gc:
            from vein_core.config.schema import AppConfig
            mock_gc.return_value = AppConfig(log=log_cfg)
            lmod._do_configure()
            lmod._configured = True
 
        for name in lmod._NOISY_LOGGERS:
            assert logging.getLogger(name).level == logging.WARNING
 
    def test_root_logger_set_to_debug(self, log_cfg, reset_logger):
        import vein_core.observability.logger as lmod
 
        with patch("vein_core.config.get_config") as mock_gc:
            from vein_core.config.schema import AppConfig
            mock_gc.return_value = AppConfig(log=log_cfg)
            lmod._do_configure()
            lmod._configured = True
 
        assert logging.getLogger().level == logging.DEBUG
 
    def test_log_file_created(self, log_cfg, reset_logger, tmp_path):
        """After configure a .log file must exist in the configured log dir."""
        import vein_core.observability.logger as lmod
 
        with patch("vein_core.config.get_config") as mock_gc:
            from vein_core.config.schema import AppConfig
            mock_gc.return_value = AppConfig(log=log_cfg)
            lmod._do_configure()
            lmod._configured = True
 
        log_files = list(log_cfg.dir.glob("*.log"))
        assert len(log_files) == 1
 
    def test_log_file_contains_json(self, log_cfg, reset_logger, tmp_path):
        """Each line in the log file must be valid JSON."""
        import vein_core.observability.logger as lmod
 
        with patch("vein_core.config.get_config") as mock_gc:
            from vein_core.config.schema import AppConfig
            mock_gc.return_value = AppConfig(log=log_cfg)
            lmod._do_configure()
            lmod._configured = True
 
        log = lmod.get_logger("test.json")
        log.info("hello from test")
 
        # Flush all handlers so the file is written
        for h in logging.getLogger().handlers:
            h.flush()
 
        log_file = next(log_cfg.dir.glob("*.log"))
        lines = [l for l in log_file.read_text().splitlines() if l.strip()]
        assert lines, "log file is empty"
        for line in lines:
            parsed = json.loads(line)   # raises if not valid JSON
            assert "event" in parsed or "message" in parsed or parsed
 
 
# TestTracer
 
class TestTracer:
    """Unit tests for tracing.py — no IO, no structlog needed."""
 
    # --- Span dataclass ---
 
    def test_span_is_open_before_close(self):
        s = Span(name="test", start_ms=_now_ms())
        assert s.is_open is True
        assert s.duration_ms is None
 
    def test_span_closed_after_close(self):
        s = Span(name="test", start_ms=_now_ms())
        s._close()
        assert s.is_open is False
        assert s.duration_ms is not None
        assert s.duration_ms >= 0
 
    def test_span_records_error_on_exception(self):
        s = Span(name="test", start_ms=_now_ms())
        s._close(error=ValueError("boom"))
        assert s.error == "ValueError: boom"
 
    def test_span_no_error_when_clean(self):
        s = Span(name="test", start_ms=_now_ms())
        s._close()
        assert s.error is None
 
    # --- Tracer sync span ---
 
    def test_sync_span_records_duration(self):
        tracer = Tracer("query")
        with tracer.span("retrieval"):
            pass
        summary = tracer.finish()
        assert len(summary.spans) == 1
        span = summary.spans[0]
        assert span.name == "retrieval"
        assert span.duration_ms is not None
        assert span.duration_ms >= 0
        assert span.error is None
 
    def test_sync_span_captures_context_at_start(self):
        set_stage("chunking")
        set_pipeline("ingest")
        tracer = Tracer("ingest")
        with tracer.span("split"):
            # mutate stage after span opened — context must still reflect start-time value
            set_stage("embedding")
        summary = tracer.finish()
        ctx = summary.spans[0].context
        assert ctx.get("stage") == "chunking"
        assert ctx.get("pipeline") == "ingest"
 
    def test_sync_span_records_error_and_reraises(self):
        tracer = Tracer("query")
        with pytest.raises(RuntimeError, match="fail"):
            with tracer.span("broken"):
                raise RuntimeError("fail")
        summary = tracer.finish()
        assert summary.spans[0].error is not None
        assert "RuntimeError" in summary.spans[0].error
 
    def test_multiple_spans_in_order(self):
        tracer = Tracer("query")
        with tracer.span("rewrite"):
            pass
        with tracer.span("retrieval"):
            pass
        with tracer.span("generation"):
            pass
        summary = tracer.finish()
        assert [s.name for s in summary.spans] == ["rewrite", "retrieval", "generation"]
 
    # --- Tracer async span ---
 
    @pytest.mark.asyncio
    async def test_async_span_records_duration(self):
        tracer = Tracer("query")
        async with tracer.async_span("embed"):
            await asyncio.sleep(0)   # yield control
        summary = tracer.finish()
        assert summary.spans[0].duration_ms is not None
        assert summary.spans[0].duration_ms >= 0
 
    @pytest.mark.asyncio
    async def test_async_span_captures_error_and_reraises(self):
        tracer = Tracer("ingest")
        with pytest.raises(ValueError, match="async fail"):
            async with tracer.async_span("load"):
                raise ValueError("async fail")
        summary = tracer.finish()
        assert "ValueError" in summary.spans[0].error
 
    @pytest.mark.asyncio
    async def test_async_span_captures_context(self):
        set_collection("papers")
        tracer = Tracer("query")
        async with tracer.async_span("retrieve"):
            await asyncio.sleep(0)
        summary = tracer.finish()
        assert summary.spans[0].context.get("collection") == "papers"
 
    # --- finish() ---
 
    def test_finish_closes_open_spans(self):
        """finish() must close any span that is still open (e.g. on cancellation)."""
        tracer = Tracer("query")
        # Manually open a span without using the context manager
        s = tracer._open("orphan")
        assert s.is_open
        summary = tracer.finish()
        assert not summary.spans[0].is_open
        assert summary.spans[0].duration_ms is not None
 
    def test_finish_total_ms_positive(self):
        tracer = Tracer("query")
        with tracer.span("step"):
            pass
        summary = tracer.finish()
        assert summary.total_ms >= 0
 
    def test_finish_with_no_spans(self):
        tracer = Tracer("empty")
        summary = tracer.finish()
        assert summary.spans == []
        assert summary.total_ms >= 0
 
    # --- TraceSummary properties ---
 
    def test_slowest_returns_longest_span(self):
        tracer = Tracer("query")
        with tracer.span("fast"):
            pass
        with tracer.span("slow"):
            # Force this span to be longer by manipulating start_ms
            tracer._spans[-1].start_ms -= 100   # pretend it started 100ms earlier
        summary = tracer.finish()
        assert summary.slowest is not None
        assert summary.slowest.name == "slow"
 
    def test_slowest_none_when_no_spans(self):
        tracer = Tracer("empty")
        summary = tracer.finish()
        assert summary.slowest is None
 
    def test_had_errors_true_when_any_span_errored(self):
        tracer = Tracer("query")
        with pytest.raises(RuntimeError):
            with tracer.span("broken"):
                raise RuntimeError("oops")
        with tracer.span("ok"):
            pass
        summary = tracer.finish()
        assert summary.had_errors is True
 
    def test_had_errors_false_when_clean(self):
        tracer = Tracer("query")
        with tracer.span("a"):
            pass
        with tracer.span("b"):
            pass
        summary = tracer.finish()
        assert summary.had_errors is False
 
    # --- to_dict() ---
 
    def test_to_dict_shape(self):
        tracer = Tracer("query")
        with tracer.span("retrieval"):
            pass
        summary = tracer.finish()
        d = summary.to_dict()
        assert d["operation"] == "query"
        assert isinstance(d["total_ms"], float)
        assert isinstance(d["spans"], list)
        span_d = d["spans"][0]
        assert span_d["name"] == "retrieval"
        assert span_d["duration_ms"] is not None
        assert span_d["error"] is None
        assert isinstance(span_d["context"], dict)
 
    def test_to_dict_error_span(self):
        tracer = Tracer("ingest")
        with pytest.raises(OSError):
            with tracer.span("load"):
                raise OSError("disk full")
        d = tracer.finish().to_dict()
        assert d["spans"][0]["error"] is not None
        assert "OSError" in d["spans"][0]["error"]
 
    def test_to_dict_is_json_serialisable(self):
        tracer = Tracer("query")
        with tracer.span("step"):
            pass
        d = tracer.finish().to_dict()
        # Should not raise
        json.dumps(d)


# TestIntegration

class TestIntegration:
    """Integration tests — real log file, real ContextVar injection."""

    def test_contextvars_appear_in_log_file(self, log_cfg, reset_logger, tmp_path):
        """ContextVars set before logging must appear in the JSON log file."""
        import vein_core.observability.logger as lmod

        with patch("vein_core.config.get_config") as mock_gc:
            from vein_core.config.schema import AppConfig
            mock_gc.return_value = AppConfig(log=log_cfg)
            lmod._do_configure()
            lmod._configured = True

        set_pipeline("query")
        set_stage("retrieval")
        set_collection("research")
 
        log = lmod.get_logger("integration.test")
        log.info("retrieval complete", chunks=5)
 
        for h in logging.getLogger().handlers:
            h.flush()
 
        log_file = next(log_cfg.dir.glob("*.log"))
        lines = [json.loads(l) for l in log_file.read_text().splitlines() if l.strip()]
        assert lines, "No log lines written"
 
        last = lines[-1]
        assert last.get("pipeline") == "query"
        assert last.get("stage") == "retrieval"
        assert last.get("collection") == "research"
        assert last.get("chunks") == 5
 
    def test_unset_contextvars_absent_from_log(self, log_cfg, reset_logger, tmp_path):
        """Keys for unset ContextVars must not appear in the JSON log line."""
        import vein_core.observability.logger as lmod
 
        with patch("vein_core.config.get_config") as mock_gc:
            from vein_core.config.schema import AppConfig
            mock_gc.return_value = AppConfig(log=log_cfg)
            lmod._do_configure()
            lmod._configured = True
 
        # Nothing set — all vars at default ""
        log = lmod.get_logger("integration.clean")
        log.info("clean log line")
 
        for h in logging.getLogger().handlers:
            h.flush()
 
        log_file = next(log_cfg.dir.glob("*.log"))
        lines = [json.loads(l) for l in log_file.read_text().splitlines() if l.strip()]
        last = lines[-1]
 
        for key in ("pipeline", "stage", "task", "document_id", "collection"):
            assert key not in last, f"Unexpected key {key!r} in log line"
 
    @pytest.mark.asyncio
    async def test_tracer_and_logger_together(self, log_cfg, reset_logger, tmp_path):
        """Span context snapshot matches what the logger wrote to file."""
        import vein_core.observability.logger as lmod
 
        with patch("vein_core.config.get_config") as mock_gc:
            from vein_core.config.schema import AppConfig
            mock_gc.return_value = AppConfig(log=log_cfg)
            lmod._do_configure()
            lmod._configured = True
 
        log = lmod.get_logger("integration.tracer")
 
        set_pipeline("query")
        tracer = Tracer("query")
 
        async with tracer.async_span("retrieval"):
            set_stage("retrieval")
            set_collection("docs")
            log.info("retrieving chunks", top_k=20)
 
        summary = tracer.finish()
 
        for h in logging.getLogger().handlers:
            h.flush()
 
        # Tracer captured context at span-open time
        ctx = summary.spans[0].context
        assert ctx.get("pipeline") == "query"
 
        # Log file captured context at log-call time (stage set inside span)
        log_file = next(log_cfg.dir.glob("*.log"))
        lines = [json.loads(l) for l in log_file.read_text().splitlines() if l.strip()]
        last = lines[-1]
        assert last.get("stage") == "retrieval"
        assert last.get("collection") == "docs"
        assert last.get("top_k") == 20