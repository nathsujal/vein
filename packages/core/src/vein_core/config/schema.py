from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from vein_core.errors import ConfigValidationError
from vein_core.utils import raise_if_errors


# Paths
APP_ROOT: Path = (Path.home() / ".vein").resolve()
CONFIG_PATH_DEFAULT: Path = APP_ROOT / "config.toml"

# --- helpers ---

_VALID_LOG_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})


def _default_log_dir() -> Path:
    return APP_ROOT / "logs"


# --- sections ---

@dataclass(slots=True, frozen=True)
class Daemon:
    host: str = "127.0.0.1"
    port: int = 8765

    def __post_init__(self) -> None:
        errors: list[str] = []
        if not isinstance(self.host, str):
            errors.append(
                f"daemon.host must be a string, got {self.host!r} ({type(self.host).__name__})"
            )
        elif not self.host:
            errors.append(f"daemon.host must be non-empty, got {self.host!r}")
        if not isinstance(self.port, int):
            errors.append(
                f"daemon.port must be an int, got {self.port!r} ({type(self.port).__name__})"
            )
        elif not (1 <= self.port <= 65535):
            errors.append(f"daemon.port must be 1..65535, got {self.port!r}")
        raise_if_errors(errors, "Daemon configuration errors", ConfigValidationError)

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"


@dataclass(slots=True, frozen=True)
class Log:
    level: str = "INFO"
    json_format: bool = False
    dir: Path = field(default_factory=_default_log_dir)
    max_bytes: int = 10 * 1024 * 1024
    backup_count: int = 5

    def __post_init__(self) -> None:
        errors: list[str] = []
        if not isinstance(self.level, str):
            errors.append(
                f"log.level must be a string, got {self.level!r} ({type(self.level).__name__})"
            )
        else:
            object.__setattr__(self, "level", self.level.upper())
            if self.level not in _VALID_LOG_LEVELS:
                errors.append(
                    f"log.level must be one of {sorted(_VALID_LOG_LEVELS)}, got {self.level!r}"
                )
        if not isinstance(self.json_format, bool):
            errors.append(
                f"log.json_format must be a bool, got {self.json_format!r}"
            )
        if not isinstance(self.max_bytes, int):
            errors.append(
                f"log.max_bytes must be an int, got {self.max_bytes!r} ({type(self.max_bytes).__name__})"
            )
        elif self.max_bytes <= 0:
            errors.append(f"log.max_bytes must be > 0, got {self.max_bytes!r}")
        if not isinstance(self.backup_count, int):
            errors.append(
                f"log.backup_count must be an int, got {self.backup_count!r} ({type(self.backup_count).__name__})"
            )
        elif self.backup_count < 0:
            errors.append(f"log.backup_count must be >= 0, got {self.backup_count!r}")

        raise_if_errors(errors, "Log configuration errors", ConfigValidationError)


@dataclass(slots=True, frozen=True)
class Ollama:
    provider: str = "ollama"
    base_url: str = "http://localhost:11434"
    timeout_seconds: int = 30
    max_retries: int = 3

    def __post_init__(self) -> None:
        errors: list[str] = []
        if not isinstance(self.provider, str) or not self.provider.strip():
            errors.append("provider must not be empty")
        if not isinstance(self.base_url, str) or not self.base_url:
            errors.append("base_url must not be empty")
        if not isinstance(self.timeout_seconds, int) or self.timeout_seconds <= 0:
            errors.append(f"timeout_seconds must be an int > 0, got {self.timeout_seconds}") 
        if not isinstance(self.max_retries, int) or self.max_retries < 0:
            errors.append(f"max_retries must be an int > 0, got {self.max_retries}")
        raise_if_errors(errors, "LLM configuration errors", ConfigValidationError)


@dataclass(slots=True, frozen=True)
class LLM:
    """LLM-specific settings. Derived from Ollama provider for base_url/retries."""
    provider: Ollama = field(default_factory=Ollama)
    model: str = "gemma4:12b-it-qat"

    num_ctx: int = 32768

    def __post_init__(self) -> None:
        errors: list[str] = []
        if not isinstance(self.model, str) or not self.model.strip():
            errors.append("model must not be empty")
        if not isinstance(self.num_ctx, int) or self.num_ctx < 0:
            errors.append("num_ctx must be a positive int")
        raise_if_errors(errors, "LLM configuration errors", ConfigValidationError)

    @property
    def base_url(self) -> str:
        return self.provider.base_url

    @property
    def timeout_seconds(self) -> int:
        return self.provider.timeout_seconds

    @property
    def max_retries(self) -> int:
        return self.provider.max_retries


@dataclass(slots=True, frozen=True)
class Embedder:
    """Embedding-specific settings. Derived from Ollama provider for base_url/retries."""
    provider: Ollama = field(default_factory=Ollama)
    model: str = "nomic-embed-text:v1.5"
    dimension: int = 768

    def __post_init__(self) -> None:
        errors: list[str] = []
        if not isinstance(self.model, str) or not self.model.strip():
            errors.append("model must not be empty")
        if not isinstance(self.dimension, int) or self.dimension <= 0:
            errors.append(f"dimension must be an int > 0, got {self.dimension}")
        raise_if_errors(errors, "Embedder configuration errors", ConfigValidationError)

    @property
    def base_url(self) -> str:
        return self.provider.base_url

    @property
    def timeout_seconds(self) -> int:
        return self.provider.timeout_seconds

    @property
    def max_retries(self) -> int:
        return self.provider.max_retries


# root
@dataclass(slots=True, frozen=True)
class AppConfig:
    config_version: str = "1"
    daemon: Daemon = field(default_factory=Daemon)
    log: Log = field(default_factory=Log)
    llm: LLM = field(default_factory=LLM)
    embedder: Embedder = field(default_factory=Embedder)


DEFAULT = AppConfig()