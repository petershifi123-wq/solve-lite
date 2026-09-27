#!/usr/bin/env python3
"""Host-side hook registration for Solve Lite (P1: no model discretion).

Two real hosts are handled:

``workbuddy``
    WorkBuddy AI desktop ships the CodeBuddy CLI (``@genie/agent-cli``).  Its
    agent loop loads both settings hooks and plugin hooks.  Solve Lite therefore
    uses exactly one authoritative plugin-layer ``UserPromptSubmit`` hook and
    removes its own legacy settings-layer duplicate.  The copied plugin resolves
    its root from WorkBuddy's real ``CODEBUDDY_PLUGIN_ROOT`` /
    ``CLAUDE_PLUGIN_ROOT`` environment, never from the unsupported generic
    ``PLUGIN_ROOT`` variable.

``doubao``
    Doubao Work (``DoubaoWork.app``) runs a cloud agent with a local skill
    workspace.  It exposes **no hook API** - the app bundle contains no
    ``UserPromptSubmit`` / ``hookSpecificOutput`` / hook config reader at all -
    so a hook cannot be registered into it.  What *is* host-writable is the
    agent skill workspace (``.user_skills/<name>``); the installer copies the
    plugin there and reports the honest status plus a copy-paste one-step
    command that performs the same pre-prompt Lite run without any hook, so
    activation never depends on the host model choosing to invoke a skill.

Nothing here writes outside the user's own host config directories, and every
write is backed up first.  ``--config-dir`` redirects the whole operation to a
sandbox copy, which is how the host-shaped tests exercise it.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

SCHEMA = "solve-lite.host-hook-registration.v1"
MARKER = "solve-lite"
HOOK_SCRIPT_REL = "hooks/user_prompt_submit.py"
SKILL_REL = "skills/solve-lite"
REGISTRY_REL = "skills/solve-lite/assets/agent_registry.json"
PYTHON = "/usr/bin/python3"


def _home() -> Path:
    return Path.home()


def _integration(plugin_root: Path, host_id: str) -> Dict[str, Any]:
    registry = json.loads((Path(plugin_root) / REGISTRY_REL).read_text(encoding="utf-8"))
    host = next((item for item in registry.get("hosts", []) if item.get("host_id") == host_id), None)
    if not host or not isinstance(host.get("integration"), dict):
        raise RuntimeError("host integration missing from agent_registry.json: %s" % host_id)
    return host["integration"]


@dataclass(frozen=True)
class HostSpec:
    host_id: str
    display: str
    hook_api: str
    hook_api_evidence: str
    config_env: Sequence[str] = field(default_factory=tuple)
    config_candidates: Sequence[Path] = field(default_factory=tuple)
    settings_filename: str = "settings.json"
    skill_dest: Optional[Path] = None
    skill_locator: str = ""


def _hosts() -> Dict[str, HostSpec]:
    return {
        "workbuddy": HostSpec(
            host_id="workbuddy",
            display="WorkBuddy AI desktop (CodeBuddy CLI agent)",
            hook_api="settings_json_hooks",
            hook_api_evidence=(
                "app.asar.unpacked/cli/dist/codebuddy-headless.js: "
                "async getHooks(event){let es=await this.settingsManager.get(\"hooks\");"
                "...loadHooksFromPlugins(event)} and the hook event table "
                "[PreToolUse,PostToolUse,Notification,UserPromptSubmit,Stop,"
                "SubagentStop,PreCompact,SessionStart,SessionEnd,WorktreeCreate]"
            ),
            config_env=("WORKBUDDY_CONFIG_DIR", "CODEBUDDY_CONFIG_DIR"),
            config_candidates=(
                _home() / ".workbuddy-ai",
                _home() / ".workbuddy",
                _home() / ".codebuddy",
            ),
        ),
        "doubao": HostSpec(
            host_id="doubao",
            display="Doubao Work (DoubaoWork.app)",
            hook_api="none",
            hook_api_evidence=(
                "no hook API in the host: 'UserPromptSubmit'/'hookSpecificOutput'"
                "/hook config reader are absent from the app bundle and from the "
                "agent workspace; the workspace only exposes .user_skills (skill "
                "files) plus a sandbox runtime"
            ),
            config_candidates=(
                _home() / "Library" / "Application Support" / "DoubaoWork",
            ),
            skill_dest=(
                _home()
                / "Library"
                / "Application Support"
                / "DoubaoWork"
                / "Default"
                / ".doubaowork"
                / "agent_mode"
                / "workspace"
                / ".user_skills"
                / "solve-lite"
            ),
            skill_locator=(
                "~/Library/Application Support/DoubaoWork/Default/.doubaowork/"
                "agent_mode/workspace/.user_skills/solve-lite"
            ),
        ),
        "generic": HostSpec(
            host_id="generic",
            display="Any host that reads AGENTS/SKILL instructions (portable path)",
            hook_api="none",
            hook_api_evidence=(
                "no host hook API assumed: the portable path relies on (a) the skill banner "
                "carrying SOLVE_LITE_MANDATORY_FIRST_STEP and (b) tools/one_step_command, which "
                "runs the pre-prompt Lite pass outside the host model"
            ),
            config_env=("SOLVE_LITE_HOST_CONFIG_DIR",),
            config_candidates=(),
            skill_dest=_home() / ".solve-lite" / "hosts" / "generic" / "skills" / "solve-lite",
            skill_locator="~/.solve-lite/hosts/generic/skills/solve-lite",
        ),
    }


def resolve_auto(override: Optional[Path] = None) -> str:
    """Pick a host id without the operator naming one.

    Order: explicit env marker -> a known host's config dir that exists on disk ->
    the portable ``generic`` path. This is what makes "any host that sees us"
    work: hosts we have an adapter for get that adapter, everything else gets the
    portable skill banner + one-step command.
    """
    for env_name, host_id in (("WORKBUDDY_CONFIG_DIR", "workbuddy"),
                              ("CODEBUDDY_CONFIG_DIR", "workbuddy"),
                              ("SOLVE_LITE_HOST", None)):
        value = os.environ.get(env_name)
        if value and host_id:
            return host_id
        if value and host_id is None:
            wanted = value.strip().lower()
            if wanted in _hosts():
                return wanted
            return "generic"
    for host_id, spec in _hosts().items():
        if host_id == "generic":
            continue
        for candidate in spec.config_candidates:
            if Path(candidate).exists():
                return host_id
    return "generic"


def host_spec(host_id: str) -> HostSpec:
    if host_id == "auto":
        host_id = resolve_auto()
    hosts = _hosts()
    if host_id not in hosts:
        raise SystemExit("unknown host: %s (known: %s)" % (host_id, ",".join(sorted(hosts))))
    return hosts[host_id]


def hook_command(plugin_root: Path) -> str:
    """Absolute-path command; works in hosts that never expand ${PLUGIN_ROOT}.

    WorkBuddy reported the failure mode directly: a command that relies on
    ${PLUGIN_ROOT} is executed by the host's shell, where the variable is unset,
    so the path collapses to "/hooks/..." and the hook never runs.  We therefore
    bake the resolved absolute path in, and still export PLUGIN_ROOT for the hook
    script's own use.
    """
    root = Path(plugin_root).resolve()
    script = root / HOOK_SCRIPT_REL
    return 'PLUGIN_ROOT="%s" %s "%s"' % (root, PYTHON, script)


def plugin_hook_command(plugin_root: Path, host_id: str) -> str:
    """Fail-open command for a plugin-layer hook using the host's real root env."""
    envs = list(_integration(plugin_root, host_id).get("plugin_root_env") or [])
    if not envs:
        raise RuntimeError("plugin_root_env missing for host: %s" % host_id)
    expression = ""
    for name in reversed(envs):
        expression = "${%s:-%s}" % (name, expression)
    return (
        "sh -c 'D=%s; F=\"$D/%s\"; P=\"$D/skills/solve-lite/runtime/specialist-env/bin/python3\"; "
        "if [ -n \"$D\" ] && [ -f \"$F\" ]; then [ -x \"$P\" ] || P=%s; exec \"$P\" \"$F\"; fi; exit 0'"
        % (expression, HOOK_SCRIPT_REL, PYTHON)
    )


