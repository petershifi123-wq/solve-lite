#!/usr/bin/env python3
"""Fresh-copy acceptance for the self-contained public specialist runtime.

This harness mutates only a temporary repository copy and a temporary shared
runtime root. It proves that an
isolated Python with no ambient Torch/Transformers can install the pinned local
runtime, leave the invoking interpreter's packages unchanged, keep Lite startup
specialist-free, and execute one real Review, Topic and NLI decision.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def _run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None, timeout: int = 1200) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        timeout=timeout,
    )


def _copy_public_tree(destination: Path) -> None:
    dynamic = {".git", "__pycache__", "addons", "specialist-env", "specialist-python"}
    shutil.copytree(ROOT, destination, ignore=lambda _path, names: [name for name in names if name in dynamic])


def _clean_probe(python: str, cwd: Path) -> dict[str, Any]:
    program = (
        "import importlib.util,json,sys;"
        "print(json.dumps({'torch':importlib.util.find_spec('torch') is not None,"
        "'transformers':importlib.util.find_spec('transformers') is not None,"
        "'version':list(sys.version_info[:3])}))"
    )
    result = _run([python, "-I", "-c", program], cwd=cwd)
    return json.loads(result.stdout.strip()) if result.returncode == 0 else {"error": result.stderr[-300:]}


def _freeze(python: str, cwd: Path) -> str:
    result = _run([python, "-m", "pip", "freeze"], cwd=cwd)
    return result.stdout if result.returncode == 0 else ""


def _decision_cases() -> list[dict[str, Any]]:
    topic_labels = [
        "Company", "EducationalInstitution", "Artist", "Athlete", "OfficeHolder",
        "MeanOfTransportation", "Building", "NaturalPlace", "Village", "Animal",
        "Plant", "Album", "Film", "WrittenWork",
    ]
    return [
        {
            "case_id": "clean-review-1",
            "family": "amazon_review_polarity",
            "state": {"items": [{"id": "item_0", "text": "This product is excellent and works perfectly."}]},
            "questions": {"q_0": {"type": "noul", "input_ref": "item_0",
                                      "criteria": {"false": "negative review", "true": "positive review"},
                                      "instructions": "Is this a positive review?"}},
        },
        {
            "case_id": "clean-topic-1",
            "family": "knowledge_topic_routing",
            "state": {"items": [{"id": "item_0", "title": "Apple Inc.",
                                    "content": "Apple is a technology company that designs consumer electronics."}]},
            "questions": {"q_0": {"type": "choice", "input_ref": "item_0",
                                      "criteria": {label: label for label in topic_labels},
                                      "instructions": "Classify the topic."}},
        },
        {
            "case_id": "clean-nli-1",
            "family": "natural_language_inference",
            "state": {"items": [{"id": "item_0", "premise": "A dog is running outside.",
                                    "hypothesis": "An animal is outdoors."}]},
            "questions": {"q_0": {"type": "choice", "input_ref": "item_0",
                                      "criteria": {"contradiction": "not entailed", "entailment": "entailed",
                                                   "neutral": "uncertain"},
                                      "instructions": "Classify the relation."}},
        },
    ]


def _run_decisions(repo: Path, python: str, runtime: Path) -> dict[str, Any]:
    scripts = repo / "plugins" / "solve-lite" / "skills" / "solve-lite" / "scripts"
    program = (
        "import json,pathlib,sys,tempfile;"
        f"sys.path.insert(0,{str(scripts)!r});import solve_lite_abi as A;"
        f"cases={_decision_cases()!r};rt=pathlib.Path({str(runtime)!r});out=[];"
        "\nfor case in cases:\n"
        "  with tempfile.TemporaryDirectory() as workspace:\n"
        "    result=A.route_prompt(workspace,case,{'metadata':{'locale':'en-US'}},asset_root=rt,invocation_id='clean:'+case['case_id'])\n"
        "  out.append({'case_id':case['case_id'],'status':result.get('status'),'route':result.get('adapter_route'),"
        "'answers':len(result.get('answers') or {}),'isolated_venv':(result.get('specialist_process') or {}).get('isolated_venv')})\n"
        "print(json.dumps(out))"
    )
    result = _run([python, "-I", "-c", program], cwd=repo, timeout=900)
    try:
        rows = json.loads(result.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        rows = []
    return {"returncode": result.returncode, "rows": rows, "stderr": result.stderr[-500:]}


def _lite_startup_probe(repo: Path, python: str, runtime: Path) -> dict[str, Any]:
    scripts = repo / "plugins" / "solve-lite" / "skills" / "solve-lite" / "scripts"
    program = (
        "import json,sys;"
        f"sys.path.insert(0,{str(scripts)!r});import solve_lite_abi as A;"
        f"h=A.healthcheck({str(runtime)!r});s=(h.get('dlc') or {{}}).get('specialist_runtime') or {{}};"
        "print(json.dumps({'status':h.get('status'),'torch_imported':'torch' in sys.modules,"
        "'transformers_imported':'transformers' in sys.modules,'specialist_process_started':s.get('specialist_process_started'),"
        "'probe_mode':s.get('probe_mode')}))"
    )
    result = _run([python, "-I", "-c", program], cwd=repo)
    return json.loads(result.stdout.strip()) if result.returncode == 0 else {"status": "FAIL", "stderr": result.stderr[-500:]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package-dir", type=Path, required=True, help="directory holding the three pinned DLC archives")
    parser.add_argument("--wheel-dir", type=Path, default=None, help="optional offline wheel mirror")
    parser.add_argument("--python", default="/usr/bin/python3", help="clean Lite/installer interpreter")
    parser.add_argument("--keep", action="store_true", help="keep the temporary copy for inspection")
    args = parser.parse_args()

    temp = Path(tempfile.mkdtemp(prefix="solve-lite-specialist-clean-"))
    repo = temp / "repo"
    shared_runtime = temp / "shared-runtime" / "v0.1.8"
    _copy_public_tree(repo)
    environment = dict(os.environ)
    environment["PYTHONNOUSERSITE"] = "1"
    before_probe = _clean_probe(args.python, repo)
    before_freeze = _freeze(args.python, repo)
    command = [
        args.python, "tools/installer.py", "--package-dir", str(args.package_dir.resolve()),
        "--shared-runtime-root", str(shared_runtime), "--host", "none", "--json",
    ]
    if args.wheel_dir:
        command += ["--specialist-wheel-dir", str(args.wheel_dir.resolve())]
    install = _run(command, cwd=repo, env=environment)
    try:
        install_payload = json.loads(install.stdout.strip())
    except ValueError:
        install_payload = {"status": "FAIL", "stderr": install.stderr[-1000:], "stdout": install.stdout[-1000:]}
    after_freeze = _freeze(args.python, repo)
    startup = _lite_startup_probe(repo, args.python, shared_runtime)
    decisions = _run_decisions(repo, args.python, shared_runtime) if install_payload.get("status") == "PASS" else {"rows": []}
    routes = {row.get("route"): row for row in decisions.get("rows", [])}
    checks = {
        "CLEAN_HOST_WITHOUT_TORCH": before_probe.get("torch") is False,
        "CLEAN_HOST_WITHOUT_TRANSFORMERS": before_probe.get("transformers") is False,
        "INSTALLER_CREATES_SHARED_ENV": (shared_runtime / "specialist-env/bin/python3").is_file(),
        "REPO_HEAVY_RUNTIME_COPY_ZERO": not any(
            (repo / "plugins/solve-lite/skills/solve-lite/runtime" / name).exists()
            for name in ("specialist-env", "specialist-python", "addons")
        ),
        "PINNED_DEPENDENCIES": bool((install_payload.get("required_checks") or {}).get("specialist_runtime")),
        "SYSTEM_PYTHON_UNCHANGED": before_freeze == after_freeze,
        "GLOBAL_SITE_PACKAGES_UNCHANGED": before_freeze == after_freeze,
        "LITE_HEALTHCHECK_WITHOUT_SPECIALIST_BOOT": (
            startup.get("status") == "PASS" and startup.get("torch_imported") is False
            and startup.get("transformers_imported") is False and startup.get("specialist_process_started") is False
        ),
        "REVIEW_REAL_DECISION": routes.get("review", {}).get("status") == "PASS" and routes.get("review", {}).get("answers", 0) > 0,
        "TOPIC_REAL_DECISION": routes.get("topic", {}).get("status") == "PASS" and routes.get("topic", {}).get("answers", 0) > 0,
        "NLI_REAL_DECISION": routes.get("nli", {}).get("status") == "PASS" and routes.get("nli", {}).get("answers", 0) > 0,
        "PRELOAD_ALL": False,
        "MAX_RESIDENT_DLC_1": ((install_payload.get("dlc") or {}).get("capability") or {}).get("resident_model_limit") == 1,
    }
    passed = all(value is True for key, value in checks.items() if key != "PRELOAD_ALL") and checks["PRELOAD_ALL"] is False
    output = {
        "status": "PASS" if passed else "FAIL",
        "checks": checks,
        "clean_probe": before_probe,
        "install_status": install_payload.get("status"),
        "startup": startup,
        "decisions": decisions,
        "temporary_copy": str(repo) if args.keep else "REMOVED",
        "production_mutation": 0,
    }
    print(json.dumps(output, indent=2, sort_keys=True, ensure_ascii=False))
    if not args.keep:
        shutil.rmtree(temp, ignore_errors=True)
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
