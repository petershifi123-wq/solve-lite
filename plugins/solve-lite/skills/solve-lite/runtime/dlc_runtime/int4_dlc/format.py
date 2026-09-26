"""INT4 DLC on-disk format constants for the solve-lite specialist INT4 DLC.

Format name:  solve-lite.slint4  (container version 1)
Container:    a safetensors file holding, per quantized tensor,
                <name>.qweight  uint8  [rows, ceil(cols/2)]   two int4 nibbles per byte
                <name>.scales   float16[row, ceil(cols/group_size)]
              plus every NOT-quantized tensor under its original name.
              The safetensors ``__metadata__`` header carries the descriptor JSON.
Nibble order: low nibble = even column index 2*i, high nibble = column 2*i+1.
Value domain: signed symmetric int4, q in [-8, 7], two's complement in the nibble.

Nothing in this module imports torch at import time; the reader is used by the
runtime on the optional (explicitly activated) path only.
"""

from __future__ import annotations

FORMAT_NAME = "solve-lite.slint4"
FORMAT_VERSION = 1

DESCRIPTOR_FILE = "slint4.json"
#: The container name carries the ``.safetensors`` extension on purpose: the
#: frozen kernel derives its per-route weight hash by globbing
#: ``*.safetensors`` / ``*.bin`` inside the model directory
#: (BUILD/lite_src/_src5_lite.py:208,209,247,281,321).  The container *is* a
#: safetensors file, so that hash is a genuine hash of the int4 payload and the
#: unmodified kernel keeps working.  It is never handed to
#: ``from_pretrained``: the DLC loader reads ``config.json`` only.
WEIGHT_FILE = "model.slint4.safetensors"
MANIFEST_FILE = "dlc.json"

DEFAULT_GROUP_SIZE = 64
ALLOWED_GROUP_SIZES = (16, 32, 64, 128)

QMIN = -8
QMAX = 7

SCHEME_SYMMETRIC_RTN = "symmetric_rtn_int4_weight_only"
#: Nibble value encoding: the writer stores ``value + 8``, the reader subtracts 8.
NIBBLE_VALUE_ENCODING = "offset_binary_minus8"

#: licence distribution classes (VV ruling of the INT4 DLC task)
LICENSE_OFFICIAL_APACHE2 = "OFFICIAL_DLC_APACHE_2_0"
LICENSE_ENGINEERING_ONLY = "ENGINEERING_VERIFICATION_ONLY_DO_NOT_DISTRIBUTE"

#: addon-relative paths
ADDON_DIRNAME = "solve-lite-int4-dlc"
ADDON_REGISTRY_FILE = "dlc-registry.json"
ADDON_EVENT_LOG = "dlc-events.jsonl"
ADDON_ASSET_ROOT_DIRNAME = "asset-root"

#: markers used when a DLC in the assembled asset root is not installed
NOT_INSTALLED_MARKER = "DLC_NOT_INSTALLED.json"

STATUS_INSTALLED = "DLC_INSTALLED"
STATUS_NOT_INSTALLED = "DLC_NOT_INSTALLED"
STATUS_LOADED = "DLC_LOADED"
STATUS_UNLOADED = "DLC_UNLOADED"
STATUS_UNLOADED_IDLE = "DLC_UNLOADED_IDLE"

#: honesty label carried by every INT4-result artifact
PRECISION_LABEL = "INT4_WEIGHT_ONLY_DEQUANT_FP32_ACCUM"


def nibble_pack_bytes(cols: int) -> int:
    """Packed byte width for ``cols`` int4 values (odd column counts pad up)."""
    return (cols + 1) // 2
