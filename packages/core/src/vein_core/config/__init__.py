from __future__ import annotations

from functools import lru_cache

from .loader import (
    ensure_config,
    load_config,
    load_or_create,
    write_config,
)
from .schema import APP_ROOT, CONFIG_PATH_DEFAULT, DEFAULT, AppConfig, Daemon, Log

__all__ = [
    "AppConfig",
    "Daemon",
    "Log",
    "APP_ROOT",
    "CONFIG_PATH_DEFAULT",
    "DEFAULT",
    "load_config",
    "load_or_create",
    "write_config",
    "ensure_config",
    "get_config",
    "reload_config",
]


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    return load_config(CONFIG_PATH_DEFAULT)


def reload_config() -> AppConfig:
    get_config.cache_clear()
    return get_config()