def _hook_document(command: str) -> Dict[str, Any]:
    return {
        "hooks": {
            "UserPromptSubmit": [
                {"hooks": [{"type": "command", "command": command}]}
            ]
        }
    }


def one_step_command(plugin_root: Path) -> str:
    """Copy-paste command that runs the very same pre-prompt step with no hook.

    The prompt is taken from the macOS clipboard and the injected prompt is
    copied back, so a host without any hook API can still get a mechanism-level
    activation instead of relying on the host model choosing a skill.
    """
    root = Path(plugin_root).expanduser()
    nested_python = root / "skills" / "solve-lite" / "runtime" / "specialist-env" / "bin" / "python3"
    flat_python = root / "runtime" / "specialist-env" / "bin" / "python3"
    python = next((path for path in (nested_python, flat_python) if path.is_file() and os.access(path, os.X_OK)), Path(PYTHON))
    return '"%s" "%s" --clipboard' % (python.as_posix(), (root / HOOK_SCRIPT_REL).as_posix())


# --------------------------------------------------------------------------- #
# workbuddy
# --------------------------------------------------------------------------- #
def resolve_config_dirs(spec: HostSpec, override: Optional[Path]) -> List[Path]:
    if override is not None:
        return [Path(override).expanduser()]
    resolved: List[Path] = []
    for env_key in spec.config_env:
        value = os.environ.get(env_key)
        if value and value.strip():
            resolved.append(Path(value.strip()).expanduser())
    if not resolved:
        present = [p for p in spec.config_candidates if p.is_dir()]
        resolved = present or [spec.config_candidates[0]]
    unique: List[Path] = []
    for path in resolved:
        if path not in unique:
            unique.append(path)
    return unique


