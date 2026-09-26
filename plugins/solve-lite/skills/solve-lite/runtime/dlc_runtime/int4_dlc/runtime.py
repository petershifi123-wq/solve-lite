"""Lazy, one-at-a-time, idle-unloading manager for the INT4 specialist DLCs.

Contract (VV INT4 DLC task):

* default: nothing is downloaded and nothing is loaded -- importing this module
  touches no model file and imports no ML framework;
* at most ONE dlc unit is resident at any time (a unit == one ``dlc_id``; the
  financial route co-loads its two checkpoints, so both live in one unit);
* switching unit or idling really releases the weights (refs dropped, gc run,
  proof recorded: weakrefs dead + live int4 modules == 0 + RSS delta).

The kernel talks to :meth:`DLCManager.load_for_path` through the same
``(tokenizer, model, device)`` contract as the frozen ``load_classifier``.
"""

from __future__ import annotations

import gc
import json
import os
import threading
import time
import weakref
from pathlib import Path
from typing import Any, Callable

from . import meter
from .format import DESCRIPTOR_FILE, STATUS_LOADED, STATUS_UNLOADED, STATUS_UNLOADED_IDLE

DEFAULT_IDLE_SECONDS = 120.0


class DLCBusy(RuntimeError):
    """Raised when a second DLC load is attempted while a forward is in flight."""
WATCHDOG_TICK_SECONDS = 0.25


def default_state_dir(asset_root: Path | None) -> Path:
    override = os.environ.get("SOLVE_LITE_INT4_STATE_DIR")
    if override:
        return Path(override)
    if asset_root is not None:
        return Path(asset_root).resolve().parent / ".int4-dlc-state"
    return Path(__file__).resolve().parent / "addon"


class _Instance:
    __slots__ = ("model_dir", "dlc_id", "tokenizer", "model", "stats", "config", "loaded_at")

    def __init__(self, model_dir: Path, dlc_id: str, tokenizer: Any, model: Any, stats: dict, config: dict):
        self.model_dir = model_dir
        self.dlc_id = dlc_id
        self.tokenizer = tokenizer
        self.model = model
        self.stats = stats
        self.config = config
        self.loaded_at = time.time()


