from __future__ import annotations
 
from contextvars import ContextVar, Token
from typing import Any


# Set by CorrelationIDMiddleware at the start of every HTTP request.
correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")
 
# Set by worker_loop() when a job is dequeued; cleared in the finally block
# so jobs don't bleed into each other on the same worker coroutine.
job_id_var: ContextVar[str] = ContextVar("job_id", default="")
 
# Top-level pipeline: "ingest" | "query" | "eval"
pipeline_var: ContextVar[str] = ContextVar("pipeline", default="")
 
# Coarse stage within the pipeline: "loading" | "chunking" | "embedding"
# | "retrieval" | "reranking" | "generation" | "eval"
stage_var: ContextVar[str] = ContextVar("stage", default="")
 
# Fine-grained sub-step within a stage: "bm25_score" | "cross_encoder"
# | "hyde_generate" | "prompt_render" | etc
task_var: ContextVar[str] = ContextVar("task", default="")
 
# SHA-256 content hash or original filename of the document being processed
document_id_var: ContextVar[str] = ContextVar("document_id", default="")
 
# Qdrant collection targeted by the current operation
collection_var: ContextVar[str] = ContextVar("collection", default="")


# 8-char sentinels — short enough to not dominate log columns when nothing
# is set, long enough to be visually distinguishable from a real ID.
_UNSET_REQUEST = "--------"
_UNSET_JOB     = "---------"


# correlation_id
def set_correlation_id(request_id: str) -> Token[str]:
    """
    Stamp a request correlation ID for the current async context.

    Called by CorrelationIDMiddleware — every logger call in the same
    request picks it up automatically via the structlog contextvar injector.
    Truncates to 8 chars; the "req-" prefix is what disambiguates a
    correlation ID from a job ID in shared log output.
    """
    return correlation_id_var.set(f"req-{request_id[:8]}")

def get_correlation_id() -> str:
    """Return the current correlation ID, or the sentinel if unset."""
    return correlation_id_var.get(_UNSET_REQUEST)

def reset_correlation_id(token: Token[str]) -> None:
    """Restore the previous correlation ID value (useful in tests)."""
    correlation_id_var.reset(token)


# job_id
def set_job_id(job_id: str) -> Token[str]:
    """Stamp the active ingest job ID for the current async context.

    Called by ``worker_loop()`` when a job is dequeued.
    """
    return job_id_var.set(f"job-{job_id[:8]}")

def get_job_id() -> str:
    """Return the active job ID, or the sentinel if unset."""
    return job_id_var.get(_UNSET_JOB)

def clear_job_id() -> None:
    """Reset job ID back to the sentinel after a job finishes.

    Called in the ``finally`` of ``worker_loop()`` — without this, the next
    job on the same worker coroutine would briefly inherit the previous
    job's ID during the gap between dequeue and its own set_job_id().
    """
    job_id_var.set(_UNSET_JOB)


# pipeline / stage / task
def set_pipeline(name: str) -> Token[str]:
    """Set the top-level pipeline name: ``"ingest"`` | ``"query"`` | ``"eval"``."""
    return pipeline_var.set(name)

def get_pipeline() -> str:
    return pipeline_var.get("")

def set_stage(name: str) -> Token[str]:
    """Set the coarse stage within the pipeline, e.g. ``"chunking"``."""
    return stage_var.set(name)

def get_stage() -> str:
    return stage_var.get("")

def set_task(name: str) -> Token[str]:
    """Set the fine-grained sub-step, e.g. ``"bm25_score"``."""
    return task_var.set(name)

def get_task() -> str:
    return task_var.get("")


# document_id
def set_document_id(doc_id: str) -> Token[str]:
    """Stamp the document being processed (SHA-256 hash or filename)."""
    return document_id_var.set(doc_id)

def get_document_id() -> str:
    return document_id_var.get("")

def clear_document_id() -> None:
    """Clear document ID between documents in the same ingest job."""
    document_id_var.set("")


# collection
def set_collection(name: str) -> Token[str]:
    """Stamp the target Qdrant collection for the current operation."""
    return collection_var.set(name)

def get_collection() -> str:
    return collection_var.get("")


# Used by Tracer to grab whatever context is set right now without the
# tracing module needing to know which vars exist.
_SENTINELS: frozenset[str] = frozenset({_UNSET_REQUEST, _UNSET_JOB})

def snapshot() -> dict[str, Any]:
    """Return a copy of the currently-set context vars, with unset / sentinel
    values stripped out so the dict only carries real state.

    Mutating the returned dict has no effect on the underlying ContextVars
    (see the test that asserts this).
    """
    raw: dict[str, Any] = {
        "correlation_id": correlation_id_var.get(""),
        "job_id":         job_id_var.get(""),
        "pipeline":       pipeline_var.get(""),
        "stage":          stage_var.get(""),
        "task":           task_var.get(""),
        "document_id":    document_id_var.get(""),
        "collection":     collection_var.get(""),
    }
    return {k: v for k, v in raw.items() if v and v not in _SENTINELS}