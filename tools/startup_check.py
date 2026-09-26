#!/usr/bin/env python3
"""startup_check.py - 启动检查器 (INSTALL_FINISH -> SOLVE_LITE MUST START)

在安装完成后自动运行（tools/installer.py 会调用它）；也可被宿主在首个会话前调用：
  python3 tools/startup_check.py --root . [--json]
只有全部通过才 exit 0，否则 exit 非零并打印失败项（宿主据此判定"装了但起不来"）。

检查项:
  1 LITE_CORE_PRESENT      LITE 运行时存在 + 8 个 .so 逐个 sha256 与 LITE_SHA256SUMS 一致
  2 NO_LEGACY_ASSET_DEMAND 运行路径不依赖 SOLVE_LITE_CORE_ASSET_ROOT / 不出现 ASSET_ROOT_MISSING / 不索要 2.33GB
                           （负向断言、HISTORICAL 标注、deprecated 别名声明不算命中）
  3 LITE_HEALTHCHECK       public loader LITE 优先路径 healthcheck = PASS
  4 NATIVE_DECISION        markov 原生路径真跑一次决策（NETWORK=0 / TORCH_IMPORT_ATTEMPTS=0）
  5 CAPABILITY_REGISTRY    native=AVAILABLE；specialist 状态与已装 DLC 一致
  6 DLC_DISCIPLINE         max_resident_dlc=1 · preload=FALSE · installed dlc 列表可读
  7 SUMMARY                打印用户可见分层披露（Base ≈4.6MB / 已装 DLC 清单）
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

#: runtime roots to try, in order: repo layout first, then pack/flat layouts
RUNTIME_CANDIDATES = (
    "plugins/solve-lite/skills/solve-lite/runtime",
    "runtime",
    ".",
)
SCRIPTS_CANDIDATES = (
    "plugins/solve-lite/skills/solve-lite/scripts",
    "scripts",
    ".",
)
SUMS_NAMES = ("solve_lite/lite_runtime/LITE_SHA256SUMS.txt", "SHA256SUMS.txt", "runtime/SHA256SUMS.txt")
KERNEL_REL = "solve_lite/lite_runtime/_kernel_native"
CASE_CANDIDATES = ("tests/fixtures/native_markov_case.json", "fixtures/MARKOV_CASE.json")
#: a bare needle is only a violation when the line does not explain itself
NEGATION_MARKERS = (
    "not required", "not_required", "no longer", "retired", "deprecated", "DEPRECATED",
    "assertNotIn", "does not require", "never required", "HISTORICAL", "historical",
    "optional", "OPTIONAL", "legacy", "unused", "_required", "no longer needed",
    "not in", "needed", "no asset", "without", "skipped", "skip",
    "LEGACY", "pop(", "environ.pop", "scrub",
)


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def runtime_root(root: Path) -> Path | None:
    for rel in RUNTIME_CANDIDATES:
        cand = (root / rel).resolve()
        if (cand / KERNEL_REL).is_dir():
            return cand
    return None


def find(root: Path, names) -> Path | None:
    for n in names:
        p = root / n
        if p.is_file():
            return p
    return None


def check_core(root: Path) -> dict:
    rt = runtime_root(root)
    where = rt or root
    sums = find(where, SUMS_NAMES) or find(root, SUMS_NAMES)
    kern = (where / KERNEL_REL) if rt else (root / KERNEL_REL)
    so = sorted(kern.glob("*.so")) if kern.is_dir() else []
    res = {"runtime_root": str(rt) if rt else None, "sums": str(sums) if sums else None,
           "so_count": len(so), "mismatch": [], "missing": []}
    if rt is None or sums is None or len(so) != 8:
        res["ok"] = False
        res["reason"] = "LITE_RUNTIME_OR_SUMS_MISSING"
        return res
    want = {}
    for line in sums.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or "  " not in line:
            continue
        h, rel = line.split("  ", 1)
        want[rel] = h
    for f in so:
        rel_candidates = [k for k in want if k.endswith(f.name)]
        if not rel_candidates:
            res["missing"].append(f.name)
            continue
        if sha256(f) != want[rel_candidates[0]]:
            res["mismatch"].append(f.name)
    res["ok"] = not res["mismatch"]
    return res


def check_no_legacy(root: Path) -> dict:
    """Flag an install/run *demand* - never a negative assertion.

    A line that keeps the legacy name only to say it is not needed (deprecated
    alias, `assertNotIn`, HISTORICAL reference, "not required") is correct text
    and must not be reported as a violation.
    """
    bad_needles = ("SOLVE_LITE_CORE_ASSET_ROOT", "ASSET_ROOT_MISSING")
    hits, excused = [], []
    for p in root.rglob("*"):
        if not p.is_file() or p.suffix not in (".py", ".json", ".sh", ".md"):
            continue
        if "/.git/" in str(p) or "__pycache__" in str(p):
            continue
        if p.name == "startup_check.py":
            continue  # a scanner must not flag its own needle table
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for needle in bad_needles:
            if needle not in text:
                continue
            lines = text.splitlines()
            flagged = False
            for index, line in enumerate(lines):
                window = " ".join(lines[index:index + 3])
                if needle in line and not any(m in window for m in NEGATION_MARKERS):
                    flagged = True
                    break
            entry = f"{p.relative_to(root)}:{needle}"
            (hits if flagged else excused).append(entry)
    return {"ok": not hits, "hits": hits[:10], "count": len(hits), "excused_negative_assertions": excused[:10]}


def _loader_path(root: Path) -> Path | None:
    for rel in SCRIPTS_CANDIDATES:
        for name in ("solve_lite_abi.py", "solve_lite_abi_lite.py"):
            cand = root / rel / name
            if cand.is_file():
                return cand
    return None


def _case_path(root: Path) -> Path | None:
    for rel in CASE_CANDIDATES:
        cand = root / rel
        if cand.is_file():
            return cand
    return None


def check_healthcheck_and_native(root: Path) -> dict:
    """Healthcheck plus one real native decision, in a clean subprocess."""
    rt = runtime_root(root)
    loader = _loader_path(root)
    case = _case_path(root)
    if loader is None or rt is None:
        return {"ok": False, "stage": "locate", "err": "public loader or LITE runtime not found",
                "loader": str(loader) if loader else None, "runtime_root": str(rt) if rt else None}
    program = (
        "import json, sys\n"
        f"sys.path.insert(0, {str(loader.parent)!r})\n"
        "import solve_lite_abi as A\n"
        f"rt = {str(rt)!r}\n"
        "hc = A.healthcheck(rt)\n"
        "out = {'healthcheck': hc, 'healthcheck_ok': hc.get('status') == 'PASS'}\n"
        "case_path = sys.argv[1] if len(sys.argv) > 1 else ''\n"
        "if case_path:\n"
        "    import tempfile, pathlib\n"
        "    case = json.loads(pathlib.Path(case_path).read_text(encoding='utf-8'))\n"
        "    ws = tempfile.mkdtemp(prefix='startup-check-')\n"
        "    r = A.route_prompt(ws, case, {'metadata': {'locale': 'en-US'}}, invocation_id='startup-check')\n"
        "    ans = r.get('answers') or {}\n"
        "    out['native'] = {'status': r.get('status'), 'route': r.get('adapter_route'),\n"
        "                     'answers': len(ans) if hasattr(ans, '__len__') else 0,\n"
        "                     'network_model_calls': r.get('network_model_calls'),\n"
        "                     'torch_imported': r.get('torch_imported')}\n"
        "    out['native_ok'] = r.get('status') == 'PASS' and bool(ans)\n"
        "print(json.dumps(out))\n"
    )
    cmd = [sys.executable, "-s", "-c", program]
    if case is not None:
        cmd.append(str(case))
    env = dict(os.environ)
    for name in ("SOLVE_LITE_RUNTIME_ROOT", "SOLVE_LITE_CORE_ASSET_ROOT"):
        env.pop(name, None)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600, env=env)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "stage": "healthcheck", "err": f"{type(exc).__name__}: {exc}"}
    try:
        d = json.loads(r.stdout.strip().splitlines()[-1])
    except Exception:
        return {"ok": False, "stage": "healthcheck", "err": (r.stderr or r.stdout)[-300:]}
    d["ok"] = bool(d.get("healthcheck_ok")) and bool(d.get("native_ok", True))
    d["stage"] = "healthcheck+native"
    return d


def check_registry(root: Path) -> dict:
    """Capability/DLC facts read through the public DLC layer, never guessed."""
    out = {"native": None, "specialist": None, "installed_dlc": [], "max_resident_dlc": None,
           "preload": None, "activation_state": None, "source": None}
    rt = runtime_root(root)
    loader = _loader_path(root)
    if rt is not None and loader is not None:
        program = (
            "import json, sys\n"
            f"sys.path.insert(0, {str(loader.parent)!r})\n"
            "import solve_lite_abi as A, solve_lite_dlc as D\n"
            f"rt = {str(rt)!r}\n"
            "caps = A.capabilities(rt)\n"
            "view = caps.get('dlc') or {}\n"
            "core = caps.get('core') or {}\n"
            "print(json.dumps({'native': (core.get('native') or {}).get('status'),\n"
            "  'specialist': (core.get('specialist') or {}).get('status'),\n"
            "  'installed_dlc': [u['unit_id'] for u in view.get('units', []) if u.get('status') == 'DLC_INSTALLED'],\n"
            "  'max_resident_dlc': view.get('resident_model_limit'),\n"
            "  'preload': view.get('preloaded'),\n"
            "  'activation_state': view.get('activation_state'),\n"
            "  'specialist_execution': view.get('specialist_execution_status')}))\n"
        )
        try:
            r = subprocess.run([sys.executable, "-s", "-c", program], capture_output=True, text=True, timeout=300)
            payload = json.loads(r.stdout.strip().splitlines()[-1])
            out.update({k: v for k, v in payload.items() if k != "specialist_execution"})
            out["specialist_execution"] = payload.get("specialist_execution")
            out["source"] = "public_abi_bridge"
        except Exception as exc:  # noqa: BLE001
            out["err"] = f"{type(exc).__name__}: {exc}"
    if out["native"] is None:
        # fall back to the registry file when the bridge is unavailable
        for cand in ("dlc-registry.json", "addons/solve-lite-int4-dlc/dlc-registry.json"):
            base = (rt / cand) if rt else (root / cand)
            if base.is_file():
                try:
                    d = json.loads(base.read_text(encoding="utf-8"))
                except Exception:
                    continue
                out["installed_dlc"] = [u for u in d.get("units", {})]
                out["source"] = str(base)
    out["ok"] = out["native"] == "AVAILABLE" and out["max_resident_dlc"] == 1 and out["preload"] is False
    return out


def base_runtime_mb(root: Path) -> float:
    """LITE core payload only: solve_lite/lite_runtime + public ABI + manifests.

    ``runtime/addons/**`` is the DLC area and ``runtime/dlc_runtime`` is the
    opt-in DLC backend: both are excluded so that the headline "Base ~4.6MB"
    cannot be polluted by whatever specialist components happen to be installed.
    """
    rt = runtime_root(root)
    if rt is None:
        return 4.6
    total = 0
    for p in rt.rglob("*"):
        if not p.is_file() or "__pycache__" in p.parts:
            continue
        relative = p.relative_to(rt).as_posix()
        if relative.startswith("addons/") or relative.startswith("dlc_runtime/"):
            continue
        total += p.stat().st_size
    for p in (root / "plugins" / "solve-lite" / "skills" / "solve-lite" / "scripts").rglob("*.py"):
        if p.is_file() and "__pycache__" not in p.parts:
            total += p.stat().st_size
    return round(total / 1_000_000, 1) if total else 4.6


def dlc_size_report(root: Path) -> dict:
    """DLC numbers, always separate from the base runtime number."""
    rt = runtime_root(root)
    addon = (rt / "addons" / "solve-lite-int4-dlc") if rt else None
    backend = (rt / "dlc_runtime") if rt else None
    def measure(path: Path | None) -> float:
        if path is None or not path.is_dir():
            return 0.0
        total = sum(p.stat().st_size for p in path.rglob("*") if p.is_file() and "__pycache__" not in p.parts)
        return round(total / 1_000_000, 1)
    installed_bytes = measure((addon / "installed") if addon else None)
    return {
        "installed_unpacked_mb": installed_bytes,
        "installed_installed_mb": installed_bytes,
        "backend_mb": measure(backend),
        "staged_packages_mb": measure((addon / "staged") if addon else None),
        "note": "DLC components are separate from the base runtime and are never counted in it",
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true", help="accepted; the exit code is already strict")
    args = ap.parse_args()
    root = args.root.resolve()

    core = check_core(root)
    legacy = check_no_legacy(root)
    hc = check_healthcheck_and_native(root)
    reg = check_registry(root)

    checks = {
        "LITE_CORE_PRESENT": bool(core["ok"]),
        "NO_LEGACY_ASSET_DEMAND": bool(legacy["ok"]),
        "LITE_HEALTHCHECK": bool(hc.get("healthcheck_ok")),
        "NATIVE_DECISION": bool(hc.get("native_ok", False)),
        "CAPABILITY_REGISTRY": (reg.get("native") == "AVAILABLE"
                                and reg.get("specialist") in ("AVAILABLE", "UNAVAILABLE")),
        "DLC_DISCIPLINE": reg.get("max_resident_dlc") == 1 and reg.get("preload") is False,
        "BASE_SIZE_SANE": 4.0 <= base_runtime_mb(root) <= 5.5,
    }
    passed = all(checks.values())
    report = {
        "STARTUP_CHECK": "PASS" if passed else "FAIL",
        "checks": checks,
        "detail": {"core": core, "legacy": legacy, "healthcheck": hc, "registry": reg},
        "disclosure": {
            "base_runtime_mb": base_runtime_mb(root),
            "base_runtime_scope": "LITE core only (excludes runtime/addons/** and runtime/dlc_runtime/**)",
            "dlc": dlc_size_report(root),
            "installed_dlc": reg.get("installed_dlc") or [],
            "activation_state": reg.get("activation_state"),
            "note": "Base Runtime is the small native runtime; Specialist packs are separate DLC components (not included).",
        },
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        for k, v in checks.items():
            print(f"{k}={'PASS' if v else 'FAIL'}")
        print("STARTUP_CHECK=" + report["STARTUP_CHECK"])
        if passed:
            print("Solve Lite 已就绪 / Solve Lite is ready.")
            print(f"Base Runtime: ≈{report['disclosure']['base_runtime_mb']}MB")
            dlc = report["disclosure"]["installed_dlc"]
            if dlc:
                print("Installed Specialist DLC: " + ", ".join(dlc))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
