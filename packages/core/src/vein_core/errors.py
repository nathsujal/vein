from __future__ import annotations


# --- Config ---

class ConfigValidationError(Exception):
    """Raised for any config load/parse/validation problem."""


class ConfigSchemaMismatch(ConfigValidationError):
    """Raised when config_version is not supported by this build."""


# --- Model ---

class ModelValidationError(Exception):
    """Raised for any domain model validation probelm."""
