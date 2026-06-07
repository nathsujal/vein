from __future__ import annotations


class ConfigError(Exception):
    """Raised for any config load/parse/validation problem."""


class ConfigSchemaMismatch(ConfigError):
    """Raised when config_version is not supported by this build."""