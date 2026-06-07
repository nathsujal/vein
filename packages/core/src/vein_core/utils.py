from __future__ import annotations

from .errors import ConfigValidationError


def raise_if_errors(
    errors: list[str],
    context: str,
    exc_type: type[Exception] = ValueError
) -> None:
    if not errors:
        return
        
    bullet_list = "\n".join(
        f"  • {e}"
        for e in errors
    )

    raise exc_type(
        f"{context}:\n{bullet_list}"
    )