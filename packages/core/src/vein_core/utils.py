from __future__ import annotations

from urllib.parse import urlparse

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


def is_valid_url(
    url: str,
) -> bool:
    result = urlparse(url)

    return (
        result.scheme in {
            "http",
            "https",
        }
        and bool(result.netloc)
    )