def _is_ours(entry: Any) -> bool:
    if not isinstance(entry, dict):
        return False
    for hook in entry.get("hooks", []) if isinstance(entry.get("hooks"), list) else []:
        command = str((hook or {}).get("command") or "")
        if HOOK_SCRIPT_REL in command and MARKER in command:
            return True
    return False


def _read_json(path: Path) -> Dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _write_json_atomic(path: Path, document: Dict[str, Any], backup_suffix: str) -> Optional[str]:
    backup = None
    if path.is_file():
        backup = "%s.bak-%s-%s" % (path, MARKER, backup_suffix)
        shutil.copy2(path, backup)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp-%s" % os.getpid())
    tmp.write_text(json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                   encoding="utf-8")
    os.replace(tmp, path)
    return backup


def register_settings_hook(config_dir: Path, plugin_root: Path, *, dry_run: bool = False) -> Dict[str, Any]:
    settings_path = config_dir / "settings.json"
    document = _read_json(settings_path)
    hooks = document.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}
    existing = hooks.get("UserPromptSubmit")
    entries = [e for e in existing if isinstance(e, dict)] if isinstance(existing, list) else []
    kept = [e for e in entries if not _is_ours(e)]
    command = hook_command(plugin_root)
    kept.append({"hooks": [{"type": "command", "command": command}]})
    hooks["UserPromptSubmit"] = kept
    document["hooks"] = hooks
    stamp = time.strftime("%Y%m%d%H%M%S", time.localtime())
    backup = None
    if not dry_run:
        backup = _write_json_atomic(settings_path, document, stamp)
    return {
        "config_dir": str(config_dir),
        "settings_path": str(settings_path),
        "settings_written": not dry_run,
        "backup": backup,
        "hook_command": command,
        "removed_previous_solve_lite_entries": sum(1 for e in entries if _is_ours(e)),
        "total_user_prompt_submit_entries": len(kept),
    }


