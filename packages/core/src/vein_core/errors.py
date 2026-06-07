from __future__ import annotations


class ConfigValidationError(Exception):
    """Raised for any config load/parse/validation problem."""


class ConfigSchemaMismatch(ConfigValidationError):
    """Raised when config_version is not supported by this build."""
