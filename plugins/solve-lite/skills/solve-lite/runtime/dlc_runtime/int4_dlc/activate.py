"""Wire the INT4 DLC manager into the frozen kernel WITHOUT editing it.

The frozen kernel resolves ``load_classifier`` as a module-level global and calls
it as ``load_classifier(path)`` -> ``(tokenizer, model, device)``
(BUILD/lite_src/_src5_lite.py:130,174,220,257,291).  Rebinding that attribute on
the already-imported module is therefore enough: no .so, no Core file and no
published artifact is touched, and the eight native modules stay byte-identical.

Nothing is imported (no torch, no transformers) until ``activate`` is called, and
``activate`` alone loads nothing: the first model is materialised on the first
kernel call for a DLC path.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

from .runtime import DEFAULT_IDLE_SECONDS, DLCManager


class Activation:
    """Handle returned by :func:`activate`."""

    def __init__(
        self,
        manager: DLCManager,
        *,
        kernel_module: Any | None = None,
        original: Any | None = None,
    ) -> None:
        self.manager = manager
        self.kernel_module = kernel_module
        self.original = original
        self.patched = False

    @property
    def asset_root(self) -> Path | None:
        return self.manager.asset_root

    def deactivate(self) -> bool:
        if self.patched and self.kernel_module is not None and self.original is not None:
            self.kernel_module.load_classifier = self.original
            self.patched = False
        return self.patched


def import_kernel(kernel_native: Path | str):
    """Import the frozen ``_slk5`` module from a ``_kernel_native`` directory."""
    location = str(Path(kernel_native).resolve())
    if location not in sys.path:
        sys.path.insert(0, location)
    return importlib.import_module("_slk5")


def patch_load_classifier(kernel_module: Any, activation: Activation) -> Any:
    """Point ``kernel_module.load_classifier`` at the DLC manager."""
    if activation.original is None:
        activation.original = kernel_module.load_classifier
    kernel_module.load_classifier = activation.manager.load_for_path
    activation.kernel_module = kernel_module
    activation.patched = True
    return activation.original


def activate(
    *,
    asset_root: Path | str | None = None,
    idle_seconds: float = DEFAULT_IDLE_SECONDS,
    kernel_module: Any | None = None,
    kernel_native: Path | str | None = None,
    fallback: Any | None = None,
    state_dir: Path | str | None = None,
    patch: bool = True,
) -> Activation:
    """Create the manager (loading nothing) and optionally patch the kernel."""
    if kernel_module is None and kernel_native is not None and patch:
        kernel_module = import_kernel(kernel_native)
    if fallback is None and kernel_module is not None:
        fallback = getattr(kernel_module, "load_classifier", None)
    manager = DLCManager(
        asset_root=asset_root,
        idle_seconds=idle_seconds,
        fallback=fallback,
        state_dir=state_dir,
    )
    activation = Activation(manager, kernel_module=kernel_module, original=fallback)
    if patch and kernel_module is not None:
        patch_load_classifier(kernel_module, activation)
    return activation


def auto_activate_from_env(
    kernel_module: Any, env_var: str = "SOLVE_LITE_INT4_DLC"
) -> "Activation | None":
    """Explicit opt-in activation hook for a launcher.

    Returns None unless ``env_var`` is truthy -- nothing in this addon activates
    itself, downloads anything, or edits the frozen Core.  A launcher that ships
    a DLC sets ``SOLVE_LITE_INT4_DLC=1`` (optionally
    ``SOLVE_LITE_INT4_DLC_ROOT`` / ``SOLVE_LITE_INT4_DLC_IDLE_SECONDS``).
    """
    import os

    if str(os.environ.get(env_var, "")).strip().lower() not in {"1", "true", "yes", "on"}:
        return None
    root = os.environ.get("SOLVE_LITE_INT4_DLC_ROOT") or None
    idle = float(os.environ.get("SOLVE_LITE_INT4_DLC_IDLE_SECONDS") or DEFAULT_IDLE_SECONDS)
    return activate(asset_root=root, idle_seconds=idle, kernel_module=kernel_module, patch=True)
