"""Audit-hook evidence: what a run really opened, imported and connected to.

Nothing here is inferred -- every counter comes from an audit event raised by the
interpreter itself (sys.addaudithook), so the numbers can be re-derived by any
reviewer running the same script.
"""
from __future__ import annotations

import sys
from typing import Any

FP32_WEIGHT_SUFFIXES = (".bin", ".safetensors", ".pth", ".pt", ".gguf", ".onnx")
SLINT4_MARKER = "slint4"


class AuditRecorder:
    """Counts file opens, module imports and network/subprocess attempts."""

    def __init__(self) -> None:
        self.events = 0
        self.opens: list[str] = []
        self.slint4_reads = 0
        self.slint4_paths: list[str] = []
        self.fp32_weight_reads: list[str] = []
        self.tokenizer_or_config_reads = 0
        self.torch_imports = 0
        self.imports: list[str] = []
        self.network_attempts = 0
        self.network_event_samples: list[str] = []
        self.subprocess_attempts = 0
        self.installed = False

    # -- hook ---------------------------------------------------------------
    def hook(self, event: str, args: tuple[Any, ...]) -> None:
        self.events += 1
        if event == "open":
            path = args[0]
            if not isinstance(path, str):
                try:
                    path = str(path)
                except Exception:  # pragma: no cover - defensive
                    return
            self.opens.append(path)
            lowered = path.lower()
            if SLINT4_MARKER in lowered:
                self.slint4_reads += 1
                self.slint4_paths.append(path)
            elif lowered.endswith(FP32_WEIGHT_SUFFIXES):
                self.fp32_weight_reads.append(path)
            elif lowered.endswith((".json", ".txt", ".model")):
                self.tokenizer_or_config_reads += 1
        elif event == "import":
            name = args[0] if args else ""
            self.imports.append(str(name))
            if str(name) == "torch" or str(name).startswith("torch."):
                self.torch_imports += 1
        elif event.startswith("socket."):
            self.network_attempts += 1
            detail = ""
            if args:
                try:
                    detail = str(args[0])[:120]
                except Exception:  # pragma: no cover - defensive
                    detail = "<unprintable>"
            self.network_event_samples.append(f"{event}:{detail}")
        elif event.startswith("subprocess."):
            self.subprocess_attempts += 1

    def install(self) -> "AuditRecorder":
        sys.addaudithook(self.hook)
        self.installed = True
        return self

    # -- report -------------------------------------------------------------
    def summary(self) -> dict[str, Any]:
        return {
            "audit_events_seen": self.events,
            "slint4_reads": self.slint4_reads,
            "slint4_paths": sorted(set(self.slint4_paths)),
            "fp32_weight_reads": sorted(set(self.fp32_weight_reads)),
            "fp32_weight_read_count": len(self.fp32_weight_reads),
            "tokenizer_or_config_reads": self.tokenizer_or_config_reads,
            "torch_import_attempts": self.torch_imports,
            "network_attempts": self.network_attempts,
            "network_event_samples": sorted(set(self.network_event_samples))[:5],
            "subprocess_attempts": self.subprocess_attempts,
            "total_file_opens": len(self.opens),
        }
