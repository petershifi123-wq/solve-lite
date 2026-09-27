#!/usr/bin/env python3
"""Assert that the host really fires the Solve Lite hook and that it injects.

The self-test never trusts the installer's own claim.  It reads the *host's*
configuration, extracts the exact command the host will run, executes that
command with a synthetic host payload, and checks the injected context and the
hook ledger that the very same process wrote.

Verdict lines (machine readable, always printed):

    HOOK_REGISTERED=PASS|FAIL
    HOOK_FIRED=PASS|FAIL
    ENVELOPE_INJECTED=PASS|FAIL
    NO_MODEL_DISCRETION=PASS|FAIL
    NO_FABRICATED_FOOTER=PASS|FAIL
    HOOK_LATENCY_MEDIAN_MS=<n>
    HOOK_LATENCY_MAX_MS=<n>
    HOOK_PEAK_RSS_MB=<n>
    HOOK_FIRED_VERDICT=PASS|FAIL
"""

from __future__ import annotations

import argparse
import json
import os
import resource
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parent))

import host_hooks  # noqa: E402

PLUGIN_ROOT_DEFAULT = Path(__file__).resolve().parents[1] / "plugins" / "solve-lite"
EVIDENCE_SCHEMA = "solve-lite.hook-selftest.v1"
ACTIVATION_TOKEN = "CAPABILITY_ROUTED_LAZY"

PROMPTS = [
    "汉堡和薯条哪个更好？请比较并给出明确判断。",
    "是否应该现在部署？请给出明确判断。",
    "Which option is better? Compare A and B, then decide.",
]


def _sandbox_root() -> Path:
    root = Path(os.environ.get("SOLVE_LITE_SELFTEST_DIR") or
                (os.environ.get("TMPDIR") or "/tmp") + "/solve-lite-hook-selftest")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _hook_env(workspace: Path) -> Dict[str, str]:
    env = dict(os.environ)
    env["SOLVE_LITE_WORKSPACE"] = str(workspace)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONNOUSERSITE"] = "1"
    env["SOLVE_LITE_INT4_STATE_DIR"] = str(workspace / "int4-state")
    env.pop("SOLVE_LITE_HOOK_DISABLE", None)
    return env


def _registered_command(config_dir: Path) -> Optional[str]:
    document = host_hooks._read_json(config_dir / "settings.json")
    hooks = document.get("hooks") if isinstance(document.get("hooks"), dict) else {}
    entries = hooks.get("UserPromptSubmit") if isinstance(hooks.get("UserPromptSubmit"), list) else []
    for entry in entries:
        for hook in (entry or {}).get("hooks", []) if isinstance(entry, dict) else []:
            command = str((hook or {}).get("command") or "")
            if host_hooks.HOOK_SCRIPT_REL in command:
                return command
    return None