def make_tracked_model(inner: Any, on_enter: Callable[[], None], on_exit: Callable[[], None]):
    """nn.Module proxy that reports in-flight forwards to the manager."""
    import torch
    import torch.nn as nn

    class _Tracked(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.inner = inner

        def forward(self, *args: Any, **kwargs: Any) -> Any:  # noqa: D102
            on_enter()
            try:
                return self.inner(*args, **kwargs)
            finally:
                on_exit()

        def to(self, *args: Any, **kwargs: Any):  # noqa: D102 - int4 weights are cpu-only
            target = args[0] if args else kwargs.get("device")
            if target is not None and str(target) not in ("cpu", "device(type='cpu')"):
                raise RuntimeError(f"INT4_DLC_CPU_ONLY: refusing to move int4 model to {target}")
            return self

        def __getattr__(self, item: str) -> Any:
            try:
                return super().__getattr__(item)
            except AttributeError:
                inner_obj = self.__dict__.get("_modules", {}).get("inner")
                if inner_obj is None:
                    raise
                return getattr(inner_obj, item)

    del torch
    return _Tracked().eval()


class DLCManager:
    """Owns the single resident INT4 unit."""

    def __init__(
        self,
        *,
        asset_root: Path | str | None = None,
        idle_seconds: float = DEFAULT_IDLE_SECONDS,
        fallback: Callable[[Path], tuple[Any, Any, Any]] | None = None,
        state_dir: Path | str | None = None,
    ) -> None:
        self.asset_root = Path(asset_root).resolve() if asset_root is not None else None
        self.idle_seconds = float(idle_seconds)
        self.fallback = fallback
        self.state_dir = Path(state_dir) if state_dir is not None else default_state_dir(self.asset_root)
        self.events: list[dict] = []
        self.swap_events: list[dict] = []
        self._instances: dict[str, _Instance] = {}
        self._current_dlc: str | None = None
        self._in_flight = 0
        self._last_activity = time.monotonic()
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._watchdog: threading.Thread | None = None
        self.counters = {
            "loads": 0,
            "unloads": 0,
            "idle_unloads": 0,
            "swaps": 0,
            "forwards": 0,
            "fallbacks": 0,
            "busy_rejections": 0,
            "cp_descriptor_misses": 0,
        }

    # ---------------------------------------------------------------- helpers
    def _log(self, event: str, **fields: Any) -> dict:
        row = {"ts": round(time.time(), 6), "event": event, "rss_bytes": meter.rss_bytes(), **fields}
        self.events.append(row)
        try:
            self.state_dir.mkdir(parents=True, exist_ok=True)
            with (self.state_dir / "dlc-events.jsonl").open("a", encoding="utf-8") as sink:
                sink.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
        except OSError:
            pass
        return row

    def _touch(self) -> None:
        self._last_activity = time.monotonic()

    def _enter(self) -> None:
        with self._lock:
            self._in_flight += 1
            self.counters["forwards"] += 1
            self._touch()

    def _exit(self) -> None:
        with self._lock:
            self._in_flight = max(0, self._in_flight - 1)
            self._touch()

    # ------------------------------------------------------------------- load
    def load_for_path(self, path: Path | str):
        model_dir = Path(path)
        descriptor_path = model_dir / DESCRIPTOR_FILE
        if not descriptor_path.is_file():
            if self.fallback is None:
                raise RuntimeError(f"NOT_AN_INT4_DLC: {model_dir}")
            self.counters["fallbacks"] += 1
            return self.fallback(model_dir)

        with self._lock:
            key = str(model_dir)
            instance = self._instances.get(key)
            if instance is not None:
                self._touch()
                return instance.tokenizer, instance.model, _cpu_device()

            config = json.loads(descriptor_path.read_text(encoding="utf-8"))
            dlc_id = config["dlc_id"]
            if self._current_dlc is not None and self._current_dlc != dlc_id:
                # ONE DLC AT A TIME: a swap would free the resident unit, so it is
                # refused while any forward is still in flight on that unit.
                if self._in_flight > 0:
                    self.counters["busy_rejections"] += 1
                    rejection = {
                        "event": "DLC_LOAD_REJECTED_BUSY",
                        "requested_dlc_id": dlc_id,
                        "resident_dlc_id": self._current_dlc,
                        "in_flight_forwards": self._in_flight,
                        "ts": round(time.time(), 6),
                    }
                    self.events.append(rejection)
                    self._log("DLC_LOAD_REJECTED_BUSY", **{k: v for k, v in rejection.items() if k != "event"})
                    raise DLCBusy(
                        "DLC_BUSY_IN_FLIGHT: refusing to swap "
                        f"{self._current_dlc} -> {dlc_id} while {self._in_flight} "
                        "forward(s) are in flight (one DLC at a time)"
                    )
                proof = self.unload_current(f"unit_switch_to:{dlc_id}")
                self.counters["swaps"] += 1
                self.swap_events.append(
                    {"from": proof.get("dlc_ids"), "to": dlc_id, "ts": proof.get("ts"), "proof": proof}
                )
            self._current_dlc = dlc_id
            instance = self._materialize(model_dir, config)
            self._instances[key] = instance
            self._ensure_watchdog()
            self._touch()
            return instance.tokenizer, instance.model, _cpu_device()

    def _materialize(self, model_dir: Path, config: dict) -> _Instance:
        from .loader import load_int4_model

        rss_before = meter.rss_bytes()
        from .torch_bootstrap import warm_torch

        warm_torch()
        from transformers import AutoTokenizer

        tokenizer = AutoTokenizer.from_pretrained(str(model_dir), local_files_only=True)
        model, stats = load_int4_model(model_dir)
        tracked = make_tracked_model(model, self._enter, self._exit)
        instance = _Instance(model_dir, config["dlc_id"], tokenizer, tracked, stats, config)
        rss_after = meter.rss_bytes()
        self.counters["loads"] += 1
        self._log(
            STATUS_LOADED,
            dlc_id=config["dlc_id"],
            family=config.get("family"),
            model_dir=str(model_dir),
            resident_weight_bytes=stats["resident_weight_bytes"],
            quantized_modules=stats["quantized_modules"],
            kept_tensors=stats["kept_tensors"],
            rss_before=rss_before,
            rss_after=rss_after,
            rss_delta=rss_after - rss_before,
            in_flight=self._in_flight,
        )
        return instance

    # ----------------------------------------------------------------- unload
    def unload_current(self, reason: str = "explicit") -> dict:
        with self._lock:
            if not self._instances:
                return {"unloaded": False, "reason": reason, "dlc_ids": []}
            from .modules import live_int4_stats

            rss_before = meter.rss_bytes()
            live_before = live_int4_stats()
            refs = {key: weakref.ref(inst.model) for key, inst in self._instances.items()}
            dlc_ids = sorted({inst.dlc_id for inst in self._instances.values()})
            families = sorted({inst.config.get("family") or "" for inst in self._instances.values()})
            self._instances.clear()
            self._current_dlc = None
            gc.collect()
            rss_after = meter.rss_bytes()
            live_after = live_int4_stats()
            alive = sorted(key for key, ref in refs.items() if ref() is not None)
            event = STATUS_UNLOADED_IDLE if reason.startswith("idle_timeout") else STATUS_UNLOADED
            proof = {
                "unloaded": True,
                "reason": reason,
                "dlc_ids": dlc_ids,
                "families": families,
                "rss_before": rss_before,
                "rss_after": rss_after,
                "rss_delta": rss_after - rss_before,
                "live_int4_modules_before": live_before["modules"],
                "live_int4_modules_after": live_after["modules"],
                "live_int4_bytes_before": live_before["packed_bytes"],
                "live_int4_bytes_after": live_after["packed_bytes"],
                "model_objects_collected": not alive,
                "lingering_models": alive,
                "ts": round(time.time(), 6),
            }
            self.counters["unloads"] += 1
            if reason.startswith("idle_timeout"):
                self.counters["idle_unloads"] += 1
            self._log(event, **proof)
            return proof

    # --------------------------------------------------------------- watchdog
    def _ensure_watchdog(self) -> None:
        if self._watchdog is not None or self.idle_seconds <= 0:
            return
        thread = threading.Thread(target=self._watchdog_loop, name="int4-dlc-idle", daemon=True)
        thread.start()
        self._watchdog = thread

    def _watchdog_loop(self) -> None:
        while not self._stop.is_set():
            time.sleep(WATCHDOG_TICK_SECONDS)
            with self._lock:
                if not self._instances or self._in_flight:
                    continue
                if time.monotonic() - self._last_activity >= self.idle_seconds:
                    self.unload_current(f"idle_timeout_{self.idle_seconds:g}s")

    def stop(self) -> None:
        self._stop.set()
        self.unload_current("manager_stop")

    # ----------------------------------------------------------------- status
    def loaded_dlc_ids(self) -> list[str]:
        return sorted({inst.dlc_id for inst in self._instances.values()})

    def status(self) -> dict:
        from .modules import live_int4_stats

        live = live_int4_stats()
        return {
            "current_dlc_id": self._current_dlc,
            "loaded_dlc_ids": self.loaded_dlc_ids(),
            "resident_models": len(self._instances),
            "idle_seconds": self.idle_seconds,
            "seconds_since_activity": round(time.monotonic() - self._last_activity, 3),
            "in_flight_forwards": self._in_flight,
            "live_int4_modules": live["modules"],
            "live_int4_bytes": live.get("packed_bytes"),
            "rss_bytes": meter.rss_bytes(),
            "counters": dict(self.counters),
            "events": len(self.events),
            "state_dir": str(self.state_dir),
        }


def _cpu_device():
    import torch

    return torch.device("cpu")
