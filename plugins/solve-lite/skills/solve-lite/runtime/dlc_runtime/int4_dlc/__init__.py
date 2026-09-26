"""solve-lite INT4 specialist DLC — quantizer, container runtime, registry.

Package layout
--------------
  format.py     on-disk format constants (solve-lite.slint4 v1)
  quantize.py   BUILD-TIME reproducible INT4 RTN quantizer (needs torch)
  container.py  read-only container reader (used on the optional path)
  modules.py    nn.Module replacements that dequantise weights on the fly
  loader.py     rebuild a HF model from an INT4 descriptor (no fp32 residency)
  runtime.py    DLC manager: lazy load, ONE AT A TIME, idle unload
  registry.py   DLC-aware capability registry
  doctor.py     doctor checks (offline, no model load)
  installer.py  install / uninstall / assemble asset root
  activate.py   the single wiring hook into the frozen kernel
  meter.py      resident-set-size measurement without third-party deps
"""

from __future__ import annotations

from .format import FORMAT_NAME, FORMAT_VERSION  # noqa: F401

__all__ = ["FORMAT_NAME", "FORMAT_VERSION", "__version__"]
__version__ = "1.0.0"
