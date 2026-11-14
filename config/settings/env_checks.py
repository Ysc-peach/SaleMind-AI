"""Environment checks shared by the settings modules."""

import os

from django.core.exceptions import ImproperlyConfigured


def require_proxy_hops(name: str = "DRF_NUM_PROXIES") -> int:
    """Return the trusted proxy hop count, or fail closed.

    The value must equal the number of reverse proxies between the client and
    this process. Too small merges every client behind the nearest proxy into a
    single rate-limit bucket; too large reads the client-supplied segment of
    ``X-Forwarded-For`` and reopens the spoofing hole.
    """

    raw = os.environ.get(name, "").strip()
    if not raw.isdigit() or int(raw) < 1:
        raise ImproperlyConfigured(
            f"{name} must be a positive integer equal to the number of trusted "
            "reverse proxies. Too small merges every client into one bucket; too "
            "large reads the client-supplied X-Forwarded-For segment."
        )
    return int(raw)


def require_independent_verifier(
    *,
    verifier_provider: str,
    verifier_model: str,
    verifier_base_url: str,
    llm_provider: str,
    llm_model: str,
) -> None:
    """Fail closed when production would silently reuse the generation model.

    ``VERIFIER_API_KEY`` is deliberately not checked here: a fresh deployment
    must be able to start with an empty credential set while an operator loads
    the knowledge base. Generation still fails closed at the provider boundary
    until the key is supplied.
    """

    configured = (
        ("VERIFIER_PROVIDER", verifier_provider),
        ("VERIFIER_MODEL", verifier_model),
        ("VERIFIER_BASE_URL", verifier_base_url),
    )
    missing = [
        name for name, value in configured
        if not str(value or "").strip()
    ]
    if missing:
        raise ImproperlyConfigured(
            "Production requires an explicitly configured independent verifier: "
            + ", ".join(missing)
        )
    if (
        str(verifier_provider).strip() == str(llm_provider).strip()
        and str(verifier_model).strip() == str(llm_model).strip()
    ):
        raise ImproperlyConfigured(
            "The verifier must not reuse the generation provider and model."
        )
