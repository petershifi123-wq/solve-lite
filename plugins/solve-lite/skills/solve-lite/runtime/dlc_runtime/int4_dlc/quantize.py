"""Reproducible INT4 (weight-only, symmetric RTN, per-group scale) quantizer.

This is a BUILD-TIME tool.  It reads an existing FP32 HuggingFace model directory
(never modified) and writes an INT4 DLC container + descriptor.

Numerics
--------
  group size G (default 64) along the last (contraction) dimension
  scale_g = max|w_g| / 7                (symmetric, int4 range [-8, 7])
  q       = clamp(round(w / scale_g), -8, 7)
  w_hat   = q * scale_g                 (this is what the runtime feeds to fp32 GEMM)

The runtime therefore reproduces exactly the arithmetic of a weight-only INT4
kernel that dequantises into fp32 and accumulates in fp32.  It is NOT a claim
about any particular vendor kernel's internal accumulation order.

CLI
---
  PYTHONPATH=dlc-src python3 -m int4_dlc.quantize \
      --src <fp32_dir> --out <out_dir> --dlc-id <id> --family <route> \
      --model-dir-rel <relative path> \
      --license-class <OFFICIAL_DLC_APACHE_2_0|ENGINEERING_VERIFICATION_ONLY_DO_NOT_DISTRIBUTE> \
      [--license-spdx Apache-2.0] [--license-evidence <text>] [--source-repo <hf id>] \
      [--group-size 64] [--device cpu]
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import platform
import sys
import time
from pathlib import Path
from typing import Any

from .format import (
    ALLOWED_GROUP_SIZES,
    DEFAULT_GROUP_SIZE,
    DESCRIPTOR_FILE,
    FORMAT_NAME,
    FORMAT_VERSION,
    NIBBLE_VALUE_ENCODING,
    PRECISION_LABEL,
    QMAX,
    QMIN,
    SCHEME_SYMMETRIC_RTN,
    WEIGHT_FILE,
)

#: module-name fragments whose weights stay in fp32 (decision-critical head/pooler,
#: positional tables and 1-D state).  Rationale is recorded in the descriptor.
KEEP_FP32_PATTERNS = (
    "classifier",
    ".score",
    "pre_classifier",
    "pooler",
    "position_embeddings",
    "rel_embeddings",
    "token_type_embeddings",
)


def sha256_file(path: Path, block: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(block), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _requires_torch():
    from .torch_bootstrap import warm_torch

    try:
        warm_torch()
        import torch  # noqa: F401
    except ImportError as error:  # pragma: no cover - build-time guard
        raise SystemExit(f"BUILD_TOOL_REQUIRES_TORCH: {error}") from error


def load_state_dict(model_dir: Path) -> tuple[dict[str, Any], str]:
    """Load the FP32 state dict from a HF model dir; returns (state, weight_file)."""
    import torch

    candidates = sorted(model_dir.glob("*.safetensors")) + sorted(model_dir.glob("*.bin"))
    if not candidates:
        raise SystemExit(f"NO_WEIGHT_FILE: {model_dir}")
    for path in candidates:
        if path.suffix == ".safetensors":
            from safetensors.torch import load_file

            state = load_file(str(path), device="cpu")
        else:
            state = torch.load(str(path), map_location="cpu", weights_only=True)
        if not isinstance(state, dict) or not state:
            raise SystemExit(f"EMPTY_STATE_DICT: {path}")
        return state, path.name
    raise SystemExit(f"NO_WEIGHT_FILE: {model_dir}")


def _module_kinds(model_dir: Path) -> tuple[dict[str, str], str]:
    """(name -> 'linear' | 'embedding' | 'other', architecture class name)."""
    import torch
    from transformers import AutoConfig, AutoModelForSequenceClassification

    config = AutoConfig.from_pretrained(str(model_dir), local_files_only=True)
    with torch.device("meta"):
        model = AutoModelForSequenceClassification.from_config(config)
    kinds: dict[str, str] = {}
    for name, module in model.named_modules():
        if not name:
            continue
        if isinstance(module, torch.nn.Linear):
            kinds[f"{name}.weight"] = "linear"
            if module.bias is not None:
                kinds[f"{name}.bias"] = "other"
        elif isinstance(module, torch.nn.Embedding):
            kinds[f"{name}.weight"] = "embedding"
        elif isinstance(module, torch.nn.LayerNorm):
            kinds[f"{name}.weight"] = "other"
    architecture = type(model).__name__
    del model
    return kinds, architecture


def _pack_nibbles(values) -> Any:
    """Pack an int tensor with last dim even into uint8, low nibble = index 2*i."""
    import torch

    if values.shape[-1] % 2:
        raise ValueError("nibble packing requires an even last dimension")
    unsigned = (values + 8).to(torch.uint8)  # [-8,7] -> [0,15]
    low = unsigned[..., 0::2]
    high = unsigned[..., 1::2]
    return (low | (high << 4)).contiguous()


def unpack_nibbles(packed: Any, cols: int) -> Any:
    """Inverse of _pack_nibbles (kept next to the writer on purpose).

    Value encoding is offset binary (``+8`` on write), so the reader does
    ``-8``: mirror of ``int4_dlc.container.decode_nibbles``.
    """
    import torch

    low = (packed & 0x0F).to(torch.int16)
    high = ((packed >> 4) & 0x0F).to(torch.int16)
    stacked = torch.stack((low, high), dim=-1).reshape(*packed.shape[:-1], packed.shape[-1] * 2)
    return (stacked - 8)[..., :cols].to(torch.int8)


def quantize_matrix(weight, group_size: int) -> tuple[Any, Any, dict[str, float]]:
    """Group-wise symmetric RTN int4 for a 2-D weight tensor."""
    import torch

    if weight.dim() != 2:
        raise ValueError(f"quantize_matrix expects 2-D weight, got {tuple(weight.shape)}")
    rows, cols = weight.shape
    pad = (-cols) % group_size
    source = weight.detach().to(torch.float32)
    if pad:
        source = torch.nn.functional.pad(source, (0, pad))
    grouped = source.reshape(rows, -1, group_size)
    max_abs = grouped.abs().amax(dim=2, keepdim=True)
    scale = max_abs / float(QMAX)
    quantized = torch.round(grouped / scale).clamp(QMIN, QMAX)
    quantized = torch.where(max_abs == 0, torch.zeros_like(quantized), quantized)
    flat_q = quantized.reshape(rows, -1)
    packed = _pack_nibbles(flat_q)
    scales = scale.reshape(rows, -1).squeeze(-1).to(torch.float16)

    restored = (
        flat_q.to(torch.float32) * scale.reshape(rows, -1).repeat_interleave(group_size, dim=1)
    )[:, :cols]
    diff = restored - weight.detach().to(torch.float32)
    denom = float(torch.linalg.vector_norm(weight.detach().to(torch.float32)))
    # Same reconstruction, but driven by the *stored* fp16 scales: this is the
    # error the runtime actually produces (the fp32-scale figure below is the
    # writer's ideal and is reported separately so nothing is overstated).
    restored_stored = (
        flat_q.to(torch.float32) * scales.to(torch.float32).repeat_interleave(group_size, dim=1)
    )[:, :cols]
    diff_stored = restored_stored - weight.detach().to(torch.float32)
    stats = {
        "max_abs_err": float(diff.abs().max()) if diff.numel() else 0.0,
        "rms_err": float(diff.pow(2).mean().sqrt()) if diff.numel() else 0.0,
        "rel_fro_err": float(torch.linalg.vector_norm(diff)) / denom if denom > 0 else 0.0,
        "max_abs_err_stored_scale": float(diff_stored.abs().max()) if diff_stored.numel() else 0.0,
        "rel_fro_err_stored_scale": (
            float(torch.linalg.vector_norm(diff_stored)) / denom if denom > 0 else 0.0
        ),
        "padded_cols": int(pad),
        "groups_per_row": int(flat_q.shape[1] // group_size),
    }
    return packed, scales, stats


def quantize_model_dir(
    model_dir: Path,
    out_dir: Path,
    *,
    group_size: int = DEFAULT_GROUP_SIZE,
    dlc_id: str,
    family: str,
    model_dir_rel: str,
    license_class: str,
    license_spdx: str | None = None,
    license_evidence: list[str] | None = None,
    source_repo: str | None = None,
) -> dict[str, Any]:
    _requires_torch()
    import torch
    from safetensors.torch import save_file

    if group_size not in ALLOWED_GROUP_SIZES:
        raise SystemExit(f"BAD_GROUP_SIZE: {group_size} not in {ALLOWED_GROUP_SIZES}")
    started = time.time()
    out_dir.mkdir(parents=True, exist_ok=True)
    state, weight_file_name = load_state_dict(model_dir)
    weight_path = model_dir / weight_file_name
    kinds, architecture = _module_kinds(model_dir)

    tensors: list[dict[str, Any]] = []
    payload: dict[str, Any] = {}
    params_total = 0
    params_quant = 0
    for name in sorted(state):
        tensor = state[name]
        params_total += int(tensor.numel())
        kind = kinds.get(name, "other")
        quantizable = (
            kind in {"linear", "embedding"}
            and tensor.dim() == 2
            and not any(pattern in f".{name}" for pattern in KEEP_FP32_PATTERNS)
        )
        if not quantizable:
            keep = tensor.contiguous()
            payload[name] = keep
            tensors.append(
                {
                    "name": name,
                    "kind": kind,
                    "quantized": False,
                    "dtype": str(keep.dtype).replace("torch.", ""),
                    "shape": list(tensor.shape),
                    "params": int(tensor.numel()),
                    "reason": "kept_fp32",
                }
            )
            continue
        packed, scales, stats = quantize_matrix(tensor, group_size)
        payload[f"{name}.qweight"] = packed
        payload[f"{name}.scales"] = scales
        params_quant += int(tensor.numel())
        tensors.append(
            {
                "name": name,
                "kind": kind,
                "quantized": True,
                "shape": list(tensor.shape),
                "params": int(tensor.numel()),
                "group_size": group_size,
                "scheme": SCHEME_SYMMETRIC_RTN,
                "packed_bytes": int(packed.numel()),
                "scale_bytes": int(scales.numel() * 2),
                **stats,
            }
        )
    del state

    container = out_dir / WEIGHT_FILE
    save_file(payload, str(container), metadata={"format": FORMAT_NAME, "version": str(FORMAT_VERSION)})
    del payload

    container_bytes = container.stat().st_size
    descriptor = {
        "format": FORMAT_NAME,
        "format_version": FORMAT_VERSION,
        "descriptor_version": 1,
        "dlc_id": dlc_id,
        "family": family,
        "model_dir_rel": model_dir_rel,
        "architecture": architecture,
        "precision_label": PRECISION_LABEL,
        "activation": "none (weight-only)",
        "accumulation": "fp32",
        "device_for_int4": "cpu",
        "scheme": SCHEME_SYMMETRIC_RTN,
        "group_size": group_size,
        "nibble_order": "low=even_index",
        "nibble_value_encoding": NIBBLE_VALUE_ENCODING,
        "value_range": [QMIN, QMAX],
        "keep_fp32_patterns": list(KEEP_FP32_PATTERNS),
        "source": {
            "path": str(model_dir),
            "weight_file": weight_file_name,
            "weight_bytes": int(weight_path.stat().st_size),
            "weight_sha256": sha256_file(weight_path),
            "source_repo": source_repo,
        },
        "license": {
            "class": license_class,
            "spdx": license_spdx,
            "evidence": list(license_evidence or []),
            "distributable": license_class == "OFFICIAL_DLC_APACHE_2_0",
        },
        "container": {
            "file": WEIGHT_FILE,
            "bytes": int(container_bytes),
            "sha256": sha256_file(container),
        },
        "totals": {
            "params_total": params_total,
            "params_quantized": params_quant,
            "params_fp32": params_total - params_quant,
            "container_bytes": int(container_bytes),
            "fp32_weight_bytes": int(weight_path.stat().st_size),
            "compression_ratio": round(weight_path.stat().st_size / max(container_bytes, 1), 4),
        },
        "tensors": tensors,
        "build": {
            "host": platform.platform(),
            "machine": platform.machine(),
            "torch": torch.__version__,
            "python": sys.version.split()[0],
            "utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            "seconds": round(time.time() - started, 3),
            "reproduce": (
                f"PYTHONPATH=dlc-src python3 -m int4_dlc.quantize --src {model_dir} "
                f"--out {out_dir} --dlc-id {dlc_id} --family {family} "
                f"--model-dir-rel {model_dir_rel} --license-class {license_class} "
                f"--group-size {group_size}"
            ),
        },
    }
    (out_dir / DESCRIPTOR_FILE).write_text(json.dumps(descriptor, indent=2, sort_keys=True), encoding="utf-8")
    report = {
        "dlc_id": dlc_id,
        "container_bytes": int(container_bytes),
        "container_mb": round(container_bytes / 1e6, 2),
        "fp32_bytes": int(weight_path.stat().st_size),
        "fp32_mb": round(weight_path.stat().st_size / 1e6, 2),
        "params_total": params_total,
        "params_quantized": params_quant,
        "quantized_tensor_count": sum(1 for row in tensors if row["quantized"]),
        "fp32_tensor_count": sum(1 for row in tensors if not row["quantized"]),
        "worst_rel_fro_err": max(
            (row.get("rel_fro_err", 0.0) for row in tensors if row["quantized"]), default=0.0
        ),
        "worst_max_abs_err": max(
            (row.get("max_abs_err", 0.0) for row in tensors if row["quantized"]), default=0.0
        ),
        "group_size": group_size,
        "descriptor": str(out_dir / DESCRIPTOR_FILE),
    }
    (out_dir / "QUANTIZATION_REPORT.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="INT4 RTN weight-only quantizer (build tool)")
    parser.add_argument("--src", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--dlc-id", required=True)
    parser.add_argument("--family", required=True)
    parser.add_argument("--model-dir-rel", required=True)
    parser.add_argument("--license-class", required=True)
    parser.add_argument("--license-spdx", default=None)
    parser.add_argument("--license-evidence", action="append", default=[])
    parser.add_argument("--source-repo", default=None)
    parser.add_argument("--group-size", type=int, default=DEFAULT_GROUP_SIZE)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = quantize_model_dir(
        Path(args.src),
        Path(args.out),
        group_size=args.group_size,
        dlc_id=args.dlc_id,
        family=args.family,
        model_dir_rel=args.model_dir_rel,
        license_class=args.license_class,
        license_spdx=args.license_spdx,
        license_evidence=args.license_evidence,
        source_repo=args.source_repo,
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
