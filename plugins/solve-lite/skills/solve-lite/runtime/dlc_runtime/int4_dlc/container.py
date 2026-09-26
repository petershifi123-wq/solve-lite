"""Read-only reader for the solve-lite.slint4 container (optional DLC path only).

The container is a plain safetensors file:

    <name>.qweight   uint8   [rows, ceil(cols/2)]     two int4 nibbles per byte
    <name>.scales    float16 [rows, cols/group_size]
    <name>           <dtype> every tensor that was kept in fp32

The reader never materialises a dequantised tensor unless asked, so the
resident footprint of a loaded DLC is the packed int4 payload plus the small
fp32 remainder.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from .format import DESCRIPTOR_FILE, FORMAT_NAME, FORMAT_VERSION


def decode_nibbles(packed: Any, cols: int) -> Any:
    """uint8 paired nibbles -> int8 [..., cols] (low nibble = even column).

    Value encoding is OFFSET BINARY, not two's complement: the writer stores
    ``value + 8`` (so [-8, 7] -> [0, 15]), therefore the reader subtracts 8.
    Using the two's complement reinterpretation here would scramble every
    weight (caught by the round-trip test -- the error is ~30x too big).
    """
    import torch

    low = (packed & 0x0F).to(torch.int16)
    high = ((packed >> 4) & 0x0F).to(torch.int16)
    joined = torch.stack((low, high), dim=-1).reshape(*packed.shape[:-1], packed.shape[-1] * 2)
    return (joined - 8)[..., :cols].to(torch.int8)


def decode_lowbits(packed: Any, cols: int, bits: int) -> Any:
    """Generic ``bits``-wide reader for the bit-packed weight stream.

    ``bits=4`` reproduces :func:`decode_nibbles` exactly (the bit-stream order is
    LSB-first both inside a value and inside a byte, so the low nibble is still
    column 0).  Anything from :mod:`int4_dlc.lowbits` reads back through here.
    """
    from .lowbits import unpack_lowbits

    return unpack_lowbits(packed, cols, bits)


def dequantize(
    packed: Any,
    scales: Any,
    group_size: int,
    cols: int,
    rows: Any = None,
    bits: int = 4,
) -> Any:
    """Packed low-bit weight (+ per-group fp16 scales) -> fp32 matrix.

    ``rows`` optionally selects a subset of rows first (used by embedding
    lookups so that a 128k-vocab table is never fully dequantised).
    ``bits`` defaults to 4, which is the shipped container: every v1 descriptor
    and every caller written before the compression round is unaffected.
    """
    import torch

    bits = int(bits)
    if rows is not None:
        packed = packed[rows]
        scales = scales[rows]
    if bits == 4:
        flat = decode_nibbles(packed, ((packed.shape[-1] * 2) if cols is None else cols))
    else:
        flat = decode_lowbits(packed, (cols if cols is not None else packed.shape[-1] * 8 // bits), bits)
    if cols is not None:
        flat = flat[..., :cols]
    expanded = scales.to(torch.float32).repeat_interleave(group_size, dim=-1)[..., : flat.shape[-1]]
    return flat.to(torch.float32) * expanded


def dequantize_rows(
    packed: Any, scales: Any, group_size: int, cols: int, rows: Any, bits: int = 4
) -> Any:
    """Row-gather dequantisation (embedding lookups never touch the whole table)."""
    return dequantize(packed, scales, group_size, cols, rows=rows, bits=bits)


class Slint4Container:
    """Opens one model.slint4 container and exposes packed tensors by name."""

    def __init__(self, container_path: Path | str, descriptor: dict[str, Any] | None = None):
        self.path = Path(container_path)
        if not self.path.is_file():
            raise FileNotFoundError(f"CONTAINER_MISSING: {self.path}")
        if descriptor is None:
            sidecar = self.path.parent / DESCRIPTOR_FILE
            if not sidecar.is_file():
                raise FileNotFoundError(f"DESCRIPTOR_MISSING: {sidecar}")
            descriptor = json.loads(sidecar.read_text(encoding="utf-8"))
        self.descriptor = descriptor
        if descriptor.get("format") != FORMAT_NAME:
            raise ValueError(f"CONTAINER_FORMAT_MISMATCH: {descriptor.get('format')}")
        if int(descriptor.get("format_version", -1)) != FORMAT_VERSION:
            raise ValueError(f"CONTAINER_VERSION_MISMATCH: {descriptor.get('format_version')}")
        self.group_size = int(descriptor["group_size"])
        self.quantized: dict[str, dict[str, Any]] = {
            row["name"]: row for row in descriptor["tensors"] if row["quantized"]
        }
        self.kept_fp32: list[str] = [row["name"] for row in descriptor["tensors"] if not row["quantized"]]
        self._handle = None

    # -- lifecycle ---------------------------------------------------------
    def open(self) -> "Slint4Container":
        from safetensors import safe_open

        if self._handle is None:
            self._handle = safe_open(str(self.path), framework="pt", device="cpu")
        return self

    def close(self) -> None:
        self._handle = None

    def __enter__(self) -> "Slint4Container":
        return self.open()

    def __exit__(self, *exc: Any) -> None:
        self.close()

    @property
    def closed(self) -> bool:
        return self._handle is None

    # -- tensor access -----------------------------------------------------
    def _require_open(self):
        if self._handle is None:
            raise RuntimeError("CONTAINER_CLOSED")
        return self._handle

    def tensor_names(self) -> list[str]:
        return list(self._require_open().keys())

    def raw(self, name: str) -> Any:
        """Zero-copy view of a stored tensor (mmap-backed)."""
        return self._require_open().get_tensor(name)

    def resident(self, name: str) -> Any:
        """Private copy of a stored tensor (used for kept-fp32 weights)."""
        return self.raw(name).clone()

    def packed(self, tensor_name: str) -> tuple[Any, Any]:
        entry = self.quantized[tensor_name]
        return self.raw(f"{tensor_name}.qweight"), self.raw(f"{tensor_name}.scales")

    def dequant(self, tensor_name: str, rows: Any = None) -> Any:
        entry = self.quantized[tensor_name]
        packed, scales = self.packed(tensor_name)
        return dequantize(
            packed,
            scales,
            int(entry.get("group_size", self.group_size)),
            int(entry["shape"][1]),
            rows=rows,
            bits=int(entry.get("bits", 4)),
        )

    def kept_tensors(self) -> Iterable[tuple[str, Any]]:
        for name in self.kept_fp32:
            yield name, self.resident(name)
