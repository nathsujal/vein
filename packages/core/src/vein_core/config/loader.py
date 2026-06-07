from __future__ import annotations

import os
import tomllib
from dataclasses import asdict
from pathlib import Path
from typing import Any

import tomli_w

from vein_core.errors import ConfigValidationError, ConfigSchemaMismatch
from .schema import AppConfig, DEFAULT, CONFIG_PATH_DEFAULT, Daemon, Log


SUPPORTED_CONFIG_VERSIONS: frozenset[str] = frozenset({"1"})


# --- read ---

def _coerce_daemon(raw: dict[str, Any]) -> Daemon:
    try:
        return Daemon(**raw)
    except (TypeError, ConfigValidationError) as exc:
        raise ConfigValidationError(f"Invalid daemon configuration: {exc}") from exc

def _coerce_log(raw: dict[str, Any]) -> Log:
    data = dict(raw)
    try:
        if "dir" in data and not isinstance(data["dir"], Path):
            data["dir"] = Path(data["dir"]).expanduser()
        return Log(**data)
    except (TypeError, ConfigValidationError) as exc:
        raise ConfigValidationError(f"Invalid log configuration: {exc}") from exc

def _coerce(raw: dict[str, Any]) -> AppConfig:
    return AppConfig(
        config_version=str(raw.get("config_version", DEFAULT.config_version)),
        daemon=_coerce_daemon(raw.get("daemon") or {}),
        log=_coerce_log(raw.get("log") or {}),
    )


def load_config(path: Path) -> AppConfig:
    if not path.exists():
        return DEFAULT
    try:
        raw = tomllib.loads(path.read_text("utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigValidationError(f"Invalid TOML in {path}: {exc}") from exc
    except OSError as exc:
        raise ConfigValidationError(f"Failed to read {path}: {exc}") from exc

    raw_version = str(raw.get("config_version", DEFAULT.config_version))
    if raw_version not in SUPPORTED_CONFIG_VERSIONS:
        raise ConfigSchemaMismatch(
            f"config_version {raw_version!r} is not supported. "
            f"Supported: {sorted(SUPPORTED_CONFIG_VERSIONS)}"
        )

    return _coerce(raw)


def load_or_create(path: Path = CONFIG_PATH_DEFAULT) -> AppConfig:
    ensure_config(path)
    return load_config(path)


# --- write ---

def _to_toml_dict(cfg: AppConfig) -> dict[str, Any]:
    d = asdict(cfg)
    d["log"]["dir"] = str(cfg.log.dir)
    return d


def _make_default_toml() -> str:
    return tomli_w.dumps(_to_toml_dict(DEFAULT))


_DEFAULT_TOML: str = _make_default_toml()


def write_config(cfg: AppConfig, path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ConfigValidationError(f"Failed to create {path.parent}: {exc}") from exc

    payload = tomli_w.dumps(_to_toml_dict(cfg))

    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(payload, encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise ConfigValidationError(f"Failed to write {path}: {exc}") from exc


def ensure_config(path: Path) -> bool:
    if path.exists():
        return False

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ConfigValidationError(f"Failed to create {path.parent}: {exc}") from exc

    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY

    try:
        fd = os.open(path, flags, 0o644)
    except FileExistsError:
        return False
    except OSError as exc:
        raise ConfigValidationError(f"Failed to create {path}: {exc}") from exc

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(_DEFAULT_TOML)
    except Exception:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(path)
        except OSError:
            pass
        raise

    return True