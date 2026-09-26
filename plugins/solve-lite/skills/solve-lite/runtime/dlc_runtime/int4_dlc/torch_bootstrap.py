"""Import-order guard for the torch + transformers stack on this platform.

Environment quirk (reproduced on macOS 27.0 / arm64 / CPython 3.9.6 with
torch 2.8.0 + transformers 4.51.3):

    transformers/integrations/flex_attention.py executes
        @torch.compiler.disable(recursive=False)
    at import time, which does ``import torch._dynamo`` while
    ``torch._dynamo`` is still initialising (its own module-level
    ``populate_builtin_to_tensor_fn_map()`` calls back into
    ``torch.compiler.disable`` -> ``torch._dynamo.disable``), producing

        AttributeError: partially initialized module 'torch._dynamo' has no
        attribute 'disable' (most likely due to a circular import)

Pre-importing ``torch._dynamo`` (and ``torch.compiler``) BEFORE transformers
makes the later re-entrant import a no-op and removes the failure.
"""

from __future__ import annotations

_warmed = False


def warm_torch() -> None:
    """Import torch and its compiler stack in the safe order (idempotent)."""
    global _warmed
    if _warmed:
        return
    import torch  # noqa: F401

    try:
        import torch._dynamo  # noqa: F401
    except Exception:  # pragma: no cover - non-fatal: older/newer torch layouts
        pass
    try:
        import torch.compiler  # noqa: F401
    except Exception:  # pragma: no cover
        pass
    _warmed = True
