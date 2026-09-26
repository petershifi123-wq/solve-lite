"""INT4 drop-in modules: weight-only int4 with dequant-on-the-forward.

Numerics: the packed int4 weight is dequantised to fp32 and multiplied with the
fp32 activation, i.e. exactly what a weight-only 4-bit kernel does (weights 4-bit,
activations/accumulation fp32).  No activation quantisation, no scaling of the
residual stream.

Every instance registers itself in ``LIVE_INT4_MODULES`` (a weak set).  That is
the independent proof used by the unload gate: after unload + gc the set is empty,
so the int4 bytes are really gone and not merely dereferenced.
"""

from __future__ import annotations

import weakref
from typing import Any

#: live int4 modules -> independent evidence for the "really unloaded" gate
LIVE_INT4_MODULES: "weakref.WeakSet[Any]" = weakref.WeakSet()


def live_int4_stats() -> dict[str, int]:
    """(modules, packed_bytes) currently resident in this process."""
    modules = [module for module in LIVE_INT4_MODULES]
    packed = sum(int(getattr(module, "resident_bytes", 0)) for module in modules)
    return {"modules": len(modules), "packed_bytes": packed}


class Int4LinearMixin:
    """Mixin holding the packed payload + dequant for a Linear-style weight."""

    def _init_int4(self, qweight, scales, group_size: int, cols: int, bits: int = 4) -> None:
        from .container import dequantize

        self._dequantize = dequantize
        self.group_size = int(group_size)
        self.bits = int(bits)
        self._cols = int(cols)
        self.register_buffer("qweight", qweight, persistent=False)
        self.register_buffer("scales", scales, persistent=False)
        self.resident_bytes = int(qweight.numel()) + int(scales.numel() * 2)
        LIVE_INT4_MODULES.add(self)

    def dequant_weight(self):
        """fp32 [out, in] view of the packed weight (transient, freed per forward)."""
        return self._dequantize(self.qweight, self.scales, self.group_size, self._cols, bits=self.bits)


def _make_linear_class():
    """Build nn.Linear subclass bound to the int4 payload.

    NOTE: it must *subclass* nn.Linear -- calling ``nn.Linear.__init__`` on a
    plain object fails torch's ``super(type, obj)`` check.
    """
    import torch.nn as nn

    class _Int4Linear(Int4LinearMixin, nn.Linear):
        def __init__(self, module, qweight, scales, group_size: int, bits: int = 4):
            in_features = int(module.in_features)
            out_features = int(module.out_features)
            has_bias = module.bias is not None
            nn.Linear.__init__(self, in_features, out_features, bias=has_bias, device="meta")
            self._init_int4(qweight, scales, group_size, in_features, bits=bits)
            if has_bias:
                self.bias = nn.Parameter(module.bias.detach().clone(), requires_grad=False)

        def forward(self, inputs):
            import torch.nn.functional as F

            return F.linear(inputs, self.dequant_weight(), self.bias)

    return _Int4Linear


Int4Linear = _make_linear_class()


class Int4EmbeddingMixin:
    """Mixin holding the packed payload + row-gather dequant for an Embedding."""

    def _init_int4_embedding(self, qweight, scales, group_size: int, dim: int, bits: int = 4) -> None:
        import torch

        from .container import dequantize_rows

        self._dequantize_rows = dequantize_rows
        self._torch = torch
        self.group_size = int(group_size)
        self.bits = int(bits)
        self._dim = int(dim)
        self.register_buffer("qweight", qweight, persistent=False)
        self.register_buffer("scales", scales, persistent=False)
        self.resident_bytes = int(qweight.numel()) + int(scales.numel() * 2)
        LIVE_INT4_MODULES.add(self)

    def _lookup(self, ids):
        """Dequantise only the rows that are actually requested."""
        torch = self._torch
        flat = ids.reshape(-1).to(torch.long)
        rows = self._dequantize_rows(
            self.qweight, self.scales, self.group_size, self._dim, flat, bits=self.bits
        )
        return rows.reshape(*ids.shape, self._dim)


def _make_embedding_class():
    import torch
    import torch.nn as nn

    class _Int4Embedding(Int4EmbeddingMixin, nn.Embedding):
        def __init__(self, module, qweight, scales, group_size: int, bits: int = 4):
            num_embeddings = int(module.num_embeddings)
            embedding_dim = int(module.embedding_dim)
            padding_idx = getattr(module, "padding_idx", None)
            nn.Embedding.__init__(
                self,
                num_embeddings,
                embedding_dim,
                padding_idx=padding_idx,
                device="meta",
            )
            self._init_int4_embedding(qweight, scales, group_size, embedding_dim, bits=bits)

        def forward(self, ids):
            return self._lookup(ids)

    return _Int4Embedding


Int4Embedding = _make_embedding_class()
