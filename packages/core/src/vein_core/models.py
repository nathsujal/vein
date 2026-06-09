from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from vein_core.utils import raise_if_errors, is_valid_url
from vein_core.errors import ModelValidationError

class MimeType(StrEnum):
    PDF         = "application/pdf"
    MARKDOWN    = "text/markdown"
    HTML        = "text/html"
    PLAIN_TEXT  = "text/plain"


@dataclass(slots=True)
class Document:
    doc_id: str
    title: str
    mime_type: MimeType
    uri: Path | str
    parsed_path: Path | None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        errors: list[str] = []
        if not self.doc_id.strip():
            errors.append(f"doc_id must not be empty")
        if not self.title.strip():
            errors.append(f"title must not be empty")
        if not isinstance(self.mime_type, MimeType):
            errors.append(
                f"mime_type must be one of "
                f"{", ".join(m.value for m in MimeType)}, got {self.mime_type}"
            )
        if isinstance(self.uri, Path):
            pass
        elif isinstance(self.uri, str):
            if not is_valid_url(self.uri):
                errors.append(f"invalid url: {self.uri}")
        else:
            errors.append(
                f"uri must be Path or URL string"
            )
        raise_if_errors(errors, "Document validation failed", ModelValidationError)


@dataclass(slots=True)
class Chunk:
    chunk_id: str
    doc_id: str
    text: str
    token_count: int
    embedding_model: str | None
    metadata: dict[str, Any]

    def __post_init__(self) -> None:
        errors: list[str] = []
        if not self.chunk_id.strip():
            errors.append("chunk_id must not be empty")
        if not self.doc_id.strip():
            errors.append("doc_id must not be empty")
        if not self.text.strip():
            errors.append("text must not be empty")
        if not isinstance(self.token_count, int) or self.token_count < 0:
            errors.append(f"token_count must not be a non-negative integer, got {self.token_count}")
        if not isinstance(self.metadata, dict):
            errors.append(f"metadata must be a dict, got {type(self.metadata).__name__}")
        raise_if_errors(errors, "Chunk validation failed", ModelValidationError)