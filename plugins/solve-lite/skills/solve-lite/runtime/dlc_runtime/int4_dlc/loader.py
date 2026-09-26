"""Build a runnable classifier from a solve-lite.slint4 DLC directory.

Strategy (no Core / kernel changes, no transformers weight loader involved):

1. read ``config.json`` (kept next to the container) through ``AutoConfig``
2. instantiate the architecture with ``AutoModelForSequenceClassification
   .from_config`` inside a ``torch.device("meta")`` context -> zero allocation
3. replace every quantised ``nn.Linear`` / ``nn.Embedding`` with the int4
   substitute (packed payload copied into private memory)
4. assign the small kept-in-fp32 tensors (LayerNorm, biases, heads, position /
   token-type / rel embeddings) from the container
5. ``eval()`` and (optionally) attach the tracking wrapper

Everything outside the quantised projections is bit-identical to the FP32
specialist, so a decision difference can only come from the int4 weights.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .container import Slint4Container
from .format import DESCRIPTOR_FILE, NIBBLE_VALUE_ENCODING, WEIGHT_FILE
from .modules import Int4Embedding, Int4Linear
from .torch_bootstrap import warm_torch

__all__ = ["load_int4_model", "LoadStats"]


class LoadStats(dict):
    """Plain dict with attribute sugar for readability at call sites."""

    def __getattr__(self, item: str) -> Any:
        try:
            return self[item]
        except KeyError as error:  # pragma: no cover - defensive
            raise AttributeError(item) from error


def _replace_module(model: Any, dotted_path: str, new_module: Any) -> None:
    parent_path, _, attr = dotted_path.rpartition(".")
    parent = model.get_submodule(parent_path) if parent_path else model
    setattr(parent, attr, new_module)


def load_int4_model(model_dir: Path | str, *, verbose: bool = False) -> tuple[Any, Any, LoadStats]:
    """Return ``(model, container_closed_marker, stats)`` for one DLC model dir."""
    warm_torch()
    import torch
    from transformers import AutoConfig, AutoModelForSequenceClassification

    model_dir = Path(model_dir)
    descriptor_path = model_dir / DESCRIPTOR_FILE
    if not descriptor_path.is_file():
        raise FileNotFoundError(f"DESCRIPTOR_MISSING: {descriptor_path}")
    descriptor = json.loads(descriptor_path.read_text(encoding="utf-8"))
    encoding = descriptor.get("nibble_value_encoding")
    if encoding != NIBBLE_VALUE_ENCODING:
        raise ValueError(
            f"CONTAINER_NIBBLE_ENCODING_MISMATCH: descriptor says {encoding!r}, "
            f"this reader implements {NIBBLE_VALUE_ENCODING!r}"
        )

    container = Slint4Container(model_dir / WEIGHT_FILE, descriptor).open()
    linear_cls = Int4Linear
    embedding_cls = Int4Embedding
    replaced: list[str] = []
    packed_bytes = 0
    try:
        config = AutoConfig.from_pretrained(model_dir, local_files_only=True)
        with torch.device("meta"):
            model = AutoModelForSequenceClassification.from_config(config)

        for name in sorted(container.quantized):
            if not name.endswith(".weight"):
                raise ValueError(f"UNEXPECTED_QUANTIZED_TENSOR: {name}")
            path = name[: -len(".weight")]
            target = model.get_submodule(path)
            entry = container.quantized[name]
            qweight, scales = container.packed(name)
            qweight = qweight.clone().contiguous()
            scales = scales.clone().contiguous()
            packed_bytes += int(qweight.numel()) + int(scales.numel()) * scales.element_size()
            rows, cols = int(entry["shape"][0]), int(entry["shape"][1])
            #: per-tensor overrides (compression round); absent in a v1 descriptor,
            #: in which case the container-global group size / 4-bit apply.
            tensor_group = int(entry.get("group_size", container.group_size))
            tensor_bits = int(entry.get("bits", 4))
            if isinstance(target, torch.nn.Linear):
                bias = None
                if target.bias is not None:
                    bias = container.resident(name.replace(".weight", ".bias"))
                new_module = linear_cls(
                    module=target,
                    qweight=qweight,
                    scales=scales,
                    group_size=tensor_group,
                    bits=tensor_bits,
                )
            elif isinstance(target, torch.nn.Embedding):
                new_module = embedding_cls(
                    module=target,
                    qweight=qweight,
                    scales=scales,
                    group_size=tensor_group,
                    bits=tensor_bits,
                )
            else:  # pragma: no cover - guarded by the quantizer policy
                raise TypeError(f"UNSUPPORTED_QUANTIZED_MODULE: {path} ({type(target).__name__})")
            _replace_module(model, path, new_module)
            replaced.append(path)

        kept_state = {name: container.resident(name) for name in container.kept_fp32}
        # assign=True is REQUIRED: the model was built on the meta device, and a
        # plain copy_() into a meta parameter is a silent no-op (every kept
        # tensor would stay on meta).  With assign=True torch swaps in the real
        # CPU tensors; the meta placeholders that are not in kept_state (the
        # int4 modules' unused ``.weight``) are left on meta on purpose.
        incompatible = model.load_state_dict(kept_state, strict=False, assign=True)
        kept_bytes = sum(int(t.numel()) * t.element_size() for t in kept_state.values())
        del kept_state
        # Buffers that exist in the architecture but NOT in the checkpoint (e.g.
        # distilbert's ``position_ids``) would otherwise stay on the meta device;
        # a forward then reads uninitialised memory and yields input-dependent
        # NaNs.  Materialise them deterministically here.
        fixed_buffers: list[str] = []
        left_meta: list[str] = []
        for name, buf in list(model.named_buffers()):
            if not buf.is_meta:
                continue
            if name.endswith("position_ids"):
                count = int(buf.shape[-1])
                value = torch.arange(count, dtype=buf.dtype).expand(buf.shape).contiguous()
            else:
                value = torch.zeros(tuple(buf.shape), dtype=buf.dtype)
            parent_path, _, attr = name.rpartition(".")
            parent = model.get_submodule(parent_path) if parent_path else model
            parent.register_buffer(attr, value, persistent=False)
            fixed_buffers.append(name)
        for name, param in list(model.named_parameters()):
            if param.is_meta:
                left_meta.append(name)
    finally:
        container.close()

    model.eval()
    stats = LoadStats(
        dlc_id=descriptor.get("dlc_id"),
        family=descriptor.get("family"),
        quantized_modules=len(replaced),
        kept_tensors=len(container.kept_fp32),
        packed_bytes=packed_bytes,
        kept_bytes=kept_bytes,
        resident_weight_bytes=packed_bytes + kept_bytes,
        fp32_reference_bytes=int(descriptor["source"]["weight_bytes"]),
        missing_keys=[k for k in incompatible.missing_keys if not k.endswith(".weight")],
        unexpected_keys=list(incompatible.unexpected_keys),
        fixed_meta_buffers=sorted(fixed_buffers),
        meta_weight_placeholders=len(left_meta),
    )
    if verbose:
        print(json.dumps(stats, indent=2, sort_keys=True))
    return model, stats
