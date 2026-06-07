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
                f"daemon.host must be a string, got {type(self.host).__name__}"
            )
        elif not self.host:
            errors.append(f"daemon.host must be non-empty, got {self.host!r}")
        if not isinstance(self.port, int):
            errors.append(
                f"daemon.port must be an int, got {type(self.port).__name__}"
            )
        elif not (1 <= self.port <= 65535):
            errors.append(f"daemon.port must be 1..65535, got {self.port}")
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
                f"log.level must be a string, got {type(self.level).__name__}"
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
                f"log.max_bytes must be an int, got {type(self.max_bytes).__name__}"
            )
        elif self.max_bytes <= 0:
            errors.append(f"log.max_bytes must be > 0, got {self.max_bytes}")
        if not isinstance(self.backup_count, int):
            errors.append(
                f"log.backup_count must be an int, got {type(self.backup_count).__name__}"
            )
        elif self.backup_count < 0:
            errors.append(f"log.backup_count must be >= 0, got {self.backup_count}")

        raise_if_errors(errors, "Log configuration errors", ConfigValidationError)


# root
@dataclass(slots=True, frozen=True)
class AppConfig:
    config_version: str = "1"
    daemon: Daemon = field(default_factory=Daemon)
    log: Log = field(default_factory=Log)

DEFAULT = AppConfig()