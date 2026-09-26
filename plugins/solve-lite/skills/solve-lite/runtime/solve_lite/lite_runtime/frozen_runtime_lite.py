from __future__ import annotations

import hashlib
import importlib
import json
import os
import sys
import time
import uuid
from collections import defaultdict
from pathlib import Path
from typing import Any

from ..core import canonical_json, workspace_root
from ..identity import current_identity
from ..reward import attach_reward, local_elapsed_ns, start_local_timer


from .capability import (
    CORE_ASSET_UNAVAILABLE,
    AVAILABLE,
    SPECIALIST_CAPABILITY_UNAVAILABLE,
    SPECIALIST_MODEL_DIRS,
    SPECIALIST_ROUTES,
    capability_report,
    native_core_status,
)

LITE_RUNTIME_SCHEMA = "solve-lite.lite-runtime.v1"
LITE_CASE_RESULT_SCHEMA = "solve-lite.lite-case-result.v1"
#: honesty contract: the LITE build line ships EXACTLY one native route
LITE_NATIVE_CAPABILITIES = ("MARKOV",)
LITE_NATIVE_SUBSET = NATIVE_SUBSET = ("markov",)
SPECIALIST_SUBSET = tuple(SPECIALIST_ROUTES)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _skill_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _optional_asset_root(value: str | Path | None) -> tuple[Path, bool]:
    """LITE: the specialist model pack is OPTIONAL.

    The Full core raised its global asset gate when the five model
    directories were absent, which turned "no specialist pack" into "no Core at
    all".  The LITE line never raises here: it reports whether the optional pack
    is present and falls back to the skill root so that native routes can run.
    """
    candidates = []
    if value:
        candidates.append(Path(value))
    if os.environ.get("SOLVE_LITE_ASSET_ROOT"):
        candidates.append(Path(os.environ["SOLVE_LITE_ASSET_ROOT"]))
    if os.environ.get("SOLVE_LITE_INT4_DLC_ROOT"):
        candidates.append(Path(os.environ["SOLVE_LITE_INT4_DLC_ROOT"]))
    candidates.extend(
        (
            _skill_root() / "assets" / "gatex7a-runtime",
            _skill_root().parent / "solve-lite-runtime-assets" / "gatex7a-runtime",
        )
    )
    for candidate in candidates:
        resolved = candidate.expanduser()
        if any((resolved / item).is_dir() for item in SPECIALIST_MODEL_DIRS):
            # a partial pack is a usable pack: per-route availability decides later
            return resolved.resolve(), all(
                (resolved / item).is_dir() for item in SPECIALIST_MODEL_DIRS
            )
    return _skill_root(), False


def _load_kernel_modules() -> tuple[Any, Any, Any]:
    package = Path(__file__).resolve().parent
    native = package / "_kernel_native"
    if not native.is_dir():
        raise RuntimeError("SOLVE_LITE_KERNEL_UNAVAILABLE")
    value = str(native)
    if value not in sys.path:
        sys.path.insert(0, value)
    generator = importlib.import_module("_slk5")
    calibration = importlib.import_module("_slk6")
    frozen_params = importlib.import_module("_slk7")
    return generator, calibration, frozen_params


def _schema_labels(question: dict[str, Any]) -> list[str]:
    criteria = question["criteria"]
    return list(map(str, criteria.keys() if isinstance(criteria, dict) else criteria))


def _align_answer(answer: dict[str, Any], question: dict[str, Any]) -> dict[str, Any]:
    desired = _schema_labels(question)
    current = list(map(str, answer["support_labels"]))
    support = list(map(float, answer["raw_support"]))
    if set(current) == set(desired):
        by_label = dict(zip(current, support))
        support = [by_label[label] for label in desired]
    elif len(current) != len(desired):
        raise ValueError("adapter support dimension does not match public schema")
    result = dict(answer)
    result["support_labels"] = desired
    result["raw_support"] = support
    result["support_semantics"] = "uncalibrated_relative_support"
    result["display_as_percent"] = False
    return result