def remove_settings_hook(config_dir: Path, *, dry_run: bool = False) -> Dict[str, Any]:
    """Remove only Solve Lite's settings-layer hook so plugin loading stays single-shot."""
    settings_path = config_dir / "settings.json"
    document = _read_json(settings_path)
    hooks = document.get("hooks") if isinstance(document.get("hooks"), dict) else {}
    existing = hooks.get("UserPromptSubmit")
    entries = [e for e in existing if isinstance(e, dict)] if isinstance(existing, list) else []
    kept = [e for e in entries if not _is_ours(e)]
    removed = len(entries) - len(kept)
    if removed:
        hooks["UserPromptSubmit"] = kept
        document["hooks"] = hooks
        if not dry_run:
            _write_json_atomic(settings_path, document, time.strftime("%Y%m%d%H%M%S", time.localtime()))
    return {
        "settings_path": str(settings_path),
        "removed_solve_lite_entries": removed,
        "remaining_user_prompt_submit_entries": len(kept),
    }


def _marketplace_dir(config_dir: Path) -> Path:
    return config_dir / "plugins" / "marketplaces" / "solve-lite-local"


def register_plugin_layer(config_dir: Path, plugin_root: Path, *, host_id: str = "workbuddy",
                          dry_run: bool = False) -> Dict[str, Any]:
    """Directory marketplaces are a first-class host feature (`workbuddy-builtin`)."""
    marketplace_root = _marketplace_dir(config_dir)
    plugin_copy = marketplace_root / "plugins" / "solve-lite"
    manifest_dir = marketplace_root / ".codebuddy-plugin"
    manifest = {
        "name": "solve-lite-local",
        "interface": {"displayName": "Solve Lite Local"},
        "plugins": [
            {
                "name": "solve-lite",
                "source": "./plugins/solve-lite",
                "category": "productivity",
            }
        ],
    }
    known_path = config_dir / "plugins" / "known_marketplaces.json"
    known = _read_json(known_path)
    known["solve-lite-local"] = {
        "manifestName": "solve-lite-local",
        "type": "directory",
        "source": {"source": "directory", "path": str(marketplace_root)},
        "installLocation": str(marketplace_root),
        "description": "Local Solve Lite plugin marketplace (registered by the installer)",
        "autoUpdate": False,
    }
    settings_path = config_dir / "settings.json"
    settings = _read_json(settings_path)
    enabled = settings.get("enabledPlugins")
    if not isinstance(enabled, dict):
        enabled = {}
    integration = _integration(plugin_root, host_id)
    plugin_id = str((integration.get("plugin_identity") or {}).get("canonical") or "")
    if not plugin_id:
        raise RuntimeError("plugin_identity.canonical missing for host: %s" % host_id)
    enabled[plugin_id] = True
    settings["enabledPlugins"] = enabled
    stamp = time.strftime("%Y%m%d%H%M%S", time.localtime())
    command = plugin_hook_command(plugin_root, host_id)
    if dry_run:
        return {"marketplace_root": str(marketplace_root), "plugin_copy": str(plugin_copy),
                "written": False, "manifest": manifest, "hook_command": command}
    if plugin_copy.exists():
        shutil.rmtree(plugin_copy)
    plugin_copy.parent.mkdir(parents=True, exist_ok=True)
    # Preserve venv and model-view symlinks. Dereferencing a macOS framework
    # Python symlink copies only its tiny launcher binary; the copied plugin then
    # fails at runtime because @executable_path/../Python3 is absent.
    shutil.copytree(plugin_root, plugin_copy, symlinks=True)
    source_runtime_raw = plugin_root / "skills" / "solve-lite" / "runtime"
    source_runtime = source_runtime_raw.resolve()
    copied_runtime = (plugin_copy / "skills" / "solve-lite" / "runtime").resolve()
    pyvenv = copied_runtime / "specialist-env" / "pyvenv.cfg"
    if pyvenv.is_file():
        text = pyvenv.read_text(encoding="utf-8", errors="replace")
        text = text.replace(str(source_runtime_raw), str(copied_runtime))
        text = text.replace(str(source_runtime), str(copied_runtime))
        pyvenv.write_text(text, encoding="utf-8")
    for name in ("python", "python3", "python3.9"):
        source_link = source_runtime / "specialist-env" / "bin" / name
        copied_link = copied_runtime / "specialist-env" / "bin" / name
        if not source_link.is_symlink() or not copied_link.is_symlink():
            continue
        resolved = source_link.resolve()
        try:
            relative = resolved.relative_to(source_runtime)
        except ValueError:
            continue  # external system Python: the preserved absolute link is valid
        copied_link.unlink()
        target = copied_runtime / relative
        copied_link.symlink_to(os.path.relpath(target, copied_link.parent))
    (plugin_copy / "hooks" / "hooks.json").write_text(
        json.dumps(_hook_document(command), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (manifest_dir / "marketplace.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    known_backup = _write_json_atomic(known_path, known, stamp)
    settings_backup = _write_json_atomic(settings_path, settings, stamp)
    return {
        "marketplace_root": str(marketplace_root),
        "plugin_copy": str(plugin_copy),
        "written": True,
        "known_marketplaces_backup": known_backup,
        "settings_backup": settings_backup,
        "enabled_plugins_key": plugin_id,
        "hook_command": command,
        "hook_state": "HOOK_ACTIVE",
        "host_load_observed": False,
        "note": "config written; whether the desktop UI loads it is not observable offline",
    }


# --------------------------------------------------------------------------- #
# doubao
# --------------------------------------------------------------------------- #
SKILL_FIRST_STEP_MARKER = "SOLVE_LITE_MANDATORY_FIRST_STEP"


def _relocate_skill_runtime(source_runtime: Path, copied_runtime: Path) -> None:
    """Make a copied self-contained skill refer only to its installed paths."""
    source_runtime_raw = source_runtime
    source_runtime_resolved = source_runtime.resolve()
    copied_runtime_resolved = copied_runtime.resolve()
    replacements = (
        (str(source_runtime_raw), str(copied_runtime_resolved)),
        (str(source_runtime_resolved), str(copied_runtime_resolved)),
    )
    pyvenv = copied_runtime / "specialist-env" / "pyvenv.cfg"
    if pyvenv.is_file():
        text = pyvenv.read_text(encoding="utf-8", errors="replace")
        for old, new in replacements:
            text = text.replace(old, new)
        pyvenv.write_text(text, encoding="utf-8")
    for name in ("python", "python3", "python3.9"):
        source_link = source_runtime / "specialist-env" / "bin" / name
        copied_link = copied_runtime / "specialist-env" / "bin" / name
        if not source_link.is_symlink() or not copied_link.is_symlink():
            continue
        resolved = source_link.resolve()
        try:
            relative = resolved.relative_to(source_runtime_resolved)
        except ValueError:
            continue
        copied_link.unlink()
        target = copied_runtime_resolved / relative
        copied_link.symlink_to(os.path.relpath(target, copied_link.parent))
    for relative in (
        Path("specialist-env") / "solve-lite-specialist-runtime.json",
        Path("addons") / "solve-lite-int4-dlc" / "dlc-registry.json",
    ):
        path = copied_runtime / relative
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for old, new in replacements:
            text = text.replace(old, new)
        path.write_text(text, encoding="utf-8")


def install_skill(spec: HostSpec, plugin_root: Path, *, override: Optional[Path] = None,
                  dry_run: bool = False) -> Dict[str, Any]:
    if spec.skill_dest is None:
        return {"status": "NO_SKILL_LOCATION"}
    dest = Path(override).expanduser() if override is not None else Path(spec.skill_dest)
    report: Dict[str, Any] = {"destination": str(dest), "locator": spec.skill_locator}
    if dry_run:
        report.update({"status": "DRY_RUN", "exists": dest.exists()})
        return report
    stamp = time.strftime("%Y%m%d%H%M%S", time.localtime())
    backup = None
    if dest.exists():
        backup = "%s.bak-%s-%s" % (dest, MARKER, stamp)
        if Path(backup).exists():
            shutil.rmtree(backup)
        shutil.move(str(dest), backup)
    dest.parent.mkdir(parents=True, exist_ok=True)
    source = plugin_root / SKILL_REL
    shutil.copytree(source, dest, symlinks=True)
    hook_source = plugin_root / HOOK_SCRIPT_REL
    hook_dest = dest / HOOK_SCRIPT_REL
    hook_dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(hook_source, hook_dest)
    _relocate_skill_runtime(source / "runtime", dest / "runtime")
    skill_md = dest / "SKILL.md"
    text = skill_md.read_text(encoding="utf-8") if skill_md.is_file() else ""
    destination_command = one_step_command(dest)
    banner = (
        "\n\n<!-- %s -->\n## 设备级无条件第一步（勿跳过）\n\n"
        "本宿主机没有 hook 接口，因此 Solve Lite 不能靠宿主事件强制触发。"
        "为了让激活不依赖你的自由裁量：**每次收到用户消息，你必须在作答前先执行一次**\n\n"
        "```\n%s\n```\n\n"
        "并把它的结构化输出（激活回执 / 本地路由结论 / Token 与奖励结算）原样并入回答。"
        "若该命令报告 `NO_LOCAL_DECISION`，就如实说明本轮本地没有可注入结论，不要编造选择概率、Token 或奖励数字。\n"
        % (SKILL_FIRST_STEP_MARKER, destination_command)
    )
    if SKILL_FIRST_STEP_MARKER not in text:
        skill_md.write_text(text.rstrip() + banner, encoding="utf-8")
    else:
        lines = []
        for line in text.splitlines():
            if HOOK_SCRIPT_REL in line and ("python3" in line or PYTHON in line):
                prefix = line[:len(line) - len(line.lstrip())]
                if line.lstrip().startswith("*"):
                    lines.append(prefix + "* one-step command: `" + destination_command + "`.")
                else:
                    lines.append(prefix + destination_command)
            else:
                lines.append(line)
        skill_md.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    report.update({"status": "INSTALLED", "backup": backup,
                   "mandatory_first_step_banner": True,
                   "one_step_command": destination_command})
    return report


# --------------------------------------------------------------------------- #
# driver
# --------------------------------------------------------------------------- #
def detect(host_id: str, override: Optional[Path] = None) -> Dict[str, Any]:
    spec = host_spec(host_id)
    report: Dict[str, Any] = {
        "host_id": spec.host_id,
        "display": spec.display,
        "hook_api": spec.hook_api,
        "hook_api_evidence": spec.hook_api_evidence,
    }
    if host_id == "workbuddy":
        plugin_root = Path(__file__).resolve().parents[1] / "plugins" / "solve-lite"
        plugin_id = str((_integration(plugin_root, host_id).get("plugin_identity") or {}).get("canonical") or "")
        dirs = resolve_config_dirs(spec, override)
        report["config_dirs"] = []
        for config_dir in dirs:
            settings_path = config_dir / spec.settings_filename
            document = _read_json(settings_path)
            hooks = document.get("hooks") if isinstance(document.get("hooks"), dict) else {}
            entries = hooks.get("UserPromptSubmit") if isinstance(hooks.get("UserPromptSubmit"), list) else []
            settings_count = sum(1 for entry in entries if _is_ours(entry))
            plugin_copy = _marketplace_dir(config_dir) / "plugins" / "solve-lite"
            plugin_hooks = _read_json(plugin_copy / "hooks" / "hooks.json").get("hooks", {})
            plugin_entries = plugin_hooks.get("UserPromptSubmit") if isinstance(plugin_hooks, dict) else []
            plugin_commands = [
                str(hook.get("command") or "")
                for group in plugin_entries if isinstance(group, dict)
                for hook in group.get("hooks", []) if isinstance(hook, dict)
                and hook.get("type") == "command"
            ] if isinstance(plugin_entries, list) else []
            enabled = document.get("enabledPlugins") or {}
            plugin_enabled = bool(isinstance(enabled, dict) and enabled.get(plugin_id))
            plugin_active = int(plugin_enabled and len(plugin_commands) == 1)
            active_sources = settings_count + plugin_active
            script_exists = (plugin_copy / HOOK_SCRIPT_REL).is_file()
            if active_sources > 1 or len(plugin_commands) > 1:
                hook_state = "HOOK_ERROR"
            elif active_sources == 1 and (settings_count or script_exists):
                hook_state = "HOOK_ACTIVE"
            else:
                hook_state = "HOOK_MISSING"
            report["config_dirs"].append({
                "config_dir": str(config_dir),
                "exists": config_dir.is_dir(),
                "settings_path": str(settings_path),
                "settings_exists": settings_path.is_file(),
                "writable": os.access(settings_path.parent, os.W_OK) if settings_path.parent.exists() else False,
                "registered": hook_state == "HOOK_ACTIVE",
                "hook_state": hook_state,
                "active_solve_lite_sources": active_sources,
                "settings_solve_lite_entries": settings_count,
                "plugin_hook_commands": plugin_commands,
                "plugin_script_exists": script_exists,
                "user_prompt_submit_entries": len(entries),
                "enabled_plugins": sorted(enabled.keys()) if isinstance(enabled, dict) else [],
            })
    else:
        destination = Path(override).expanduser() if override is not None else spec.skill_dest
        report["skill_destination"] = str(destination) if destination else None
        report["skill_installed"] = bool(destination and Path(destination).is_dir())
        report["mandatory_first_step_present"] = bool(
            destination
            and (Path(destination) / "SKILL.md").is_file()
            and SKILL_FIRST_STEP_MARKER
            in (Path(destination) / "SKILL.md").read_text(encoding="utf-8", errors="replace")
        )
    return report


def register(host_id: str, plugin_root: Path, *, override: Optional[Path] = None,
             dry_run: bool = False, install_plugin_layer: bool = True) -> Dict[str, Any]:
    spec = host_spec(host_id)
    report: Dict[str, Any] = {
        "schema_version": SCHEMA,
        "host_id": spec.host_id,
        "plugin_root": str(plugin_root),
        "hook_api": spec.hook_api,
        "dry_run": dry_run,
    }
    if host_id == "workbuddy":
        results = []
        for config_dir in resolve_config_dirs(spec, override):
            use_plugin_layer = install_plugin_layer and (
                config_dir.name in (".workbuddy-ai", ".workbuddy") or override is not None
            )
            if use_plugin_layer:
                entry = {"config_dir": str(config_dir)}
                entry["settings_dedup"] = remove_settings_hook(config_dir, dry_run=dry_run)
                entry["plugin_layer"] = register_plugin_layer(
                    config_dir, plugin_root, host_id=host_id, dry_run=dry_run)
            else:
                entry = register_settings_hook(config_dir, plugin_root, dry_run=dry_run)
            results.append(entry)
        report["registrations"] = results
        report["hook_registration"] = "REGISTERED" if not dry_run else "DRY_RUN"
        report["status"] = "PASS"
        report["activation_model"] = "UNCONDITIONAL_HOST_HOOK"
        report["one_step_command"] = one_step_command(plugin_root)
        report["verification"] = "run tools/hook_selftest.py --host workbuddy"
    elif host_id == "generic":
        report["skill"] = install_skill(spec, plugin_root, override=override, dry_run=dry_run)
        report["hook_registration"] = "PORTABLE_SKILL_BANNER"
        report["activation_model"] = "OUT_OF_MODEL_PREPROMPT_STEP"
        report["one_step_command"] = one_step_command(plugin_root)
        report["portable_note"] = (
            "any host that reads the installed skill gets SOLVE_LITE_MANDATORY_FIRST_STEP; "
            "hosts with a settings.json hook API should be registered explicitly by id"
        )
        report["verification"] = "run tools/hook_selftest.py --host generic"
    else:
        report["skill"] = install_skill(spec, plugin_root, override=override, dry_run=dry_run)
        report["hook_registration"] = "UNAVAILABLE_NO_HOST_HOOK_API"
        if host_id == "doubao":
            report["status"] = "UNAVAILABLE_EXPECTED"
            report["native_hook_api"] = "UNAVAILABLE_EXPECTED"
        report["activation_model"] = "OUT_OF_MODEL_PREPROMPT_STEP"
        destination = Path((report.get("skill") or {}).get("destination") or plugin_root)
        report["one_step_command"] = one_step_command(destination)
        report["fallback_strength"] = (
            "the one-step command performs the pre-prompt Lite run outside the host "
            "model; the skill banner additionally makes it a mandatory first step"
        )
        report["verification"] = "run tools/hook_selftest.py --host doubao"
    return report


def unregister(host_id: str, plugin_root: Path, *, override: Optional[Path] = None) -> Dict[str, Any]:
    spec = host_spec(host_id)
    if host_id != "workbuddy":
        return {"host_id": host_id, "status": "NOTHING_TO_UNREGISTER"}
    removed = []
    plugin_id = str((_integration(plugin_root, host_id).get("plugin_identity") or {}).get("canonical") or "")
    for config_dir in resolve_config_dirs(spec, override):
        settings_path = config_dir / "settings.json"
        document = _read_json(settings_path)
        hooks = document.get("hooks") if isinstance(document.get("hooks"), dict) else {}
        entries = hooks.get("UserPromptSubmit") if isinstance(hooks.get("UserPromptSubmit"), list) else []
        kept = [e for e in entries if not _is_ours(e)]
        if len(kept) != len(entries):
            hooks["UserPromptSubmit"] = kept
            if hooks:
                document["hooks"] = hooks
            stamp = time.strftime("%Y%m%d%H%M%S", time.localtime())
            _write_json_atomic(settings_path, document, stamp)
            removed.append(str(settings_path))
        enabled = document.get("enabledPlugins")
        if isinstance(enabled, dict) and plugin_id in enabled:
            enabled.pop(plugin_id)
            _write_json_atomic(settings_path, document, time.strftime("%Y%m%d%H%M%S", time.localtime()))
    return {"host_id": host_id, "settings_restored": removed}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Solve Lite host hook registration")
    parser.add_argument("action", choices=("detect", "register", "unregister", "one-step"))
    parser.add_argument("--host", default="auto", help="workbuddy|doubao|auto")
    parser.add_argument("--plugin-root", type=Path, default=Path(__file__).resolve().parents[1] / "plugins" / "solve-lite")
    parser.add_argument("--config-dir", type=Path, default=None, help="sandbox override for the host config dir")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-plugin-layer", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    plugin_root = args.plugin_root.expanduser()
    targets = ["workbuddy", "doubao"] if args.host == "auto" else [args.host]
    output: Dict[str, Any] = {"schema_version": SCHEMA, "action": args.action, "hosts": {}}
    for host_id in targets:
        if args.action == "detect":
            output["hosts"][host_id] = detect(host_id, args.config_dir)
        elif args.action == "register":
            output["hosts"][host_id] = register(
                host_id, plugin_root, override=args.config_dir, dry_run=args.dry_run,
                install_plugin_layer=not args.no_plugin_layer)
        elif args.action == "unregister":
            output["hosts"][host_id] = unregister(host_id, plugin_root, override=args.config_dir)
        else:
            output["hosts"][host_id] = {"one_step_command": one_step_command(plugin_root)}
    if args.json:
        print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    else:
        for host_id, entry in output["hosts"].items():
            print("== %s" % host_id)
            print(json.dumps(entry, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
