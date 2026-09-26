"""Generic low-bit weight quantization: bits in {2, 3, 4}, group-wise symmetric RTN.

This is the compression-round extension of the int4 writer.  Nothing here is
new numerics: ``quantize_grouped`` with ``bits=4`` is bit-for-bit the same
computation as ``quantize.quantize_matrix`` and ``pack_lowbits`` with
``bits=4`` is byte-for-byte the same packing as ``quantize._pack_nibbles``.
That equivalence is asserted by ``tests/test_lowbits_equivalence.py`` -- if it
ever drifts, every "same as the shipped int4 DLC" claim in the compression
round becomes meaningless.

Bit stream convention (must match ``container.decode_lowbits``): the packed
stream is LSB-first both *within* a value and *within* a byte.  Value ``v`` at
column ``c`` occupies stream positions ``c*bits ... c*bits + bits - 1`` with
``v``'s bit 0 at the lowest position, and stream position ``p`` lives in byte
``p // 8`` at bit ``p % 8``.  For ``bits=4`` that yields exactly the documented
container layout "low nibble = even column index", which is why the existing
reader keeps working unchanged.

Value encoding is OFFSET BINARY, matching the shipped int4 container: the
writer stores ``q + 2**(bits-1)`` (so for int4 ``[-8, 7] -> [0, 15]``) and the
reader subtracts it back.  Two's complement would scramble every weight.

No torch import at module import time: the writer is build-time, the reader is
used on the explicitly activated DLC path only.
"""

from __future__ import annotations

from typing import Any

#: signed symmetric range per bit width, value = 2**(bits-1) - 1 is the positive cap
BITS_RANGE = {2: (-2, 1), 3: (-4, 3), 4: (-8, 7)}
SUPPORTED_BITS = tuple(sorted(BITS_RANGE))


def qmin_qmax(bits: int) -> tuple[int, int]:
    try:
        return BITS_RANGE[int(bits)]
    except KeyError as error:
        raise ValueError(f"UNSUPPORTED_BITS: {bits} (supported: {SUPPORTED_BITS})") from error


def packed_row_bytes(cols: int, bits: int) -> int:
    """Bytes one row of ``cols`` values occupies when bit-packed at ``bits``."""
    return (int(cols) * int(bits) + 7) // 8


# --------------------------------------------------------------------------- #
# writer
# --------------------------------------------------------------------------- #
def pack_lowbits(values: Any, bits: int) -> Any:
    """int tensor (last dim = columns, already group-padded) -> uint8 bit stream."""
    import torch

    bits = int(bits)
    qlo, _qhi = qmin_qmax(bits)
    if values.shape[-1] * bits % 8:
        raise ValueError(
            f"bit packing requires (cols*bits) % 8 == 0, got cols={values.shape[-1]} bits={bits}"
        )
    unsigned = (values.to(torch.int64) - qlo) & ((1 << bits) - 1)
    shifts = torch.arange(bits, dtype=torch.int64, device=unsigned.device)
    # bit_lsb_first[..., c, j] = bit j of column c  -> stream position c*bits + j
    bit_lsb_first = (unsigned.unsqueeze(-1) >> shifts) & 1
    rows = unsigned.shape[0]
    stream = bit_lsb_first.reshape(rows, -1)
    byte_weights = (1 << torch.arange(8, dtype=torch.int64, device=unsigned.device))
    bytes_ = (stream.reshape(rows, -1, 8) * byte_weights).sum(dim=-1)
    return bytes_.to(torch.uint8).contiguous()


def unpack_lowbits(packed: Any, cols: int, bits: int) -> Any:
    """Inverse of :func:`pack_lowbits`; returns int16 ``[..., cols]``."""
    import torch

    bits = int(bits)
    qlo, _qhi = qmin_qmax(bits)
    rows = packed.shape[0]
    byte_bits = ((packed.to(torch.int64).unsqueeze(-1) >> torch.arange(8, dtype=torch.int64)) & 1)
    stream = byte_bits.reshape(rows, -1)
    stream = stream[:, : int(cols) * bits]
    values = (stream.reshape(rows, int(cols), bits) * (1 << torch.arange(bits, dtype=torch.int64))).sum(-1)
    return (values + qlo).to(torch.int16)


def quantize_grouped(weight: Any, group_size: int, bits: int) -> tuple[Any, Any, dict[str, float]]:
    """Group-wise symmetric RTN at ``bits``.  bits=4 + group 64 == shipped int4 writer."""
    import torch

    bits = int(bits)
    qlo, qmax_pos = qmin_qmax(bits)
    qmax = float(qmax_pos)
    if weight.dim() != 2:
        raise ValueError(f"quantize_grouped expects 2-D weight, got {tuple(weight.shape)}")
    group_size = int(group_size)
    rows, cols = int(weight.shape[0]), int(weight.shape[1])
    pad = (-cols) % group_size
    source = weight.detach().to(torch.float32)
    if pad:
        source = torch.nn.functional.pad(source, (0, pad))
    grouped = source.reshape(rows, -1, group_size)
    max_abs = grouped.abs().amax(dim=2, keepdim=True)
    scale = max_abs / qmax
    quantized = torch.round(grouped / scale).clamp(qlo, qmax_pos)
    quantized = torch.where(max_abs == 0, torch.zeros_like(quantized), quantized)
    flat_q = quantized.reshape(rows, -1).to(torch.int16)
    scales = scale.reshape(rows, -1).squeeze(-1).to(torch.float16)
    packed = pack_lowbits(flat_q, bits)

    restored = (
        flat_q.to(torch.float32) * scales.to(torch.float32).repeat_interleave(group_size, dim=1)
    )[:, :cols]
    diff = restored - weight.detach().to(torch.float32)
    denom = float(torch.linalg.vector_norm(weight.detach().to(torch.float32)))
    stats = {
        "bits": bits,
        "group_size": group_size,
        "padded_cols": int(pad),
        "groups_per_row": int(flat_q.shape[1] // group_size),
        "max_abs_err_stored_scale": float(diff.abs().max()) if diff.numel() else 0.0,
        "rel_fro_err_stored_scale": (float(torch.linalg.vector_norm(diff)) / denom) if denom > 0 else 0.0,
        "packed_bytes": int(packed.numel()),
        "scale_bytes": int(scales.numel() * 2),
    }
    return packed, scales, stats