def _refuse_gold(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in {"gold", "gold_answer", "answer_key", "expected_answer"}:
                raise ValueError("runtime input may not contain gold or expected answers")
            _refuse_gold(item)
    elif isinstance(value, list):
        for item in value:
            _refuse_gold(item)


class FrozenKernelLite:
    def __init__(
        self,
        asset_root: str | Path | None = None,
        *,
        require_specialist: bool = False,
    ) -> None:
        self.identity = current_identity()
        # startup gate #1 (the only one): verify the bundled native Core bytes.
        self.native_core = native_core_status()
        if self.native_core["status"] != AVAILABLE:
            raise RuntimeError(
                f"{CORE_ASSET_UNAVAILABLE}: {self.native_core['reason']}: {self.native_core['detail']}"
            )
        self.asset_root, self.specialist_pack_present = _optional_asset_root(asset_root)
        self.generator, self.calibration, frozen_params = _load_kernel_modules()
        self.generator.PRIOR_ROOT = self.asset_root
        self.generator.MODELS = self.asset_root / "model-cache"
        # startup gate #2: capability registry.  A missing pack is NOT a Core fault.
        self.capabilities = capability_report(self.native_core, self.asset_root)
        self.specialist_available = self.capabilities["specialist"]["status"] == AVAILABLE
        if require_specialist and not self.specialist_available:
            raise RuntimeError(
                f"{SPECIALIST_CAPABILITY_UNAVAILABLE}: "
                f"{self.capabilities['specialist']['reason']}"
            )
        self.params_sha256 = str(frozen_params.PARAMS_SHA256)
        self.params = frozen_params.load()
        self.routers = {
            family: self.calibration.P95TailRouter.from_dict(value)
            for family, value in self.params["tail_routers"].items()
        }
        self.curves = {}
        for family, tiers in self.params["fit_groups"].items():
            for tier, values in tiers.items():
                candidate = self.params["selected_candidates"][tier]
                self.curves[(family, tier)] = self.calibration.curve(
                    candidate, values["knots"], values["knot_probabilities"]
                )
        certificate = self.params["independent_confidence_certificate"]
        self.risk_quantiles = certificate["risk_quantiles"]
        self.selected_policies = certificate["selected_policies"]
        self.semantic_banks = {
            family: self.calibration.pbank.from_dict(value)
            for family, value in certificate["pbank_map"].items()
        }

    def _tier_distributions(self, family: str, support: list[float]) -> dict[str, list[float]]:
        return {
            tier: self.calibration.calibrated_distribution(
                support,
                self.params["fit_groups"][family][tier]["scale"],
                self.curves[(family, tier)],
            )
            for tier in ("L1", "L2", "L3")
        }

    def _calibrate_answer(
        self,
        family: str,
        question: dict[str, Any],
        original: dict[str, Any],
    ) -> dict[str, Any]:
        support = list(map(float, original["raw_support"]))
        labels = list(map(str, original["support_labels"]))
        guard = self.routers[family].guard_decision(support)
        win = self.calibration.winner(support)
        distributions = self._tier_distributions(family, support)
        features = self.calibration.independent_features(
            family, original, win, distributions, self.semantic_banks
        )
        baseline_l1_confidence = max(distributions["L1"]) if guard["base_route"] == "L1" else None
        quantiles = self.risk_quantiles[family]
        tier = str(guard["route"])
        continuity_floor = (
            quantiles["p95"] if tier == "L3" else quantiles["p70"] if tier == "L2" else 0.0
        )
        baseline_certificate = self.calibration.final_certificate(
            base_risk=self.routers[family].risk(support),
            continuity_risk_floor=continuity_floor,
            risk_quantiles=quantiles,
            distributions=distributions,
            frozen_winner=win,
            evidence={},
            certified_confidence_ceiling=features.get("semantic_certified_confidence_ceiling"),
        )
        matched_policies = []
        if guard["route"] in {"L1", "L2"} and max(baseline_certificate["probabilities"]) >= 0.90:
            for policy in self.selected_policies:
                if policy["family"] != family:
                    continue
                if guard["route"] == "L2" and policy["floor_tier"] != "L3":
                    continue
                triggered, _ = self.calibration.feature_policy_trigger(features, [policy])
                if triggered:
                    matched_policies.append(policy)
        if matched_policies:
            tier = "L3" if any(row["floor_tier"] == "L3" for row in matched_policies) else "L2"
            continuity_floor = max(
                continuity_floor, quantiles["p95"] if tier == "L3" else quantiles["p70"]
            )
        certificate = self.calibration.final_certificate(
            base_risk=self.routers[family].risk(support),
            continuity_risk_floor=continuity_floor,
            risk_quantiles=quantiles,
            distributions=distributions,
            frozen_winner=win,
            evidence={
                "features": features,
                "triggered_axes": sorted({row["feature"] for row in matched_policies}),
            },
            certified_confidence_ceiling=features.get("semantic_certified_confidence_ceiling"),
        )
        probabilities = certificate["probabilities"]
        if self.calibration.winner(probabilities) != win:
            raise AssertionError("BLEND_ARGMAX_DIFF")
        value: Any = labels[win]
        if question["type"] == "score":
            value = win
        elif question["type"] == "noul":
            value = value == "true"
        combined_guard = dict(
            guard,
            route=tier,
            guard_triggered=tier != guard["base_route"],
            guard_level=(
                "strong"
                if tier == "L3" and tier != guard["base_route"]
                else "suspicious"
                if tier == "L2" and tier != guard["base_route"]
                else guard["guard_level"]
            ),
            independent_certificate_triggered=bool(matched_policies),
            independent_certificate_axes=sorted({row["feature"] for row in matched_policies}),
            counterfactual_baseline_l1_confidence=baseline_l1_confidence,
            counterfactual_display_as_percent=False,
        )
        return {
            "type": question["type"],
            "value": value,
            "support_labels": labels,
            "raw_support": support,
            "support_semantics": "uncalibrated_relative_support",
            "display_as_percent": False,
            "probabilities": dict(zip(labels, probabilities)),
            "confidence": {
                "type": "calibrated_probability",
                "value": max(probabilities),
                "calibration_evidence_ref": "FROZEN_CALIBRATION_ASSET_V1",
                "display_as_percent": True,
            },
            "adapter_route": f"{tier}_CONTINUOUS_CERTIFICATE_V1",
            "l1_guard": combined_guard,
            "final_certificate": certificate,
        }

    def solve_cases(self, cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
        groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for case in cases:
            _refuse_gold(case)
            required = {"case_id", "family", "state", "questions"}
            missing = sorted(required - set(case))
            if missing:
                raise ValueError(f"case missing fields: {missing}")
            groups[self.generator.route_case(case)].append(case)
        # --- LITE delta (runtime): no global 5-model gate. Per-route capability only.
        # A case whose route needs a pack that is absent (or a backend that is not
        # active) is answered with SPECIALIST_CAPABILITY_UNAVAILABLE; it is NEVER
        # silently answered by a substitute or a hand-computed value.
        route_details = (self.capabilities.get("specialist") or {}).get("route_details") or {}
        specialist_missing = [
            route
            for route in SPECIALIST_SUBSET
            if groups.get(route)
            and (route_details.get(route) or {}).get("status") != AVAILABLE
        ]
        raw_rows: dict[str, dict[str, Any]] = {}
        route_hashes: dict[str, dict[str, str]] = {}
        for route in ("financial", "topic", "review", "nli", "markov"):
            selected = groups.get(route, [])
            if not selected or route in specialist_missing:
                continue
            values, _, hashes = self.generator.PROCESSORS[route](selected)
            raw_rows.update(values)
            route_hashes[route] = hashes
        output = []
        for case in cases:
            route = self.generator.route_case(case)
            if route in specialist_missing:
                output.append(self._specialist_unavailable(case, route))
                continue
            raw = raw_rows[case["case_id"]]
            raw["answers"] = {
                qid: _align_answer(raw["answers"][qid], case["questions"][qid])
                for qid in case["questions"]
            }
            started = time.perf_counter_ns()
            answers = {
                qid: self._calibrate_answer(case["family"], question, raw["answers"][qid])
                for qid, question in case["questions"].items()
            }
            calibration_ms = (time.perf_counter_ns() - started) / 1_000_000.0
            output.append(
                {
                    "schema_version": "solve-lite.frozen-case-result.v1",
                    "status": "PASS",
                    "case_id": case["case_id"],
                    "family": case["family"],
                    "answers": answers,
                    "adapter_route": route,
                    "adapter_inference_latency_ms": raw.get("latency_ms"),
                    "calibration_latency_ms": calibration_ms,
                    "network_model_calls": 0,
                    "credential_reads": 0,
                    "jev_api_calls": 0,
                    "runtime_identity": {
                        "build_id": self.identity["build_id"],
                        "kernel": "FROZEN_GATEX7B_CONTINUOUS_CERTIFICATE_V1",
                        "params_sha256": self.params_sha256,
                        "asset_root_id": _sha256_bytes(str(self.asset_root).encode("utf-8"))[:16],
                        "model_hashes": route_hashes[route],
                    },
                }
            )
        return output

    def _specialist_unavailable(self, case: dict[str, Any], route: str) -> dict[str, Any]:
        """Structured refusal.  No arithmetic, no fallback, no fabricated support."""
        specialist = self.capabilities["specialist"]
        detail = (specialist.get("route_details") or {}).get(route) or {}
        return {
            "schema_version": LITE_CASE_RESULT_SCHEMA,
            "status": SPECIALIST_CAPABILITY_UNAVAILABLE,
            "case_id": case["case_id"],
            "family": case["family"],
            "answers": {},
            "adapter_route": route,
            "requested_capability": "specialist",
            "capability_status": specialist["status"],
            "capability_reason": detail.get("reason") or specialist["reason"],
            "missing_model_directories": list(
                detail.get("missing_model_directories") or specialist["missing_model_directories"]
            ),
            "missing_python_modules": list(
                detail.get("missing_python_modules") or specialist["missing_python_modules"]
            ),
            "int4_backend_activated": bool(detail.get("int4_backend_activated")),
            "native_alternative": {
                "available": False,
                "reason": "NO_NATIVE_ROUTE_FOR_FAMILY",
                "native_capabilities": list(LITE_NATIVE_CAPABILITIES),
            },
            "fallback_computation": False,
            "network_model_calls": 0,
            "credential_reads": 0,
            "jev_api_calls": 0,
            "runtime_identity": {
                "build_id": self.identity["build_id"],
                "kernel": "FROZEN_GATEX7B_CONTINUOUS_CERTIFICATE_V1",
                "params_sha256": self.params_sha256,
                "asset_root_id": _sha256_bytes(str(self.asset_root).encode("utf-8"))[:16],
                "model_hashes": {},
            },
        }

    def solve_case(self, case: dict[str, Any]) -> dict[str, Any]:
        return self.solve_cases([case])[0]


def _capability_settlement(result: dict[str, Any], locale: str) -> str:
    """User-visible settlement for a capability refusal (never a fake answer)."""
    reason = result.get("capability_reason", "MODEL_PACK_MISSING")
    if str(locale).lower().startswith("zh"):
        return (
            "本机缺少 specialist 模型包，相关能力当前不可用"
            f"（{reason}）。native 路由可用，已零下载、零联网。"
        )
    return (
        "Specialist model pack is not installed on this host, so this route is "
        f"unavailable ({reason}). Native routes remain available; nothing was "
        "downloaded and no network call was made."
    )


def run_frozen_case_lite(
    workspace: str | Path,
    case: dict[str, Any],
    *,
    asset_root: str | Path | None = None,
    namespace: str = "production",
    invocation_id: str | None = None,
    locale: str = "en-US",
) -> dict[str, Any]:
    started = start_local_timer()
    invocation = invocation_id or f"inv_{uuid.uuid4().hex}"
    trace_id = "trace_" + _sha256_bytes(
        (invocation + "\0" + canonical_json(case)).encode("utf-8")
    )[:24]
    runtime_started = time.perf_counter_ns()
    runtime = FrozenKernelLite(asset_root)
    runtime_init_ns = time.perf_counter_ns() - runtime_started
    kernel_started = time.perf_counter_ns()
    result = runtime.solve_case(case)
    kernel_ns = time.perf_counter_ns() - kernel_started
    result["trace_id"] = trace_id
    result["invocation_id"] = invocation
    build_id = str(current_identity()["build_id"])
    reward_started = time.perf_counter_ns()
    attach_reward(
        workspace_root(workspace),
        result,
        operation="frozen_decide",
        namespace=namespace,
        elapsed_ns=local_elapsed_ns(started),
        quality_gate_pass=result["status"] == "PASS",
        quality_gate_reason=result["status"],
        local_decisions=len(result.get("answers") or {}),
        locale=locale,
        invocation_id=invocation,
        trace_id=trace_id,
        build_id=build_id,
    )
    reward_commit_ns = time.perf_counter_ns() - reward_started
    render_started = time.perf_counter_ns()
    from ..presentation import render_settlement

    result["user_visible_settlement"] = (
        render_settlement(result, locale)
        if result["status"] == "PASS"
        else _capability_settlement(result, locale)
    )
    result["reward_transaction"].update(
        {
            "operation_status": result["reward_transaction"]["operation_status"],
            "user_visible_settlement": result["user_visible_settlement"],
        }
    )
    render_ns = time.perf_counter_ns() - render_started
    result["performance"] = {
        "clock": "time.perf_counter_ns",
        "runtime_init_ms": runtime_init_ns / 1_000_000.0,
        "kernel_and_adapter_ms": kernel_ns / 1_000_000.0,
        "adapter_reported_ms": result.get("adapter_inference_latency_ms"),
        "calibration_reported_ms": result.get("calibration_latency_ms"),
        "reward_commit_ms": reward_commit_ns / 1_000_000.0,
        "receipt_render_ms": render_ns / 1_000_000.0,
        "local_e2e_ms": local_elapsed_ns(started) / 1_000_000.0,
        "host_visible_ms": None,
        "host_visible_status": "NOT_MEASURED",
    }
    return result
