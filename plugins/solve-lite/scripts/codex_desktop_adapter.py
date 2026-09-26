#!/usr/bin/env python3
"""Solve Lite -> Codex Desktop adapter: install / doctor / uninstall.

Talks only to official Codex interfaces:

* ``codex plugin add|remove|list`` / ``codex plugin marketplace`` for lifecycle.
* app-server JSON-RPC over stdio for ``hooks/list``, ``config/read``,
  ``plugin/list`` and ``config/batchWrite`` (the same RPC the Desktop app uses).

Hard rule: this tool never writes hook trust.  Codex persists hook trust in
``hooks.state.<key>.trusted_hash`` and the approval itself stays a visible user
action in the Codex Desktop Hooks panel / Codex TUI trust prompt.  ``doctor``
reports the exact key + hash the human has to approve instead.

Usage::

    python3 scripts/codex_desktop_adapter.py doctor   [--cwd DIR] [--json] [--no-dispatch-probe]
                                                      [--ledger-baseline FILE]
    python3 scripts/codex_desktop_adapter.py snapshot [--out FILE] [--json]
    python3 scripts/codex_desktop_adapter.py rollout-check --session SESSION_ID
    python3 scripts/codex_desktop_adapter.py install  [--dry-run] [--json] [--receipt FILE]
    python3 scripts/codex_desktop_adapter.py uninstall [--yes] [--json]

Exit codes: 0 = PASS, 2 = READY_FOR_PETER_HOOK_APPROVAL / GATE_AWAITING_ORDINARY_SESSION, 1 = FAIL.

The ordinary-session gate is machine verifiable because it compares the production
reward ledger against a ``snapshot`` baseline and reads the session rollout:
exactly one new invocation, session ``originator`` = the Desktop app, and the
*visible* assistant message (never the hook's injected developer context) must
carry the Chinese percentage labels, the token status, the ``+5`` reward delta and
the running total, with a single latency line.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

PLUGIN_ID = "solve-lite@personal"
PLUGIN_NAME = "solve-lite"
MARKETPLACE = "personal"
HOOK_SOURCE = "hooks/hooks.json"
ROOT_MANIFEST_SOURCE = "plugin.json"
HOOK_EVENT = "user_prompt_submit"
PROBE_PROMPT = "热狗是否属于三明治？"
DEFAULT_CLI_CANDIDATES = (
    "/Applications/ChatGPT.app/Contents/Resources/codex",
    "/opt/homebrew/bin/codex",
    "/usr/local/bin/codex",
)


def plugin_root() -> Path:
    return Path(__file__).resolve().parents[1]


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or (Path.home() / ".codex")).expanduser()


def marketplace_path() -> Path:
    return Path.home() / ".agents" / "plugins" / "marketplace.json"


def codex_cli() -> str:
    for key in ("SOLVE_LITE_CODEX_CLI", "CODEX_CLI_PATH"):
        value = os.environ.get(key)
        if value and Path(value).is_file():
            return value
    for candidate in DEFAULT_CLI_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    found = shutil.which("codex")
    if not found:
        raise SystemExit("FAIL codex_cli=NOT_FOUND")
    return found


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_manifest(root: Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(root)
        if any(part in {"__pycache__", ".DS_Store", ".solve-lite"} for part in rel.parts):
            continue
        entries[str(rel)] = sha256_file(path)
    return entries


def manifest_digest(entries: dict[str, str]) -> str:
    payload = json.dumps(entries, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def cached_plugin_dir() -> Path | None:
    version_path = plugin_root() / ".codex-plugin" / "plugin.json"
    try:
        version = json.loads(version_path.read_text(encoding="utf-8"))["version"]
    except Exception:
        return None
    path = codex_home() / "plugins" / "cache" / MARKETPLACE / PLUGIN_NAME / str(version)
    return path if path.is_dir() else None


def run(cmd: list[str], timeout: float = 60.0, env: dict[str, str] | None = None):
    merged = dict(os.environ)
    if env:
        merged.update(env)
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
            env=merged,
            stdin=subprocess.DEVNULL,
        )
        return proc.returncode, proc.stdout
    except subprocess.TimeoutExpired as exc:
        return 124, (exc.output or "") + f"\nTIMEOUT after {timeout}s"

class AppServer:
    """Minimal JSON-RPC stdio client for the bundled Codex app server."""

    def __init__(self, cli: str, timeout: float = 60.0) -> None:
        self.timeout = timeout
        self._lines: list[str] = []
        self._lock = threading.Lock()
        self._proc = subprocess.Popen(
            [cli, "app-server", "--listen", "stdio://"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        threading.Thread(target=self._pump, args=(self._proc.stdout,), daemon=True).start()

    def _pump(self, stream) -> None:
        for line in stream:
            with self._lock:
                self._lines.append(line)

    def _drain(self, request_id: int) -> dict[str, Any] | None:
        with self._lock:
            for line in self._lines:
                try:
                    message = json.loads(line)
                except Exception:
                    continue
                if message.get("id") == request_id:
                    return message
        return None

    def call(self, method: str, params: dict[str, Any] | None = None, seq: int = 1) -> dict[str, Any]:
        request = {"jsonrpc": "2.0", "id": seq, "method": method, "params": params or {}}
        if self._proc.stdin is None:
            raise RuntimeError("app server stdin closed")
        self._proc.stdin.write(json.dumps(request) + "\n")
        self._proc.stdin.flush()
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            message = self._drain(seq)
            if message is not None:
                if "error" in message:
                    raise RuntimeError(f"{method} failed: {message['error']}")
                return message.get("result") or {}
            time.sleep(0.05)
        raise RuntimeError(f"{method} timed out after {self.timeout}s")

    def initialize(self) -> None:
        self.call(
            "initialize",
            {"clientInfo": {"name": "solve-lite-adapter", "version": "1.0.0"}},
            seq=0,
        )

    def close(self) -> None:
        try:
            self._proc.terminate()
            self._proc.wait(timeout=10)
        except Exception:
            self._proc.kill()


def _hook_entries(cli: str, cwd: Path) -> tuple[list[dict[str, Any]], list[str]]:
    server = AppServer(cli)
    try:
        server.initialize()
        listing = server.call("hooks/list", {"cwds": [str(cwd)]}, seq=1)
    finally:
        server.close()
    entries: list[dict[str, Any]] = []
    warnings: list[str] = []
    for bucket in listing.get("data", []):
        warnings.extend(bucket.get("warnings") or [])
        for error in bucket.get("errors") or []:
            warnings.append(f"{error.get('path')}: {error.get('message')}")
        for hook in bucket.get("hooks", []):
            if str(hook.get("pluginId") or "") == PLUGIN_ID:
                entries.append(hook)
    return entries, warnings


def _config_read(cli: str) -> dict[str, Any]:
    server = AppServer(cli)
    try:
        server.initialize()
        result = server.call("config/read", {}, seq=1)
    finally:
        server.close()
    return result.get("config") or {}


def _plugin_state(cli: str) -> dict[str, Any]:
    server = AppServer(cli)
    try:
        server.initialize()
        result = server.call("plugin/list", {}, seq=1)
    finally:
        server.close()
    for marketplace in result.get("marketplaces", []):
        for plugin in marketplace.get("plugins", []):
            if plugin.get("id") == PLUGIN_ID:
                return plugin
    return {}

def default_workspace() -> Path:
    configured = os.environ.get("SOLVE_LITE_WORKSPACE")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / "Library" / "Application Support" / "OpenAI" / "Codex" / "solve-lite"


def check_package() -> dict[str, Any]:
    """Source-side package checks: manifest, hook command, runtime config, ABI."""
    root = plugin_root()
    out: dict[str, Any] = {"root": str(root)}
    manifest_path = root / ".codex-plugin" / "plugin.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {**out, "status": "FAIL", "detail": f"plugin.json unreadable: {exc}"}
    out["version"] = manifest.get("version")
    out["declared_hooks"] = manifest.get("hooks")
    # Measured ABI boundary (codex-cli 0.155.0-alpha.16.4, LAYOUT_MATRIX.json):
    # a root `plugin.json` switches the plugin to the Agent Plugins loader, which
    # exposes no hooks at all, so the load-bearing manifest stays `.codex-plugin/`.
    if (root / ROOT_MANIFEST_SOURCE).exists():
        return {**out, "status": "FAIL", "detail": f"{ROOT_MANIFEST_SOURCE} must not exist: it disables plugin hook loading"}
    if manifest.get("hooks") != f"./{HOOK_SOURCE}":
        return {**out, "status": "FAIL", "detail": f"manifest must declare hooks=./{HOOK_SOURCE}"}
    namespace = (manifest.get("extensions") or {}).get("com.openai") or {}
    out["namespace_hooks"] = namespace.get("hooks")
    if namespace.get("hooks") != f"./{HOOK_SOURCE}":
        return {**out, "status": "FAIL", "detail": f"extensions.com.openai.hooks must mirror ./{HOOK_SOURCE}"}
    hooks_files = sorted(
        str(path.relative_to(root)) for path in root.rglob("hooks.json") if path.is_file()
    )
    out["hooks_files"] = hooks_files
    if hooks_files != [HOOK_SOURCE]:
        return {**out, "status": "FAIL", "detail": f"expected exactly one hook manifest at {HOOK_SOURCE}, found {hooks_files}"}
    hooks_path = root / HOOK_SOURCE
    try:
        hooks = json.loads(hooks_path.read_text(encoding="utf-8"))["hooks"]
    except Exception as exc:
        return {**out, "status": "FAIL", "detail": f"{HOOK_SOURCE} unreadable: {exc}"}
    commands = [
        handler.get("command", "")
        for group in hooks.get("UserPromptSubmit", [])
        for handler in group.get("hooks", [])
        if handler.get("type") == "command"
    ]
    out["hook_commands"] = commands
    if len(commands) != 1 or "${PLUGIN_ROOT}" not in commands[0]:
        return {**out, "status": "FAIL", "detail": "expected exactly one UserPromptSubmit command using ${PLUGIN_ROOT}"}
    for other, events in hooks.items():
        if other != "UserPromptSubmit" and events:
            return {**out, "status": "FAIL", "detail": f"unexpected extra hook event: {other}"}
    entrypoint = root / "hooks" / "user_prompt_submit.py"
    if not entrypoint.is_file() or not os.access(entrypoint, os.R_OK):
        return {**out, "status": "FAIL", "detail": "hooks/user_prompt_submit.py missing or unreadable"}
    out["entrypoint"] = str(entrypoint)
    out["entrypoint_sha256"] = sha256_file(entrypoint)
    runtime_path = root / ".codex-runtime.json"
    runtime: dict[str, Any] = {}
    if runtime_path.is_file():
        try:
            loaded = json.loads(runtime_path.read_text(encoding="utf-8"))
        except Exception as exc:
            return {**out, "status": "FAIL", "detail": f".codex-runtime.json unreadable: {exc}"}
        if isinstance(loaded, dict):
            runtime = loaded
    configured = str(runtime.get("asset_root") or "").strip()
    asset_root = Path(configured).expanduser() if configured else None
    out["asset_root"] = str(asset_root) if asset_root else None
    out["asset_root_origin"] = "explicit_config" if asset_root else "bundled_runtime"
    if asset_root is not None and not asset_root.is_dir():
        return {**out, "status": "FAIL", "detail": f"asset_root configured but missing: {asset_root}"}
    scripts = root / "skills" / "solve-lite" / "scripts"
    code = (
        "import json,sys;sys.path.insert(0,%r);"
        "from solve_lite_abi import healthcheck;print(json.dumps(healthcheck(%r)))"
        % (str(scripts), str(asset_root) if asset_root else None)
    )
    rc, output = run(["/usr/bin/python3", "-c", code], timeout=120, env={"PYTHONDONTWRITEBYTECODE": "1"})
    out["abi_healthcheck_raw"] = output.strip().splitlines()[-1] if output.strip() else ""
    if rc != 0 or '"status": "PASS"' not in out["abi_healthcheck_raw"]:
        return {**out, "status": "FAIL", "detail": f"ABI healthcheck failed (rc={rc})"}
    return {**out, "status": "PASS"}


def check_identity() -> dict[str, Any]:
    """Source plugin directory vs the materialized plugin cache must be byte identical."""
    source = tree_manifest(plugin_root())
    cache_dir = cached_plugin_dir()
    if cache_dir is None:
        return {"status": "FAIL", "detail": "installed cache directory not found"}
    cache = tree_manifest(cache_dir)
    only_source = sorted(set(source) - set(cache))
    only_cache = sorted(set(cache) - set(source))
    mismatched = sorted(rel for rel in set(source) & set(cache) if source[rel] != cache[rel])
    ok = not only_source and not only_cache and not mismatched
    return {
        "status": "PASS" if ok else "FAIL",
        "cache_dir": str(cache_dir),
        "source_files": len(source),
        "cache_files": len(cache),
        "only_source": only_source,
        "only_cache": only_cache,
        "hash_mismatch": mismatched,
        "source_manifest_sha256": manifest_digest(source),
        "cache_manifest_sha256": manifest_digest(cache),
    }


def trusted_project(cwd: Path, config: dict[str, Any] | None = None) -> bool:
    projects = (config or {}).get("projects")
    if projects is None:
        projects = _config_read(codex_cli()).get("projects") or {}
    text = str(cwd)
    for path, value in (projects or {}).items():
        if (value or {}).get("trust_level") != "trusted":
            continue
        if text == str(path) or text.startswith(str(path).rstrip("/") + "/"):
            return True
    return False


def real_invocation_evidence(workspace: Path, baseline_path: Path | None = None) -> dict[str, Any]:
    ledger = ledger_path(workspace)
    if not ledger.is_file():
        return {"status": "NONE", "detail": f"no ledger at {ledger}"}
    records = ledger_records(workspace)
    passed = [record for record in records if record.get("status") == "PASS"]
    last = passed[-1] if passed else (records[-1] if records else {})
    modified = time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(ledger.stat().st_mtime))
    out: dict[str, Any] = {
        "status": "PASS" if passed else "FAIL",
        "path": str(ledger),
        "invocations": len(records),
        "last_appended_at": modified,
        "last_invocation_id": last.get("invocation_id"),
        "last_reward_summary": last.get("reward_summary"),
        "last_network_model_calls": last.get("network_model_calls"),
        "note": "count and last_appended_at must advance after the trust approval for a real-session PASS",
    }
    if baseline_path is None:
        out["baseline_verified"] = False
        out["detail"] = "legacy view: any PASS record counts; pass --ledger-baseline for an advance proof"
        return out
    try:
        known = baseline_ids(baseline_path)
    except Exception as exc:
        return {**out, "status": "FAIL", "detail": f"baseline unreadable: {exc}"}
    new = [record for record in records if str(record.get("invocation_id")) not in known]
    out.update(
        baseline=str(baseline_path),
        baseline_verified=True,
        new_since_baseline=len(new),
        new_invocation_ids=[record.get("invocation_id") for record in new],
    )
    if not new:
        out["status"] = "GATE"
        out["detail"] = "no production invocation appended since the baseline"
        return out
    out["status"] = "PASS" if any(record.get("status") == "PASS" for record in new) else "FAIL"
    out["detail"] = "production ledger advanced since the baseline"
    return out




DESKTOP_ORIGINATOR = "Codex Desktop"
LEDGER_BASELINE_SCHEMA = "solve-lite.codex-desktop-ledger-baseline.v1"


def ledger_path(workspace: Path) -> Path:
    return workspace / "codex-desktop-invocations.jsonl"


def ledger_records(workspace: Path) -> list[dict[str, Any]]:
    path = ledger_path(workspace)
    if not path.is_file():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except Exception:
            continue
    return records


def ledger_snapshot(workspace: Path) -> dict[str, Any]:
    """Baseline for the ordinary-session gate: the ledger must advance by exactly one."""
    path = ledger_path(workspace)
    records = ledger_records(workspace)
    return {
        "schema_version": LEDGER_BASELINE_SCHEMA,
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "ledger": str(path),
        "ledger_exists": path.is_file(),
        "ledger_sha256": sha256_file(path) if path.is_file() else None,
        "invocations": len(records),
        "invocation_ids": [record.get("invocation_id") for record in records],
    }


def baseline_ids(baseline_path: Path) -> list[str]:
    payload = json.loads(baseline_path.read_text(encoding="utf-8"))
    return [str(entry) for entry in (payload.get("invocation_ids") or []) if entry]


def session_id_of(record: dict[str, Any]) -> str | None:
    parts = str(record.get("invocation_id") or "").split(":")
    return parts[1] if len(parts) >= 3 and parts[0] == "codex" else None


def rollout_path(session_id: str, sessions_root: Path | None = None) -> Path | None:
    root = sessions_root or (codex_home() / "sessions")
    if not session_id or not root.is_dir():
        return None
    hits = [path for path in root.rglob(f"*{session_id}*.jsonl") if path.is_file()]
    return max(hits, key=lambda path: path.stat().st_mtime) if hits else None


def rollout_evidence(path: Path) -> dict[str, Any]:
    """Who started the session and what the user actually saw.

    Only ``response_item`` messages with ``role=assistant`` count as visible: the
    hook injects its contract as a ``developer`` message, which must never be
    mistaken for the user-visible answer.
    """
    meta: dict[str, Any] = {}
    assistant: list[str] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except Exception:
            continue
        payload = event.get("payload") or {}
        if event.get("type") == "session_meta":
            meta = payload
        elif (
            event.get("type") == "response_item"
            and payload.get("type") == "message"
            and payload.get("role") == "assistant"
        ):
            text = "".join(
                str(part.get("text") or "") for part in (payload.get("content") or []) if isinstance(part, dict)
            )
            if text.strip():
                assistant.append(text)
    return {
        "rollout": str(path),
        "originator": meta.get("originator"),
        "source": meta.get("source"),
        "cwd": meta.get("cwd"),
        "assistant_messages": len(assistant),
        "assistant_message": assistant[-1] if assistant else "",
    }


def visible_obligations(text: str) -> dict[str, Any]:
    """The visible contract lines, plus the single-latency / single-reward-line rule."""
    zero = re.search(r"Token：(?:0（无可压缩上下文）)|Token: 0 \(no compressible context\)", text)
    pack = re.search(
        r"Token：(?:输入 \d+ · 输出 \d+ · 压缩 -?\d+ · 凭据 evt_[0-9a-f]{4,})"
        r"|Token: (?:in \d+ · out \d+ · packed -?\d+ · receipt evt_[0-9a-f]{4,})",
        text,
    )
    return {
        "router_footer": "选择 |" in text,
        "percent_labels_chinese": bool(re.search(r"[\u4e00-\u9fff][^%\n]{0,24}?\d+(?:\.\d+)?%", text)),
        "percent_labels_english": bool(re.search(r"[A-Za-z]{3,}[^%\n]{0,15}?\d+(?:\.\d+)?%", text)),
        "token_status": bool(zero or pack),
        "token_status_measured": bool(zero or pack),
        "token_status_retired_literal": "本轮未触发压缩" in text or "compression not triggered this turn" in text,
        "reward_delta_plus5": bool(re.search(r"\+\s?5\s*(?:分|Score)", text)),
        "cumulative_reward": bool(re.search(r"累计\s*\d+", text)),
        "reward_lines": len(re.findall(r"\+\s?5\s*(?:分|Score)", text)),
        "latency_mentions": len(re.findall(r"本地推理", text)),
    }


def check_ordinary_session(
    workspace: Path, baseline_path: Path | None, sessions_root: Path | None = None
) -> dict[str, Any]:
    """Exactly one new invocation from a real Desktop session whose visible answer matches."""
    if baseline_path is None:
        return {
            "status": "GATE",
            "detail": "no baseline: run snapshot before the ordinary session, then doctor --ledger-baseline FILE",
        }
    try:
        known = baseline_ids(baseline_path)
    except Exception as exc:
        return {"status": "FAIL", "detail": f"baseline unreadable: {exc}", "baseline": str(baseline_path)}
    records = ledger_records(workspace)
    new = [record for record in records if str(record.get("invocation_id")) not in known]
    out: dict[str, Any] = {
        "baseline": str(baseline_path),
        "baseline_invocations": len(known),
        "ledger_invocations": len(records),
        "new_invocations": len(new),
    }
    if not new:
        return {
            **out,
            "status": "GATE",
            "detail": "reward ledger has not advanced since the baseline: waiting for the ordinary Desktop session",
        }
    if len(new) > 1:
        return {**out, "status": "FAIL", "detail": f"duplicate hook invocations: {len(new)} new ledger records"}
    record = new[0]
    out.update(
        invocation_id=record.get("invocation_id"),
        record_status=record.get("status"),
        network_model_calls=record.get("network_model_calls"),
        reward_summary=record.get("reward_summary"),
    )
    if record.get("status") != "PASS":
        return {**out, "status": "FAIL", "detail": f"invocation record status={record.get('status')}"}
    session_id = session_id_of(record)
    out["session_id"] = session_id
    path = rollout_path(session_id or "", sessions_root)
    if path is None:
        return {**out, "status": "FAIL", "detail": "no session rollout found for the recorded session id"}
    evidence = rollout_evidence(path)
    out.update(evidence)
    cwd = evidence.get("cwd")
    try:
        out["project_trusted"] = trusted_project(Path(str(cwd))) if cwd else None
    except Exception as exc:
        out["project_trusted"] = None
        out["project_trust_lookup_error"] = str(exc)
    originator = str(evidence.get("originator") or "")
    if "desktop" not in originator.lower():
        return {**out, "status": "FAIL", "detail": f"session originator={originator or 'unknown'} is not the Desktop app"}
    if not evidence.get("assistant_message"):
        return {**out, "status": "FAIL", "detail": "no visible assistant message in the session rollout"}
    obligations = visible_obligations(str(evidence["assistant_message"]))
    out["visible_obligations"] = obligations
    missing = [
        name
        for name in (
            "router_footer",
            "percent_labels_chinese",
            "token_status",
            "reward_delta_plus5",
            "cumulative_reward",
        )
        if not obligations[name]
    ]
    if obligations["percent_labels_english"]:
        missing.append("percent_labels_chinese_only")
    if obligations["token_status_retired_literal"]:
        missing.append("token_status_retired_static_literal")
    if obligations["latency_mentions"] != 1 or obligations["reward_lines"] != 1:
        missing.append("single_latency_and_reward_line")
    if missing:
        return {**out, "status": "FAIL", "detail": "visible contract incomplete: " + ", ".join(sorted(missing))}
    return {
        **out,
        "status": "PASS",
        "detail": f"ordinary Desktop session {session_id}: +1 invocation, visible contract complete",
    }


def _assistant_messages(log_path: Path) -> list[str]:
    messages: list[str] = []
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return messages
    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except Exception:
            continue
        item = event.get("item") or {}
        if event.get("type") == "item.completed" and item.get("type") == "agent_message":
            messages.append(str(item.get("text") or ""))
    return messages


def _config_batch_write(cli: str, edits: list[dict[str, Any]]) -> None:
    server = AppServer(cli)
    try:
        server.initialize()
        server.call(
            "config/batchWrite",
            {"edits": edits, "filePath": None, "expectedVersion": None, "reloadUserConfig": True},
            seq=1,
        )
    finally:
        server.close()


def drop_project_trust(cli: str, keys: list[str]) -> list[str]:
    """Undo the project-trust entries Codex auto-persists for short-lived probe dirs."""
    if not keys:
        return []
    _config_batch_write(
        cli,
        [
            {"keyPath": f'projects."{key}"', "mergeStrategy": "replace", "value": None}
            for key in keys
        ],
    )
    return keys


def dispatch_probe(cli: str, cwd: Path, timeout: float = 240.0) -> dict[str, Any]:
    """Prove the adapter contract through the host on a real ordinary turn.

    Runs one genuine model turn with hook trust bypassed (the Codex CLI flag for
    vetted automation) and an isolated ``SOLVE_LITE_WORKSPACE``, so neither the
    production reward ledger nor persisted hook trust is touched.  The turn runs
    in a throwaway project directory whose trust is granted only as a process
    local ``-c`` override, which keeps the probe free of the caller's workspace
    instructions.  All three visible obligations must appear: localized decision
    percentages, truthful token status and one ``+5`` reward footer.
    """
    workspace = Path(tempfile.mkdtemp(prefix="solve-lite-dispatch-"))
    project = workspace / "project"
    project.mkdir()
    ledger = workspace / "codex-desktop-invocations.jsonl"
    log = workspace / "probe.log"
    started = time.time()
    projects_before = set((_config_read(cli).get("projects") or {}).keys())
    with log.open("w", encoding="utf-8") as handle:
        proc = subprocess.Popen(
            [
                cli, "exec", "--dangerously-bypass-hook-trust", "--skip-git-repo-check",
                "-c", f'projects."{project}".trust_level="trusted"',
                "-C", str(project), "--json", PROBE_PROMPT,
            ],
            stdout=handle,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            cwd=str(project),
            env={**os.environ, "SOLVE_LITE_WORKSPACE": str(workspace)},
        )
        deadline = time.time() + timeout
        while time.time() < deadline:
            finished = False
            if log.is_file():
                text = log.read_text(encoding="utf-8", errors="replace")
                finished = '"type":"turn.completed"' in text or '"type":"turn.failed"' in text
            if ledger.is_file() and finished:
                break
            if proc.poll() is not None:
                break
            time.sleep(1)
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
    result: dict[str, Any] = {"cwd": str(cwd), "probe_project": str(project), "elapsed_seconds": round(time.time() - started, 1)}
    projects_after = set((_config_read(cli).get("projects") or {}).keys())
    result["project_trust_cleanup"] = drop_project_trust(cli, sorted(projects_after - projects_before))
    if not ledger.is_file():
        result.update(
            status="FAIL",
            detail="hook command produced no invocation ledger during the probe",
            log_tail=log.read_text(encoding="utf-8", errors="replace")[-500:],
        )
        return result
    lines = [line for line in ledger.read_text(encoding="utf-8").splitlines() if line.strip()]
    record = json.loads(lines[-1])
    message = "\n".join(_assistant_messages(log))
    result.update(
        invocations=len(lines),
        record_status=record.get("status"),
        network_model_calls=record.get("network_model_calls"),
        credential_reads=record.get("credential_reads"),
        jev_api_calls=record.get("jev_api_calls"),
        reward_summary=record.get("reward_summary"),
        visible_percentage="选择 |" in message,
        visible_token_status="Token：" in message,
        visible_reward_delta="+5" in message,
        assistant_message=message[-400:],
    )
    result["status"] = (
        "PASS"
        if result["record_status"] == "PASS"
        and result["visible_percentage"]
        and result["visible_token_status"]
        and result["visible_reward_delta"]
        else "FAIL"
    )
    return result



def doctor(
    cwd: Path, do_dispatch_probe: bool = True, ledger_baseline: Path | None = None
) -> tuple[int, dict[str, Any]]:
    cli = codex_cli()
    report: dict[str, Any] = {
        "schema_version": "solve-lite.codex-desktop-doctor.v1",
        "codex_cli": cli,
        "codex_cli_version": (run([cli, "--version"], timeout=30)[1] or "").strip(),
        "codex_home": str(codex_home()),
        "cwd": str(cwd),
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }
    checks: dict[str, dict[str, Any]] = {}

    checks["ADAPTER_SOURCE"] = check_package()

    plugin = _plugin_state(cli)
    checks["PLUGIN_INSTALLED"] = {
        "status": "PASS" if plugin.get("installed") else "FAIL",
        "version": plugin.get("localVersion"),
        "source": (plugin.get("source") or {}).get("path"),
    }
    checks["PLUGIN_ENABLED"] = {
        "status": "PASS" if plugin.get("enabled") else "FAIL",
        "enabled": bool(plugin.get("enabled")),
    }

    checks["SOURCE_CACHE_IDENTITY"] = check_identity() if plugin.get("installed") else {"status": "SKIPPED"}

    config = _config_read(cli)
    hooks, warnings = _hook_entries(cli, cwd)
    checks["HOST_DISCOVERY"] = {
        "status": "PASS" if len(hooks) == 1 else "FAIL",
        "hook_count": len(hooks),
        "warnings": warnings,
        "detail": "expected exactly one discovered Solve Lite hook",
    }
    hook = hooks[0] if len(hooks) == 1 else {}
    checks["ROUTER_REGISTERED"] = {
        "status": "PASS"
        if str(hook.get("key", "")).endswith(f"{HOOK_SOURCE}:{HOOK_EVENT}:0:0") and hook.get("enabled")
        else "FAIL",
        "key": hook.get("key"),
        "event_name": hook.get("eventName"),
        "source": hook.get("source"),
        "plugin_id": hook.get("pluginId"),
        "matcher": hook.get("matcher"),
        "command": hook.get("command"),
        "current_hash": hook.get("currentHash"),
    }

    trust_status = hook.get("trustStatus")
    state = ((config.get("hooks") or {}).get("state") or {}).get(hook.get("key") or "", {})
    checks["HOOK_TRUST"] = {
        "status": "PASS" if trust_status in {"trusted", "managed"} else "GATE",
        "trust_status": trust_status or "unknown",
        "current_hash": hook.get("currentHash"),
        "persisted_trusted_hash": state.get("trusted_hash"),
        "detail": "approved by the user"
        if trust_status in {"trusted", "managed"}
        else "Codex silently skips untrusted hooks; approve it in the Codex Desktop Hooks panel",
    }
    checks["RESTART_PERSISTENCE"] = {
        "status": "PASS"
        if trust_status in {"trusted", "managed"} and state.get("trusted_hash") == hook.get("currentHash")
        else "GATE",
        "detail": "trust lives in config hooks.state, so it survives a restart once approved",
    }

    project_trusted = trusted_project(cwd, config)
    checks["PROJECT_TRUST"] = {
        "status": "PASS" if project_trusted else "FAIL",
        "detail": "trusted" if project_trusted else "Codex only executes hooks inside a trusted project",
    }

    if do_dispatch_probe and plugin.get("installed"):
        checks["DISPATCH_PROBE"] = dispatch_probe(cli, cwd)
    else:
        checks["DISPATCH_PROBE"] = {"status": "SKIPPED", "detail": "dispatch probe disabled"}

    checks["REAL_INVOKE"] = real_invocation_evidence(default_workspace(), ledger_baseline)
    checks["ORDINARY_SESSION"] = check_ordinary_session(default_workspace(), ledger_baseline)

    hard = ["ADAPTER_SOURCE", "PLUGIN_INSTALLED", "PLUGIN_ENABLED", "SOURCE_CACHE_IDENTITY",
            "HOST_DISCOVERY", "ROUTER_REGISTERED", "PROJECT_TRUST"]
    failed = [name for name in hard if checks[name]["status"] != "PASS"]
    report["checks"] = checks
    if failed:
        report["result"] = "FAIL"
        report["failed_checks"] = failed
        return 1, report
    gate = checks["HOOK_TRUST"]["status"] != "PASS"
    product_checks = ("HOOK_TRUST", "RESTART_PERSISTENCE", "ORDINARY_SESSION", "REAL_INVOKE")
    product_pass = all(checks[name]["status"] == "PASS" for name in product_checks)
    if product_pass:
        report["result"] = "PASS"
        return 0, report
    if gate:
        report["result"] = "READY_FOR_PETER_HOOK_APPROVAL"
        report["approval"] = {
            "hook_key": checks["ROUTER_REGISTERED"]["key"],
            "current_hash": checks["ROUTER_REGISTERED"]["current_hash"],
            "where": "Codex Desktop -> Settings -> Hooks -> review and trust the Solve Lite hook",
            "then": "restart Codex Desktop, open a fresh ordinary session, ask one bounded question",
        }
        return 2, report
    if any(checks[name]["status"] == "GATE" for name in ("ORDINARY_SESSION", "REAL_INVOKE")):
        report["result"] = "GATE_AWAITING_ORDINARY_SESSION"
        report["next"] = (
            "if the ordinary session has not run yet: `snapshot --out FILE` first, run one bounded "
            "question in a fresh Codex Desktop session, then `doctor --ledger-baseline FILE`. "
            "If it already ran and the ledger still did not advance, the hook did not fire: that is a "
            "first-real-failure condition, freeze evidence and report it."
        )
        return 2, report
    report["result"] = "FAIL"
    report["failed_checks"] = [name for name in product_checks if checks[name]["status"] != "PASS"]
    return 1, report


def _backup_dir(stamp: str) -> Path:
    path = default_workspace() / "adapter-backups" / stamp
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    return path


def _snapshot(paths: list[Path], destination: Path) -> list[dict[str, Any]]:
    saved: list[dict[str, Any]] = []
    for source in paths:
        if not source.exists():
            saved.append({"path": str(source), "state": "absent"})
            continue
        target = destination / source.name
        if source.is_dir():
            shutil.copytree(source, target, symlinks=True)
        else:
            shutil.copy2(source, target)
        saved.append({"path": str(source), "state": "copied", "backup": str(target)})
    return saved


def install(dry_run: bool, receipt: Path | None) -> tuple[int, dict[str, Any]]:
    cli = codex_cli()
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    report: dict[str, Any] = {
        "schema_version": "solve-lite.codex-desktop-install.v1",
        "plugin_id": PLUGIN_ID,
        "codex_cli": cli,
        "codex_cli_version": (run([cli, "--version"], timeout=30)[1] or "").strip(),
        "dry_run": dry_run,
        "installed_at": stamp,
        "trust_written": False,
    }
    package = check_package()
    report["package"] = package
    if package["status"] != "PASS":
        report["result"] = "FAIL"
        return 1, report

    backup = _backup_dir(stamp)
    report["backup"] = _snapshot([codex_home() / "config.toml", marketplace_path()], backup)
    report["backup_dir"] = str(backup)

    if not dry_run:
        rc, output = run([cli, "plugin", "add", PLUGIN_ID], timeout=300)
        report["plugin_add"] = {"returncode": rc, "tail": output.strip().splitlines()[-6:]}
        if rc != 0:
            report["result"] = "FAIL"
            return 1, report
        state = _plugin_state(cli)
        if state.get("installed") and not state.get("enabled"):
            server = AppServer(cli)
            try:
                server.initialize()
                server.call(
                    "config/batchWrite",
                    {
                        "edits": [{
                            "keyPath": f'plugins."{PLUGIN_ID}".enabled',
                            "mergeStrategy": "upsert",
                            "value": True,
                        }],
                        "filePath": None,
                        "expectedVersion": None,
                        "reloadUserConfig": True,
                    },
                    seq=1,
                )
            finally:
                server.close()
            report["enabled_via"] = "config/batchWrite"

    identity = check_identity()
    report["identity"] = identity
    hooks, warnings = _hook_entries(cli, Path(os.path.expanduser("~")))
    report["discovery"] = {
        "hook_count": len(hooks),
        "warnings": warnings,
        "key": hooks[0].get("key") if hooks else None,
        "current_hash": hooks[0].get("currentHash") if hooks else None,
        "trust_status": hooks[0].get("trustStatus") if hooks else None,
        "enabled": hooks[0].get("enabled") if hooks else None,
        "command": hooks[0].get("command") if hooks else None,
    }
    ok = identity["status"] == "PASS" and len(hooks) == 1 and hooks[0].get("enabled")
    report["result"] = "READY_FOR_PETER_HOOK_APPROVAL" if ok else "FAIL"
    report["approval"] = {
        "required": True,
        "hook_key": report["discovery"]["key"],
        "current_hash": report["discovery"]["current_hash"],
        "where": "Codex Desktop -> Settings -> Hooks -> review and trust the Solve Lite hook",
        "note": "install never writes hook trust; only a visible user approval does",
    }
    if receipt is not None:
        receipt.parent.mkdir(parents=True, exist_ok=True)
        receipt.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        report["receipt"] = str(receipt)
    return (2 if ok else 1), report


def uninstall(confirmed: bool, purge_cache: bool) -> tuple[int, dict[str, Any]]:
    cli = codex_cli()
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    report: dict[str, Any] = {
        "schema_version": "solve-lite.codex-desktop-uninstall.v1",
        "plugin_id": PLUGIN_ID,
        "codex_cli": cli,
        "uninstalled_at": stamp,
        "confirmed": confirmed,
    }
    if not confirmed:
        report["result"] = "REFUSED_NEEDS_CONFIRMATION"
        report["hint"] = "pass --yes to remove the installed Solve Lite plugin and its cache"
        return 1, report

    backup = _backup_dir(stamp)
    targets = [codex_home() / "config.toml", marketplace_path()]
    cache_dir = cached_plugin_dir()
    if cache_dir is not None and purge_cache:
        targets.append(cache_dir)
    report["backup"] = _snapshot(targets, backup)
    report["backup_dir"] = str(backup)

    marketplace_before = (
        marketplace_path().read_text(encoding="utf-8") if marketplace_path().is_file() else ""
    )
    rc, output = run([cli, "plugin", "remove", PLUGIN_ID], timeout=300)
    report["plugin_remove"] = {"returncode": rc, "tail": output.strip().splitlines()[-6:]}

    if marketplace_path().is_file() and PLUGIN_NAME not in marketplace_path().read_text(encoding="utf-8"):
        marketplace_path().write_text(marketplace_before, encoding="utf-8")
        report["marketplace_restored"] = True

    state = _plugin_state(cli)
    hooks, _ = _hook_entries(cli, Path(os.path.expanduser("~")))
    report["verify"] = {
        "plugin_installed": bool(state.get("installed")),
        "hook_count": len(hooks),
        "cache_dir_removed": cache_dir is None or not cache_dir.exists(),
    }
    clean = not state.get("installed") and not hooks and (cache_dir is None or not cache_dir.exists())
    report["result"] = "PASS" if clean else "PARTIAL"
    report["rollback"] = {
        "backup_dir": str(backup),
        "restore": (
            f"cp -a '{backup}/config.toml' '{codex_home()}/config.toml' && "
            f"cp -a '{backup}/marketplace.json' '{marketplace_path()}' && "
            f"'{cli}' plugin add {PLUGIN_ID}"
        ),
    }
    return (0 if clean else 1), report


def render(report: dict[str, Any], as_json: bool) -> None:
    if as_json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return
    checks = report.get("checks")
    if checks:
        for name, value in checks.items():
            status = value.get("status")
            detail = value.get("trust_status") or value.get("hook_count") or value.get("detail") or ""
            print(f"{name}={status}" + (f"  # {detail}" if detail else ""))
    print(f"RESULT={report.get('result')}")
    probe = (checks or {}).get("DISPATCH_PROBE") or {}
    for key in ("visible_percentage", "visible_token_status", "visible_reward_delta", "record_status"):
        if probe.get(key) is not None:
            print(f"PROBE_{key.upper()}={probe[key]}")
    if probe.get("assistant_message"):
        print("PROBE_ASSISTANT_MESSAGE=" + probe["assistant_message"].replace("\n", " ⏎ "))
    for key in ("backup_dir", "receipt"):
        if report.get(key):
            print(f"{key.upper()}={report[key]}")
    approval = report.get("approval")
    if approval:
        print(f"APPROVE_HOOK_KEY={approval.get('hook_key')}")
        print(f"APPROVE_CURRENT_HASH={approval.get('current_hash')}")
        print(f"APPROVE_WHERE={approval.get('where')}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Solve Lite -> Codex Desktop adapter")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor_parser = sub.add_parser("doctor", help="verify install, discovery, trust and real invocation")
    doctor_parser.add_argument("--cwd", default=os.getcwd())
    doctor_parser.add_argument("--json", action="store_true")
    doctor_parser.add_argument(
        "--no-dispatch-probe",
        action="store_true",
        help="skip the one-turn end-to-end adapter probe (saves one model call)",
    )
    doctor_parser.add_argument(
        "--ledger-baseline",
        default=None,
        help="ledger baseline written by `snapshot`; turns REAL_INVOKE/ORDINARY_SESSION into advance proofs",
    )

    snapshot_parser = sub.add_parser("snapshot", help="record the reward-ledger baseline for the ordinary-session proof")
    snapshot_parser.add_argument("--out", default=None)
    snapshot_parser.add_argument("--json", action="store_true")

    rollout_parser = sub.add_parser("rollout-check", help="extract the visible contract from one session rollout")
    rollout_parser.add_argument("--session", required=True)
    rollout_parser.add_argument("--sessions-root", default=None)
    rollout_parser.add_argument("--json", action="store_true")

    install_parser = sub.add_parser("install", help="install/refresh the plugin and report the trust gate")
    install_parser.add_argument("--dry-run", action="store_true")
    install_parser.add_argument("--json", action="store_true")
    install_parser.add_argument("--receipt", default=None)

    uninstall_parser = sub.add_parser("uninstall", help="remove the plugin (backup first)")
    uninstall_parser.add_argument("--yes", action="store_true")
    uninstall_parser.add_argument("--keep-cache", action="store_true")
    uninstall_parser.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "doctor":
        baseline = Path(args.ledger_baseline).expanduser() if args.ledger_baseline else None
        code, report = doctor(Path(args.cwd).expanduser().resolve(), not args.no_dispatch_probe, baseline)
    elif args.command == "snapshot":
        report = ledger_snapshot(default_workspace())
        if args.out:
            target = Path(args.out).expanduser()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            report["out"] = str(target)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0
    elif args.command == "rollout-check":
        root = Path(args.sessions_root).expanduser() if args.sessions_root else None
        path = rollout_path(args.session, root)
        if path is None:
            print(json.dumps({"status": "FAIL", "detail": f"no session rollout for {args.session}"}, ensure_ascii=False))
            return 1
        report = rollout_evidence(path)
        report["session_id"] = args.session
        report["visible_obligations"] = visible_obligations(str(report.get("assistant_message") or ""))
        report["status"] = "PASS" if report.get("assistant_message") else "FAIL"
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0 if report["status"] == "PASS" else 1
    elif args.command == "install":
        receipt = Path(args.receipt).expanduser() if args.receipt else None
        code, report = install(args.dry_run, receipt)
    else:
        code, report = uninstall(args.yes, not args.keep_cache)
    render(report, getattr(args, "json", False))
    return code


if __name__ == "__main__":
    sys.exit(main())
