#!/usr/bin/env python3
"""Fail-closed, registry-driven host planning over the frozen public ABI."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from solve_lite_abi import route_prompt as _route_prompt


REGISTRY_PATH = Path(__file__).resolve().parents[1] / "assets" / "agent_registry.json"
REGISTRY_SCHEMA = "solve-lite.agent-registry.v2"
COLD_FORK_STATUS = "PASS_VERIFIED_FRESH_INSTALL_PUBLIC_ABI"
COLD_FORK_STATUS_PRIOR = "PASS_VERIFIED_PUBLIC_ABI_PRIOR_SCOPE"
COLD_FORK_PENDING = "UNTESTED_PUBLIC_ABI_AVAILABLE"
COLD_FORK_SUMMARY = "PASS_VERIFIED_FRESH_INSTALL_TWO_HOST_PUBLIC_ABI"
COLD_FORK_STATUSES = (COLD_FORK_STATUS, COLD_FORK_STATUS_PRIOR, COLD_FORK_PENDING)
SUPPORTED_MODES = (
    "explicit_host_id",
    "environment",
    "executable",
    "filesystem_marker",
)


class AgentAutoError(RuntimeError):
    """Base error for fail-closed host selection and planning."""


class RegistryError(AgentAutoError):
    pass


class UnknownHostError(AgentAutoError):
    pass


class AmbiguousHostError(AgentAutoError):
    pass


class UnsafePathError(AgentAutoError):
    pass


class ApplyNotAuthorizedError(AgentAutoError):
    pass


@dataclass(frozen=True)
class HostSpec:
    host_id: str
    aliases: Tuple[str, ...]
    priority: int
    compatibility_status: str
    cold_fork_status: str
    supported_modes: Tuple[str, ...]
    capabilities: Tuple[str, ...]
    public_abi_entrypoint: str
    public_adapter_entrypoint: Optional[str]
    mcp_config_key: Optional[str]
    mcp_cwd: Optional[str]
    environment_keys: Tuple[str, ...]
    executables: Tuple[str, ...]
    filesystem_markers: Tuple[str, ...]


@dataclass(frozen=True)
class InstallPlan:
    host_id: str
    source_root: str
    source_tree_sha256: str
    destination_root: str
    destination: str
    backup_root: str
    backup: str
    public_adapter_entrypoint: Optional[str]
    action: str = "DRY_RUN_PLAN_ONLY"
    cold_fork_test: str = COLD_FORK_STATUS


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RegistryError("%s must be a non-empty string" % name)
    return value.strip()


def _string_tuple(value: Any, name: str) -> Tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise RegistryError("%s must be a string list" % name)
    return tuple(value)


def _safe_relative(value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or not path.parts or ".." in path.parts:
        raise UnsafePathError("path must be relative and remain inside its declared root")
    return path


def _inside(root: Path, relative: str) -> Path:
    base = root.resolve()
    resolved = (base / _safe_relative(relative)).resolve()
    try:
        resolved.relative_to(base)
    except ValueError as exc:
        raise UnsafePathError("resolved path escapes its declared root") from exc
    return resolved


def _tree_sha256(root: Path) -> str:
    if not root.is_dir():
        raise UnsafePathError("source root must be a directory")
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise UnsafePathError("symlinks are not allowed in install sources")
        if path.is_file():
            relative = path.relative_to(root).as_posix()
            digest.update(relative.encode("utf-8"))
            digest.update(b"\0")
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def load_registry(path: Path = REGISTRY_PATH) -> Tuple[Tuple[str, ...], Tuple[HostSpec, ...]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != REGISTRY_SCHEMA:
        raise RegistryError("unsupported registry schema")
    modes = _string_tuple(payload.get("supported_modes_priority"), "supported_modes_priority")
    if not modes or len(modes) != len(set(modes)) or any(mode not in SUPPORTED_MODES for mode in modes):
        raise RegistryError("supported mode priority must be unique and known")
    if payload.get("cold_fork_test") != COLD_FORK_SUMMARY:
        raise RegistryError("cold fork summary does not match the frozen four-host evidence")
    raw_hosts = payload.get("hosts")
    if not isinstance(raw_hosts, list) or not raw_hosts:
        raise RegistryError("hosts must be a non-empty list")
    abi_entrypoint = _text(payload.get("public_abi_entrypoint"), "public_abi_entrypoint")
    hosts: List[HostSpec] = []
    identifiers = set()
    priorities = set()
    for raw in raw_hosts:
        if not isinstance(raw, dict) or not isinstance(raw.get("detection"), dict):
            raise RegistryError("each host must contain a detection mapping")
        host_id = _text(raw.get("host_id"), "host_id")
        aliases = _string_tuple(raw.get("aliases"), "aliases")
        priority = raw.get("priority")
        if not isinstance(priority, int) or priority in priorities:
            raise RegistryError("host priority must be a unique integer")
        priorities.add(priority)
        for identifier in (host_id,) + aliases:
            if identifier in identifiers:
                raise RegistryError("host identifiers and aliases must be unique")
            identifiers.add(identifier)
        host_modes = _string_tuple(raw.get("supported_modes"), "supported_modes")
        if any(mode not in modes for mode in host_modes):
            raise RegistryError("host declares a mode outside registry priority")
        detection = raw["detection"]
        adapter = raw.get("public_adapter_entrypoint")
        mcp_key = raw.get("mcp_config_key")
        mcp_cwd = raw.get("mcp_cwd")
        if adapter is not None and not isinstance(adapter, str):
            raise RegistryError("public adapter entrypoint must be a string or null")
        if mcp_key is not None and not isinstance(mcp_key, str):
            raise RegistryError("MCP config key must be a string or null")
        if mcp_cwd is not None and not isinstance(mcp_cwd, str):
            raise RegistryError("MCP cwd must be a string or null")
        host = HostSpec(
            host_id=host_id,
            aliases=aliases,
            priority=priority,
            compatibility_status=_text(raw.get("compatibility_status"), "compatibility_status"),
            cold_fork_status=_text(raw.get("cold_fork_status"), "cold_fork_status"),
            supported_modes=host_modes,
            capabilities=_string_tuple(raw.get("capabilities"), "capabilities"),
            public_abi_entrypoint=abi_entrypoint,
            public_adapter_entrypoint=adapter,
            mcp_config_key=mcp_key,
            mcp_cwd=mcp_cwd,
            environment_keys=_string_tuple(detection.get("environment_keys"), "environment_keys"),
            executables=_string_tuple(detection.get("executables"), "executables"),
            filesystem_markers=_string_tuple(detection.get("filesystem_markers"), "filesystem_markers"),
        )
        if host.cold_fork_status not in COLD_FORK_STATUSES:
            raise RegistryError("host cold fork status is not recognized")
        for marker in host.filesystem_markers:
            _safe_relative(marker)
        hosts.append(host)
    return modes, tuple(sorted(hosts, key=lambda item: (item.priority, item.host_id)))


def _mode_matches(mode: str, signals: Mapping[str, Any], hosts: Sequence[HostSpec]) -> List[HostSpec]:
    if mode == "explicit_host_id":
        explicit = str(signals.get("host_id") or "").strip().lower()
        if not explicit:
            return []
        return [host for host in hosts if explicit in (host.host_id,) + host.aliases]
    if mode == "environment":
        raw = signals.get("environment") or {}
        if not isinstance(raw, Mapping):
            raise AgentAutoError("environment signal must be a mapping")
        present = {str(key) for key, value in raw.items() if value is not None and value != ""}
        return [host for host in hosts if present.intersection(host.environment_keys)]
    if mode == "executable":
        raw = signals.get("executables") or []
        if not isinstance(raw, Iterable) or isinstance(raw, (str, bytes)):
            raise AgentAutoError("executables signal must be a list")
        present = {Path(str(item)).name.lower() for item in raw}
        return [host for host in hosts if present.intersection(name.lower() for name in host.executables)]
    if mode == "filesystem_marker":
        raw = signals.get("filesystem_markers") or []
        if not isinstance(raw, Iterable) or isinstance(raw, (str, bytes)):
            raise AgentAutoError("filesystem marker signal must be a list")
        present = {_safe_relative(str(item)).as_posix() for item in raw}
        return [host for host in hosts if present.intersection(host.filesystem_markers)]
    raise RegistryError("unknown detection mode")


def detect(signals: Mapping[str, Any], registry_path: Path = REGISTRY_PATH) -> HostSpec:
    """Select exactly one host from caller-supplied public signals."""
    if not isinstance(signals, Mapping):
        raise AgentAutoError("signals must be a mapping")
    modes, hosts = load_registry(registry_path)
    explicit = bool(str(signals.get("host_id") or "").strip())
    for mode in modes:
        matches = _mode_matches(mode, signals, [host for host in hosts if mode in host.supported_modes])
        if len(matches) > 1:
            raise AmbiguousHostError("multiple hosts matched the same supported detection mode")
        if matches:
            return matches[0]
        if mode == "explicit_host_id" and explicit:
            raise UnknownHostError("explicit host is not present in the public registry")
    raise UnknownHostError("no public host signal matched")


def invoke(signals: Mapping[str, Any], request: Mapping[str, Any], registry_path: Path = REGISTRY_PATH) -> Dict[str, Any]:
    """Detect a host, then call the frozen public ABI without rewriting its result."""
    host = detect(signals, registry_path)
    if "public_abi" not in host.capabilities:
        raise AgentAutoError("detected host does not expose the public ABI capability")
    allowed = {"workspace", "case", "session", "asset_root", "namespace", "invocation_id"}
    if not isinstance(request, Mapping) or set(request).difference(allowed):
        raise AgentAutoError("request contains unsupported ABI fields")
    if "workspace" not in request or "case" not in request:
        raise AgentAutoError("request requires workspace and case")
    return _route_prompt(
        request["workspace"],
        request["case"],
        request.get("session"),
        asset_root=request.get("asset_root"),
        namespace=str(request.get("namespace", "production")),
        invocation_id=request.get("invocation_id"),
    )


def translate_mcp_config(host: HostSpec, config: Mapping[str, Any]) -> Dict[str, Any]:
    """Translate canonical named-server data without writing host configuration."""
    if "mcp_plan" not in host.capabilities or not host.mcp_config_key or not host.mcp_cwd:
        raise AgentAutoError("host has no proven public MCP planning capability")
    if not isinstance(config, Mapping) or set(config).difference({"$schema", "mcpServers"}):
        raise AgentAutoError("canonical MCP config accepts only $schema and mcpServers")
    servers = config.get("mcpServers")
    if not isinstance(servers, Mapping) or not servers:
        raise AgentAutoError("canonical MCP config requires named servers")
    translated: Dict[str, Dict[str, Any]] = {}
    allowed = {"type", "command", "args", "cwd", "env_vars", "startup_timeout_sec", "tool_timeout_sec"}
    for name in sorted(servers):
        server = servers[name]
        if not isinstance(name, str) or not name or not isinstance(server, Mapping):
            raise AgentAutoError("MCP server names and definitions must be mappings")
        if set(server).difference(allowed):
            raise AgentAutoError("MCP server contains an unsupported field")
        command = server.get("command")
        if not isinstance(command, str) or not command:
            raise AgentAutoError("MCP server requires a command")
        args = server.get("args", [])
        if not isinstance(args, list) or any(not isinstance(item, str) for item in args):
            raise AgentAutoError("MCP args must be a string list")
        for item in args:
            if ".." in Path(item).parts:
                raise UnsafePathError("MCP argument path escapes the plugin root")
        cwd = server.get("cwd", ".")
        if cwd not in (".", "${PLUGIN_ROOT}"):
            raise UnsafePathError("MCP cwd must remain at the public plugin root")
        normalized = dict(server)
        normalized["args"] = list(args)
        normalized["cwd"] = host.mcp_cwd
        translated[name] = normalized
    return {host.mcp_config_key: translated}


def plan_skill_install(
    host: HostSpec,
    source_root: Path,
    destination_root: Path,
    destination_relative: str,
    backup_root: Path,
) -> InstallPlan:
    """Build a rollback-safe skill plan; never copy or alter host files."""
    if "skill_plan" not in host.capabilities:
        raise AgentAutoError("host has no public skill planning capability")
    source = source_root.resolve()
    if not (source / "SKILL.md").is_file():
        raise AgentAutoError("skill source requires SKILL.md")
    destination = _inside(destination_root, destination_relative)
    backup = _inside(backup_root, "%s/%s" % (host.host_id, _safe_relative(destination_relative).name))
    return InstallPlan(
        host_id=host.host_id,
        source_root=str(source),
        source_tree_sha256=_tree_sha256(source),
        destination_root=str(destination_root.resolve()),
        destination=str(destination),
        backup_root=str(backup_root.resolve()),
        backup=str(backup),
        public_adapter_entrypoint=host.public_adapter_entrypoint,
    )


def _adapter_apply(plan: InstallPlan, adapter: Any, method: str) -> Mapping[str, Any]:
    expected = plan.public_adapter_entrypoint
    if not expected or getattr(adapter, "public_entrypoint", None) != expected:
        raise ApplyNotAuthorizedError("apply requires the registry-pinned public adapter")
    operation = getattr(adapter, method, None)
    if not callable(operation):
        raise ApplyNotAuthorizedError("public adapter does not expose the requested operation")
    return operation(asdict(plan))


def install(plan: InstallPlan, *, apply: bool = False, adapter: Any = None) -> Mapping[str, Any]:
    """Return a dry-run plan, or delegate apply to the exact public adapter."""
    if not apply:
        return {"status": "DRY_RUN", "plan": asdict(plan), "host_mutation": 0}
    return _adapter_apply(plan, adapter, "install")


def verify(plan: InstallPlan) -> Mapping[str, Any]:
    """Read only: compare source identity and any existing destination tree."""
    source_hash = _tree_sha256(Path(plan.source_root))
    if source_hash != plan.source_tree_sha256:
        return {"status": "FAIL", "reason": "SOURCE_CHANGED", "host_mutation": 0}
    destination = Path(plan.destination)
    if not destination.exists():
        return {"status": "NOT_INSTALLED", "source_sha256": source_hash, "host_mutation": 0}
    target_hash = _tree_sha256(destination)
    return {
        "status": "PASS" if target_hash == source_hash else "FAIL",
        "source_sha256": source_hash,
        "target_sha256": target_hash,
        "host_mutation": 0,
    }


def rollback(plan: InstallPlan, *, apply: bool = False, adapter: Any = None) -> Mapping[str, Any]:
    """Return a rollback plan, or delegate it to the registry-pinned adapter."""
    if not apply:
        return {
            "status": "DRY_RUN",
            "action": "RESTORE_BACKUP_OR_REMOVE_NEW_TARGET",
            "destination": plan.destination,
            "backup": plan.backup,
            "host_mutation": 0,
        }
    return _adapter_apply(plan, adapter, "rollback")


__all__ = [
    "AgentAutoError",
    "AmbiguousHostError",
    "ApplyNotAuthorizedError",
    "COLD_FORK_STATUS",
    "COLD_FORK_STATUS_PRIOR",
    "COLD_FORK_PENDING",
    "COLD_FORK_SUMMARY",
    "COLD_FORK_STATUSES",
    "HostSpec",
    "InstallPlan",
    "RegistryError",
    "UnknownHostError",
    "UnsafePathError",
    "detect",
    "install",
    "invoke",
    "load_registry",
    "plan_skill_install",
    "rollback",
    "translate_mcp_config",
    "verify",
]
