"""
Observability: contextvars for tracing, structlog setup, and per-operation
timing. Anything in the app that touches logging or tracing goes through here.
"""

from __future__ import annotations

from .context import (
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
from .logger import get_logger
from .tracing import Span, TraceSummary, Tracer
 
__all__ = [
    # logger
    "get_logger",
    # context — setters
    "set_correlation_id",
    "reset_correlation_id",
    "set_job_id",
    "clear_job_id",
    "set_pipeline",
    "set_stage",
    "set_task",
    "set_document_id",
    "clear_document_id",
    "set_collection",
    # context — getters
    "get_correlation_id",
    "get_job_id",
    "get_pipeline",
    "get_stage",
    "get_task",
    "get_document_id",
    "get_collection",
    "snapshot",
    # tracing
    "Tracer",
    "Span",
    "TraceSummary",
]