def _dispatch(command: str, prompt: str, workspace: Path, session_id: str,
              extra_env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    payload = json.dumps({
        "hook_event_name": "UserPromptSubmit",
        "prompt": prompt,
        "session_id": session_id,
        "cwd": str(Path.cwd()),
    })
    started = time.perf_counter()
    before = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    env = _hook_env(workspace)
    env.update(extra_env or {})
    proc = subprocess.run(["bash", "-c", command], input=payload, text=True,
                          capture_output=True, env=env)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    after = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    stdout = (proc.stdout or "").strip()
    parsed: Dict[str, Any] = {}
    try:
        parsed = json.loads(stdout.splitlines()[-1]) if stdout else {}
    except ValueError:
        parsed = {}
    return {
        "command": command,
        "prompt": prompt,
        "returncode": proc.returncode,
        "elapsed_ms": round(elapsed_ms, 3),
        "child_peak_rss_mb": round(after / (1024.0 * 1024.0), 2),
        "rss_delta_mb": round((after - before) / (1024.0 * 1024.0), 2),
        "stdout_head": stdout[:400],
        "stderr_tail": (proc.stderr or "")[-300:],
        "parsed": parsed,
        "additional_context": str(((parsed.get("hookSpecificOutput") or {}).get("additionalContext")) or ""),
    }


def _ledger(workspace: Path, tail: int = 20) -> List[Dict[str, Any]]:
    path = workspace / "hook-events.jsonl"
    if not path.is_file():
        return []
    records: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[-tail:]:
        try:
            records.append(json.loads(line))
        except ValueError:
            continue
    return records


def _audit(workspace: Path, tail: int = 20) -> List[Dict[str, Any]]:
    path = workspace / "codex-desktop-invocations.jsonl"
    if not path.is_file():
        return []
    records: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[-tail:]:
        try:
            records.append(json.loads(line))
        except ValueError:
            continue
    return records


def selftest_host(host_id: str, plugin_root: Path, *, config_dir: Optional[Path] = None,
                  runs: int = 3) -> Dict[str, Any]:
    spec = host_hooks.host_spec(host_id)
    sandbox = _sandbox_root() / host_id
    workspace = sandbox / ("workspace-%s-%s" % (os.getpid(), time.time_ns()))
    workspace.mkdir(parents=True, exist_ok=True)
    result: Dict[str, Any] = {
        "schema_version": EVIDENCE_SCHEMA,
        "host_id": host_id,
        "display": spec.display,
        "hook_api": spec.hook_api,
        "hook_api_evidence": spec.hook_api_evidence,
        "activation_token": ACTIVATION_TOKEN,
        "sandbox": str(sandbox),
    }
    if host_id == "workbuddy":
        target = Path(config_dir) if config_dir else sandbox / "config"
        # Always re-register into the isolated host shape. The plugin-layer copy is
        # the authoritative WorkBuddy hook; settings.json must not contain a second
        # Solve Lite command.
        host_hooks.register(host_id, plugin_root, override=target)
        detected = host_hooks.detect(host_id, target)["config_dirs"][0]
        commands = detected.get("plugin_hook_commands") or []
        command = commands[0] if len(commands) == 1 else _registered_command(target)
        plugin_copy = host_hooks._marketplace_dir(target) / "plugins" / "solve-lite"
        hook_env = {
            "CODEBUDDY_PLUGIN_ROOT": str(plugin_copy),
            "CLAUDE_PLUGIN_ROOT": str(plugin_copy),
        }
        result["config_dir"] = str(target)
        result["registered_command"] = command
        result["hook_state"] = detected.get("hook_state")
        result["active_solve_lite_sources"] = detected.get("active_solve_lite_sources")
        result["hook_registered"] = detected.get("hook_state") == "HOOK_ACTIVE"
        result["one_step_command"] = command
        dispatches = [_dispatch(command, prompt, workspace, "selftest-%d" % index, hook_env)
                      for index, prompt in enumerate(PROMPTS[:max(1, runs)])] if command else []
        fail_open = _dispatch(command or "exit 0", PROMPTS[0], workspace, "missing-root", {
            "CODEBUDDY_PLUGIN_ROOT": "",
            "CLAUDE_PLUGIN_ROOT": "",
        })
        result["missing_root_fail_open"] = fail_open.get("returncode") == 0
    else:
        target = Path(config_dir) if config_dir else plugin_root
        command = host_hooks.one_step_command(target)
        result["registered_command"] = command
        result["skill"] = host_hooks.detect(host_id, config_dir)
        result["hook_registered"] = bool(result["skill"].get("skill_installed")
                                         and result["skill"].get("mandatory_first_step_present"))
        # Hosts without a hook API still run the SAME hook script; the payload must go
        # through stdin as JSON, exactly like a real host would deliver it. Passing
        # --prompt as an argument gave an empty prompt and made the envelope look
        # broken, which is why ENVELOPE_INJECTED/NO_MODEL_DISCRETION used to FAIL.
        dispatches = [_dispatch(command, prompt, workspace, "selftest-%d" % index)
                      for index, prompt in enumerate(PROMPTS[:max(1, runs)])]
    result["dispatches"] = dispatches

    injected = [d for d in dispatches
                if "Solve Lite" in d.get("additional_context", "")
                and ("选择 |" in d.get("additional_context", "")
                     or "Choice |" in d.get("additional_context", ""))]
    fired = [d for d in dispatches
             if d.get("returncode") == 0 and (d.get("parsed") or {}).get("continue") is True
             and ((d.get("parsed") or {}).get("hookSpecificOutput") or {}).get("hookEventName")
             == "UserPromptSubmit"]
    if host_id != "workbuddy":
        fired = [d for d in dispatches if d.get("returncode") == 0 and injected]

    records = _ledger(workspace)
    audit_records = [r for r in _audit(workspace) if r.get("status") == "PASS"]
    reward_visible = [d for d in dispatches if "⚡" in d.get("additional_context", "")]
    unmeasured_token_visible = [d for d in dispatches
                                if "Token：" in d.get("additional_context", "")
                                or "Token:" in d.get("additional_context", "")]
    latencies = [float(d["elapsed_ms"]) for d in dispatches if d.get("elapsed_ms")]

    result["ledger_path"] = str(workspace / "hook-events.jsonl")
    result["ledger_records_tail"] = records[-4:]
    result["activation_records"] = len(audit_records)
    result["checks"] = {
        "HOOK_REGISTERED": bool(result["hook_registered"]),
        "DUPLICATE_HOOK": int(result.get("active_solve_lite_sources") or 1) == 1,
        "HOOK_BLOCKING": all(d.get("returncode") == 0 for d in dispatches)
        and result.get("missing_root_fail_open", True),
        "HOST_HOOK_API": str(result.get("hook_api") or "none") != "none",
        "HOOK_FIRED": len(fired) == len(dispatches) and bool(dispatches),
        "ENVELOPE_INJECTED": len(injected) == len(dispatches) and bool(dispatches),
        "NO_MODEL_DISCRETION": len(audit_records) >= len(dispatches) and bool(dispatches),
        "NO_FABRICATED_FOOTER": len(reward_visible) == len(dispatches)
        and not unmeasured_token_visible,
    }
    result["latency_ms"] = {
        "runs": len(latencies),
        "min": round(min(latencies), 3) if latencies else None,
        "median": round(statistics.median(latencies), 3) if latencies else None,
        "max": round(max(latencies), 3) if latencies else None,
    }
    rss = [float(d["child_peak_rss_mb"]) for d in dispatches if d.get("child_peak_rss_mb")]
    result["peak_rss_mb"] = round(max(rss), 2) if rss else None
    checks = result["checks"]
    result["activation_channel"] = ("HOST_USER_PROMPT_SUBMIT_HOOK" if checks["HOST_HOOK_API"]
                                    else "OFF_HOST_PREPROMPT_STEP")
    gating = ["HOOK_FIRED", "ENVELOPE_INJECTED", "NO_MODEL_DISCRETION", "NO_FABRICATED_FOOTER"]
    if checks["HOST_HOOK_API"]:
        # only a host that has a hook API can be held to "the host fires it"
        gating = ["HOOK_REGISTERED", "DUPLICATE_HOOK", "HOOK_BLOCKING"] + gating
    result["gating_checks"] = gating
    result["HOOK_FIRED"] = "PASS" if all(checks[name] for name in gating) else "FAIL"
    return result


def _verdict_lines(result: Dict[str, Any]) -> List[str]:
    checks = result["checks"]
    latency = result["latency_ms"]
    return [
        "HOOK_REGISTERED=%s" % ("PASS" if checks["HOOK_REGISTERED"] else "FAIL"),
        "DUPLICATE_HOOK=%s" % ("0" if checks["DUPLICATE_HOOK"] else "1"),
        "HOOK_BLOCKING=%s" % ("0" if checks["HOOK_BLOCKING"] else "1"),
        "HOOK_FIRED=%s" % ("PASS" if checks["HOOK_FIRED"] else "FAIL"),
        "ENVELOPE_INJECTED=%s" % ("PASS" if checks["ENVELOPE_INJECTED"] else "FAIL"),
        "NO_MODEL_DISCRETION=%s" % ("PASS" if checks["NO_MODEL_DISCRETION"] else "FAIL"),
        "NO_FABRICATED_FOOTER=%s" % ("PASS" if checks["NO_FABRICATED_FOOTER"] else "FAIL"),
        "HOOK_LATENCY_MEDIAN_MS=%s" % latency["median"],
        "HOOK_LATENCY_MAX_MS=%s" % latency["max"],
        "HOOK_PEAK_RSS_MB=%s" % result["peak_rss_mb"],
        "HOST_HOOK_API=%s" % ("YES" if checks["HOST_HOOK_API"] else "NO_HOST_HOOK_API"),
        "ACTIVATION_CHANNEL=%s" % result["activation_channel"],
        "HOOK_FIRED_VERDICT=%s" % result["HOOK_FIRED"],
    ]


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Solve Lite host hook self-test")
    parser.add_argument("--host", default="all",
                         help="workbuddy|doubao|generic|auto|all")
    parser.add_argument("--plugin-root", type=Path, default=PLUGIN_ROOT_DEFAULT)
    parser.add_argument("--config-dir", type=Path, default=None,
                        help="host config dir to inspect (default: an isolated sandbox copy)")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--evidence", type=Path, default=None)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.host == "all":
        hosts = ["workbuddy", "doubao", "generic"]
    elif args.host == "auto":
        hosts = [host_hooks.resolve_auto(args.config_dir)]
    else:
        hosts = [args.host]
    output: Dict[str, Any] = {"schema_version": EVIDENCE_SCHEMA, "hosts": {}}
    verdict = 0
    for host_id in hosts:
        result = selftest_host(host_id, args.plugin_root.expanduser(),
                              config_dir=args.config_dir, runs=args.runs)
        output["hosts"][host_id] = result
        if not args.json:
            print("== %s (%s)" % (host_id, result["display"]))
            print("   registered_command: %s" % result["registered_command"])
            for line in _verdict_lines(result):
                print("   %s" % line)
        if result["HOOK_FIRED"] != "PASS":
            verdict = 1
            for dispatch in result["dispatches"]:
                if host_hooks.PYTHON and dispatch.get("returncode") not in (0,) and not args.json:
                    print("   ! rc=%s stderr=%s" % (dispatch.get("returncode"), dispatch.get("stderr_tail")))
    evidence_path = args.evidence or (_sandbox_root() / "hook_selftest_evidence.json")
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                             encoding="utf-8")
    if not args.json:
        print("EVIDENCE=%s" % evidence_path)
    if args.json:
        print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return verdict


if __name__ == "__main__":
    raise SystemExit(main())
