#!/usr/bin/env python3
"""Standalone HydroWeaver scientific CLI engine.

Coordinates knowledge-informed configuration generation, numerical operating-parameter
optimization, mechanistic and economic process simulation, violation diagnosis,
structural-vs-parametric routing, shared design history, and AquaDesignGym evaluation.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib.metadata
import json
import math
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

ADAPTER_VERSION = "0.3.0-beta.1"
CALLER_CWD = Path.cwd()
PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from aquadesigngym.baselines import METHOD_REGISTRY  # noqa: E402
from aquadesigngym.env import AquaDesignGymEnv  # noqa: E402
from aquadesigngym.evaluate import evaluate_benchmark  # noqa: E402
from aquadesigngym.tasks import PERTURBATION_PROFILES, list_tasks  # noqa: E402
from hydroweaver_py.diagnosis import diagnose_simulation  # noqa: E402
from hydroweaver_py.harness import (  # noqa: E402
    build_recommendation_report,
    run_closed_loop_optimization,
)
from hydroweaver_py.knowledge import (  # noqa: E402
    CANONICAL_UNITS,
    CONTAMINANT_SPECS,
    TEMPLATE_PRIORS,
    UNIT_SPECS,
    build_case_assessment,
    canonicalize_chain,
    kb_corpus_chunks,
    retrieve_evidence,
    validate_and_normalize_query,
)
from hydroweaver_py.simulator import simulate_train  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="HydroWeaver standalone scientific CLI engine")
    parser.add_argument("--version", action="store_true", help="Print engine version identity")
    subparsers = parser.add_subparsers(dest="command")

    health = subparsers.add_parser("health", help="Inspect HydroWeaver scientific runtime readiness")
    health.add_argument("--json", action="store_true", help=argparse.SUPPRESS)

    subparsers.add_parser("identity", help="Report non-secret scientific engine configuration")

    catalog = subparsers.add_parser("catalog", help="List contaminants, treatment units, and parameter bounds")
    catalog.add_argument("--kind", choices=("all", "contaminants", "units"), default="all")
    catalog.add_argument("--search", default="")
    catalog.add_argument("--limit", type=int, default=100)

    normalize = subparsers.add_parser("normalize", help="Normalize a HydroWeaver query")
    add_query_arguments(normalize)
    normalize.add_argument("--output")

    assess = subparsers.add_parser("assess-case", help="Build structured case state and readiness audit")
    add_query_arguments(assess)
    assess.add_argument("--output")

    retrieve = subparsers.add_parser("retrieve", help="Retrieve unit and template priors for a query")
    add_query_arguments(retrieve)
    retrieve.add_argument("--output")

    recommend = subparsers.add_parser("recommend", help="Generate evidence-bound optimized recommendations")
    add_query_arguments(recommend)
    recommend.add_argument("--top-k", type=int, default=3)
    recommend.add_argument("--max-rounds", type=int, default=4)
    recommend.add_argument("--output")

    critic = subparsers.add_parser("check-constraints", help="Simulate and diagnose candidate treatment trains")
    add_query_arguments(critic)
    critic_source = critic.add_mutually_exclusive_group(required=True)
    critic_source.add_argument("--candidates-json")
    critic_source.add_argument("--candidates-file")
    critic.add_argument("--output")

    optimize = subparsers.add_parser(
        "optimize",
        help="Run joint configuration & operating-parameter closed-loop optimization with diagnosis routing",
    )
    add_query_arguments(optimize)
    optimize.add_argument("--top-k", type=int, default=3)
    optimize.add_argument("--max-rounds", type=int, default=4)
    optimize.add_argument("--max-sim-calls", type=int, default=60)
    optimize_source = optimize.add_mutually_exclusive_group(required=False)
    optimize_source.add_argument("--candidates-json")
    optimize_source.add_argument("--candidates-file")
    optimize.add_argument("--output")

    sim_cmd = subparsers.add_parser("simulate", help="Simulate a single train configuration and parameters")
    add_query_arguments(sim_cmd)
    chain_src = sim_cmd.add_mutually_exclusive_group(required=True)
    chain_src.add_argument("--chain-json")
    chain_src.add_argument("--chain-file")
    params_src = sim_cmd.add_mutually_exclusive_group(required=False)
    params_src.add_argument("--params-json")
    params_src.add_argument("--params-file")
    sim_cmd.add_argument("--output")

    indexes = subparsers.add_parser("build-indexes", help="Rebuild local HydroWeaver knowledge corpus index")
    indexes.add_argument("--output")

    ingest = subparsers.add_parser("ingest", help="Stage a local knowledge record and optionally rebuild index")
    ingest.add_argument("--kb-type", choices=("kb-unit", "kb-case", "kb_unit", "kb_case"), required=True)
    ingest.add_argument("--data-file", required=True)
    ingest.add_argument("--rebuild", action=argparse.BooleanOptionalAction, default=True)
    ingest.add_argument("--output")

    audit = subparsers.add_parser("audit-report", help="Build structural claim-evidence ledger from a report")
    audit.add_argument("--report-file", required=True)
    audit.add_argument("--output")

    gym_tasks = subparsers.add_parser("gym-tasks", help="List AquaDesignGym tasks, actions, and methods")
    gym_tasks.add_argument("--output")

    gym_eval = subparsers.add_parser(
        "gym-eval",
        help="Run AquaDesignGym matched-budget benchmark, ablations, and varying-influent robustness evaluation",
    )
    gym_eval.add_argument("--methods", default="")
    gym_eval.add_argument("--tasks", default="")
    gym_eval.add_argument("--perturbations", default="nominal,mild_shift,severe_shift")
    gym_eval.add_argument("--max-sim-calls", type=int, default=60)
    gym_eval.add_argument("--seed", type=int, default=42)
    gym_eval.add_argument("--output")

    return parser


def add_query_arguments(parser: argparse.ArgumentParser) -> None:
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--query-json")
    source.add_argument("--query-file")


def resolve_external_path(raw: str) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = CALLER_CWD / path
    return path.resolve()


def _home_dir() -> Path:
    raw = os.environ.get("HYDROWEAVER_HOME", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.home() / ".hydroweaver").resolve()


def _kb_dirs() -> tuple[Path, Path]:
    home = _home_dir()
    return home / "ingest", home / "indexes"


def _load_staged_records() -> list[dict[str, Any]]:
    ingest_dir, _ = _kb_dirs()
    if not ingest_dir.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(ingest_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                records.append(data)
        except Exception:
            continue
    return records


def load_json_source(json_text: str | None, file_name: str | None, label: str) -> Any:
    if json_text is not None:
        return json.loads(json_text)
    if file_name is None:
        raise ValueError(f"{label} source is required")
    path = resolve_external_path(file_name)
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def json_safe_value(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return str(value).replace("nan", "NaN").replace("inf", "Infinity")
    if isinstance(value, dict):
        return {key: json_safe_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe_value(item) for item in value]
    return value


def write_json_file(payload: Any, output: str) -> None:
    rendered = json.dumps(json_safe_value(payload), ensure_ascii=False, indent=2, sort_keys=False, allow_nan=False)
    target = resolve_external_path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(rendered)
            handle.write("\n")
        os.replace(temporary_name, target)
    except Exception:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def emit(payload: Any, output: str | None = None) -> None:
    if output:
        write_json_file(payload, output)
    print(json.dumps(json_safe_value(payload), ensure_ascii=False, indent=2, sort_keys=False, allow_nan=False))


def dependency_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def load_user_query(args: argparse.Namespace) -> dict[str, Any]:
    value = load_json_source(args.query_json, args.query_file, "query")
    if not isinstance(value, dict):
        raise ValueError("query must be a JSON object")
    return value


def command_health() -> dict[str, Any]:
    ingest_dir, index_dir = _kb_dirs()
    corpus_file = index_dir / "corpus.jsonl"
    staged = _load_staged_records()
    builtin_chunks = len(kb_corpus_chunks())
    chunk_count = builtin_chunks + len(staged)
    if corpus_file.is_file():
        with corpus_file.open("r", encoding="utf-8") as handle:
            chunk_count = sum(1 for _ in handle)
    return {
        "ok": True,
        "ready_for_recommendation": True,
        "ready_for_optimization": True,
        "ready_for_evaluation": True,
        "adapter_version": ADAPTER_VERSION,
        "engine_mode": "standalone-hydroweaver",
        "python": sys.version.split()[0],
        "optional_packages": {
            "numpy": dependency_version("numpy"),
            "scipy": dependency_version("scipy"),
        },
        "knowledge_base": {
            "units": len(UNIT_SPECS),
            "contaminants": len(CONTAMINANT_SPECS),
            "templates": len(TEMPLATE_PRIORS),
            "staged_records": len(staged),
            "chunk_count": chunk_count,
            "ingest_dir": str(ingest_dir),
            "index_dir": str(index_dir),
        },
        "aquadesigngym": {
            "tasks": len(list_tasks()),
            "methods": len(METHOD_REGISTRY),
            "perturbations": list(PERTURBATION_PROFILES.keys()),
        },
    }


def command_identity() -> dict[str, Any]:
    return {
        "adapter_version": ADAPTER_VERSION,
        "engine_mode": "standalone-hydroweaver",
        "python": sys.version.split()[0],
        "knowledge": {
            "units": len(UNIT_SPECS),
            "contaminants": len(CONTAMINANT_SPECS),
            "templates": len(TEMPLATE_PRIORS),
        },
        "optimization": {
            "joint_config_and_params": True,
            "parameter_optimizer": "bounded-hooke-jeeves-pattern-search",
            "diagnosis_router": "simulation-feedback-structural-vs-parametric",
            "shared_design_history": True,
        },
        "aquadesigngym": {
            "tasks": len(list_tasks()),
            "methods": list(METHOD_REGISTRY.keys()),
        },
    }


def command_catalog(args: argparse.Namespace) -> dict[str, Any]:
    search = args.search.strip().lower()
    limit = max(1, min(args.limit, 1000))

    def filtered(values: list[str]) -> list[str]:
        matching = [value for value in values if search in value.lower()] if search else values
        return matching[:limit]

    payload: dict[str, Any] = {"search": args.search, "limit": limit}
    if args.kind in ("all", "contaminants"):
        contaminants = filtered(sorted(CONTAMINANT_SPECS.keys()))
        payload["contaminants"] = contaminants
        payload["contaminants_returned"] = len(contaminants)
    if args.kind in ("all", "units"):
        units = filtered(list(CANONICAL_UNITS))
        payload["treatment_units"] = units
        payload["treatment_units_returned"] = len(units)
        payload["unit_details"] = [
            {
                "unit": u,
                "stage": UNIT_SPECS[u].stage,
                "mechanisms": list(UNIT_SPECS[u].mechanisms),
                "target_contaminants": list(UNIT_SPECS[u].target_contaminants),
                "generates_brine": UNIT_SPECS[u].generates_brine,
                "requires_chemical_dosing": UNIT_SPECS[u].requires_chemical_dosing,
                "parameters": [
                    {
                        "name": p.name,
                        "unit": p.unit,
                        "lower": p.lower,
                        "upper": p.upper,
                        "default": p.default,
                    }
                    for p in UNIT_SPECS[u].params
                ],
            }
            for u in units
        ]
    return payload


def command_normalize(args: argparse.Namespace) -> dict[str, Any]:
    query = load_user_query(args)
    normalized, preservation = validate_and_normalize_query(query)
    return {"normalized_query": normalized, "context_preservation": preservation}


def command_assess_case(args: argparse.Namespace) -> dict[str, Any]:
    query = load_user_query(args)
    normalized, preservation = validate_and_normalize_query(query)
    return {
        "normalized_query": normalized,
        "context_preservation": preservation,
        **build_case_assessment(normalized),
    }


def command_retrieve(args: argparse.Namespace) -> dict[str, Any]:
    query = load_user_query(args)
    normalized, preservation = validate_and_normalize_query(query)
    retrieval = retrieve_evidence(normalized, extra_records=_load_staged_records())
    return {
        "normalized_query": normalized,
        "context_preservation": preservation,
        "retrieval": retrieval,
    }


def command_recommend(args: argparse.Namespace) -> dict[str, Any]:
    if not 1 <= args.top_k <= 10:
        raise ValueError("top-k must be between 1 and 10")
    query = load_user_query(args)
    return build_recommendation_report(query, top_k=args.top_k, max_rounds=max(1, min(args.max_rounds, 8)))


def _parse_candidates_raw(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, dict) and isinstance(raw.get("candidates"), list):
        raw = raw["candidates"]
    if not isinstance(raw, list) or not raw:
        raise ValueError("candidates must be a non-empty JSON array")
    parsed: list[dict[str, Any]] = []
    for idx, item in enumerate(raw, start=1):
        if isinstance(item, list):
            item = {"chain": item}
        if not isinstance(item, dict):
            raise ValueError(f"candidate {idx} must be an object or a list of unit names")
        chain = item.get("chain") or item.get("process_chain")
        if not isinstance(chain, list) or not chain or not all(isinstance(u, str) for u in chain):
            raise ValueError(f"candidate {idx} requires a non-empty string array named chain")
        parsed.append(
            {
                "chain_id": str(item.get("chain_id") or f"candidate_{idx}"),
                "chain": [u.strip() for u in chain if u.strip()],
                "parameters": item.get("parameters"),
                "rationale": str(item.get("rationale") or "Caller-supplied candidate train"),
            }
        )
    return parsed


def command_check_constraints(args: argparse.Namespace) -> dict[str, Any]:
    query = load_user_query(args)
    normalized, preservation = validate_and_normalize_query(query)
    raw_cands = load_json_source(args.candidates_json, args.candidates_file, "candidates")
    candidates = _parse_candidates_raw(raw_cands)

    chain_reports: list[dict[str, Any]] = []
    revised_candidates: list[dict[str, Any]] = []
    for cand in candidates:
        sim = simulate_train(normalized, cand["chain"], cand.get("parameters"))
        diag = diagnose_simulation(normalized, sim, params_already_optimized=False)
        chain_reports.append(
            {
                "chain_id": cand["chain_id"],
                "chain": sim["chain"],
                "overall_status": sim["overall_status"],
                "feasible": sim["feasible"],
                "lcow_usd_m3": sim["economics"]["lcow_usd_m3"],
                "specific_energy_kWh_m3": sim["flowsheet"]["specific_energy_kWh_m3"],
                "recovery_fraction": sim["flowsheet"]["recovery_fraction"],
                "violations": sim["violations"],
                "diagnosis": diag,
            }
        )
        revised_candidates.append(
            {
                "chain_id": cand["chain_id"],
                "chain": sim["chain"],
                "parameters": sim["parameters"],
                "economics": sim["economics"],
                "flowsheet": sim["flowsheet"],
            }
        )
    return {
        "normalized_query": normalized,
        "context_preservation": preservation,
        "candidates_after_revision": {"query_id": normalized["query_id"], "candidates": revised_candidates},
        "constraint_report": {"chain_reports": chain_reports},
    }


def command_optimize(args: argparse.Namespace) -> dict[str, Any]:
    if not 1 <= args.max_rounds <= 12:
        raise ValueError("max-rounds must be between 1 and 12")
    if not 1 <= args.max_sim_calls <= 500:
        raise ValueError("max-sim-calls must be between 1 and 500")
    query = load_user_query(args)
    initial_cands = None
    if args.candidates_json is not None or args.candidates_file is not None:
        initial_cands = _parse_candidates_raw(
            load_json_source(args.candidates_json, args.candidates_file, "candidates")
        )
    return run_closed_loop_optimization(
        query,
        initial_candidates=initial_cands,
        top_k=args.top_k,
        max_rounds=args.max_rounds,
        max_sim_calls=args.max_sim_calls,
    )


def command_simulate(args: argparse.Namespace) -> dict[str, Any]:
    query = load_user_query(args)
    normalized, preservation = validate_and_normalize_query(query)
    raw_chain = load_json_source(args.chain_json, args.chain_file, "chain")
    if not isinstance(raw_chain, list) or not raw_chain or not all(isinstance(u, str) for u in raw_chain):
        raise ValueError("chain must be a non-empty JSON string array")
    params = None
    if args.params_json is not None or args.params_file is not None:
        raw_params = load_json_source(args.params_json, args.params_file, "params")
        if not isinstance(raw_params, dict):
            raise ValueError("params must be a JSON object")
        params = raw_params
    sim = simulate_train(normalized, raw_chain, params)
    diag = diagnose_simulation(normalized, sim, params_already_optimized=False)
    return {
        "normalized_query": normalized,
        "context_preservation": preservation,
        **sim,
        "diagnosis": diag,
    }


def command_build_indexes() -> dict[str, Any]:
    ingest_dir, index_dir = _kb_dirs()
    index_dir.mkdir(parents=True, exist_ok=True)
    chunks = kb_corpus_chunks()
    for idx, rec in enumerate(_load_staged_records(), start=1):
        chunks.append(
            {
                "id": str(rec.get("id") or rec.get("case_id") or f"staged-{idx}"),
                "kind": str(rec.get("kb_type") or "staged"),
                "data": rec,
            }
        )
    corpus_path = index_dir / "corpus.jsonl"
    tmp_fd, tmp_name = tempfile.mkstemp(prefix=".corpus.", suffix=".tmp", dir=index_dir)
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as handle:
            for chunk in chunks:
                handle.write(json.dumps(json_safe_value(chunk), ensure_ascii=False))
                handle.write("\n")
        os.replace(tmp_name, corpus_path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise

    return {
        "status": "success",
        "chunks_indexed": len(chunks),
        "builtin_chunks": len(kb_corpus_chunks()),
        "staged_chunks": len(chunks) - len(kb_corpus_chunks()),
        "index_dir": str(index_dir),
        "corpus": str(corpus_path),
    }


def safe_entry_id(data: dict[str, Any]) -> str:
    raw = str(data.get("id") or data.get("case_id") or "new_entry")
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", raw).strip("._")
    return slug[:120] or "new_entry"


def command_ingest(args: argparse.Namespace) -> dict[str, Any]:
    data_path = resolve_external_path(args.data_file)
    with data_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("ingest data must be a JSON object")

    ingest_dir, _ = _kb_dirs()
    ingest_dir.mkdir(parents=True, exist_ok=True)
    kb_type = args.kb_type.replace("-", "_")
    target = ingest_dir / f"{kb_type}_{safe_entry_id(data)}.json"
    record = {**data, "kb_type": kb_type}
    write_json_file(record, str(target))

    index_report = command_build_indexes() if args.rebuild else None
    return {
        "status": "success",
        "kb_type": kb_type,
        "staged_record": str(target),
        "index_rebuilt": bool(args.rebuild),
        "index_report": index_report,
    }


_QUANTITATIVE_CLAIM = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:%|mg/L|µg/L|ug/L|ng/L|NTU|kWh|USD|\$/m3|\$/m³)(?=$|\s|[.,;:)\]])",
    re.IGNORECASE,
)
_ALLOWED_SUPPORT_TYPES = {"evidence_backed", "system_inference", "assumption"}


def _audit_issue(issues: list[dict[str, Any]], code: str, severity: str, message: str, location: str) -> None:
    issues.append({"code": code, "severity": severity, "message": message, "location": location})


def command_audit_report(args: argparse.Namespace) -> dict[str, Any]:
    report_path = resolve_external_path(args.report_file)
    with report_path.open("r", encoding="utf-8") as handle:
        report = json.load(handle)
    if not isinstance(report, dict):
        raise ValueError("HydroWeaver report must be a JSON object")
    recommendations = report.get("recommendations")
    if not isinstance(recommendations, list):
        raise ValueError("HydroWeaver report requires a recommendations array")

    claim_ledger: list[dict[str, Any]] = []
    recommendation_audits: list[dict[str, Any]] = []
    all_issues: list[dict[str, Any]] = []
    support_counts = {support_type: 0 for support_type in sorted(_ALLOWED_SUPPORT_TYPES)}
    malformed_claims = 0
    if not recommendations:
        _audit_issue(all_issues, "AUDIT-012", "critical", "The report contains no treatment recommendations to audit.", "recommendations")

    for index, rec in enumerate(recommendations, start=1):
        location = f"recommendations[{index - 1}]"
        issues: list[dict[str, Any]] = []
        if not isinstance(rec, dict):
            _audit_issue(issues, "AUDIT-001", "critical", "Recommendation is not a JSON object.", location)
            all_issues.extend(issues)
            recommendation_audits.append({"index": index, "status": "fail", "issues": issues})
            continue

        chain_id = str(rec.get("chain_id") or f"recommendation_{index}")
        chain = rec.get("chain")
        if not isinstance(chain, list) or not chain or not all(isinstance(u, str) and u.strip() for u in chain):
            _audit_issue(issues, "AUDIT-002", "critical", "Recommendation has no valid ordered treatment chain.", f"{location}.chain")

        evidence = rec.get("evidence")
        if not isinstance(evidence, list):
            evidence = []
            _audit_issue(issues, "AUDIT-003", "critical", "Recommendation evidence is missing or is not an array.", f"{location}.evidence")
        evidence_backed = 0
        for ev_idx, citation in enumerate(evidence, start=1):
            cit_loc = f"{location}.evidence[{ev_idx - 1}]"
            if not isinstance(citation, dict):
                malformed_claims += 1
                _audit_issue(issues, "AUDIT-004", "critical", "Evidence citation is not a JSON object.", cit_loc)
                continue
            fields = {}
            invalid_fields = []
            for field in ("support_type", "claim", "source_id", "chunk_id", "text_excerpt"):
                val = citation.get(field)
                fields[field] = val.strip() if isinstance(val, str) else ""
                if val is not None and not isinstance(val, str):
                    invalid_fields.append(field)
            support_type = fields["support_type"]
            claim = fields["claim"]
            source_id = fields["source_id"]
            chunk_id = fields["chunk_id"]
            excerpt = fields["text_excerpt"]
            valid_support = support_type in _ALLOWED_SUPPORT_TYPES
            structurally_complete = bool(claim) and valid_support and not invalid_fields
            if support_type == "evidence_backed":
                structurally_complete = structurally_complete and bool(source_id and chunk_id and excerpt)
                if structurally_complete:
                    evidence_backed += 1
            if not structurally_complete:
                malformed_claims += 1
                _audit_issue(
                    issues,
                    "AUDIT-005",
                    "critical" if support_type == "evidence_backed" or invalid_fields else "warning",
                    "Claim-evidence entry has missing text, non-string citation fields, or an unsupported support type.",
                    cit_loc,
                )
            if valid_support:
                support_counts[support_type] += 1
            claim_ledger.append(
                {
                    "claim_id": f"{chain_id}:evidence:{ev_idx}",
                    "chain_id": chain_id,
                    "recommendation_index": index,
                    "claim": claim,
                    "support_type": support_type or "missing",
                    "source_id": source_id or None,
                    "chunk_id": chunk_id or None,
                    "text_excerpt": excerpt or None,
                    "structurally_complete": structurally_complete,
                }
            )

        assumptions = rec.get("assumptions")
        if isinstance(assumptions, list):
            for a_idx, assumption in enumerate(assumptions, start=1):
                if not isinstance(assumption, str) or not assumption.strip():
                    continue
                support_counts["assumption"] += 1
                claim_ledger.append(
                    {
                        "claim_id": f"{chain_id}:assumption:{a_idx}",
                        "chain_id": chain_id,
                        "recommendation_index": index,
                        "claim": assumption.strip(),
                        "support_type": "assumption",
                        "source_id": None,
                        "chunk_id": None,
                        "text_excerpt": None,
                        "structurally_complete": True,
                    }
                )

        why_it_works = str(rec.get("why_it_works") or "")
        if _QUANTITATIVE_CLAIM.search(why_it_works) and evidence_backed == 0:
            _audit_issue(issues, "AUDIT-006", "warning", "Explanatory text contains a quantitative claim without an evidence-backed citation.", f"{location}.why_it_works")
        if evidence_backed == 0:
            _audit_issue(issues, "AUDIT-007", "warning", "Recommendation has no structurally complete evidence-backed claim.", f"{location}.evidence")

        constraint_report = rec.get("constraint_report")
        constraint_status = None
        if isinstance(constraint_report, dict):
            constraint_status = constraint_report.get("overall_status")
            if constraint_status == "FAIL":
                _audit_issue(issues, "AUDIT-008", "critical", "Recommendation retains a failed constraint report.", f"{location}.constraint_report.overall_status")
            elif constraint_status in ("WARNING", "N/A"):
                _audit_issue(issues, "AUDIT-014", "warning", "Constraint report declares a warning or N/A check rather than PASS.", f"{location}.constraint_report.overall_status")
            elif constraint_status != "PASS":
                _audit_issue(issues, "AUDIT-013", "critical", "Constraint status is missing or unrecognized (expected PASS, WARNING, FAIL, N/A).", f"{location}.constraint_report.overall_status")
        else:
            _audit_issue(issues, "AUDIT-009", "critical", "Recommendation has no machine-readable constraint report.", f"{location}.constraint_report")

        uncertainty = rec.get("uncertainty")
        if uncertainty in (None, ""):
            _audit_issue(issues, "AUDIT-010", "warning", "Recommendation does not declare uncertainty.", f"{location}.uncertainty")
        elif uncertainty == "insufficient_evidence":
            _audit_issue(issues, "AUDIT-011", "warning", "Recommendation explicitly reports insufficient evidence.", f"{location}.uncertainty")

        status = "fail" if any(i["severity"] == "critical" for i in issues) else "warn" if issues else "pass"
        recommendation_audits.append(
            {
                "index": index,
                "chain_id": chain_id,
                "status": status,
                "constraint_status": constraint_status,
                "evidence_backed_claims": evidence_backed,
                "issues": issues,
            }
        )
        all_issues.extend(issues)

    critical_count = sum(i["severity"] == "critical" for i in all_issues)
    warning_count = sum(i["severity"] == "warning" for i in all_issues)
    audit_status = "fail" if critical_count else "warn" if warning_count else "pass"
    return {
        "schema_version": 1,
        "kind": "hydroweaver.claim-evidence-audit",
        "report": {
            "path": str(report_path),
            "query_id": report.get("query_id"),
            "pipeline_version": report.get("pipeline_version"),
        },
        "status": audit_status,
        "summary": {
            "recommendations": len(recommendations),
            "claims": len(claim_ledger),
            "support_types": support_counts,
            "malformed_claims": malformed_claims,
            "critical_issues": critical_count,
            "warnings": warning_count,
        },
        "recommendations": recommendation_audits,
        "issues": all_issues,
        "claim_ledger": claim_ledger,
        "limitations": [
            "Checks structural citation completeness, constraint feasibility, and uncertainty declarations.",
            "Does not substitute for site-specific pilot testing or regulatory approval.",
        ],
    }


def command_gym_tasks() -> dict[str, Any]:
    return {
        "kind": "hydroweaver.aquadesigngym-catalog",
        "schema_version": 1,
        "tasks": list_tasks(),
        "admissible_actions": list(AquaDesignGymEnv.ADMISSIBLE_ACTIONS),
        "admissible_units": list(CANONICAL_UNITS),
        "perturbations": {k: v["description"] for k, v in PERTURBATION_PROFILES.items()},
        "methods": {
            name: {"family": meta["family"], "description": meta["description"]}
            for name, meta in METHOD_REGISTRY.items()
        },
    }


def command_gym_eval(args: argparse.Namespace) -> dict[str, Any]:
    methods = [m.strip() for m in args.methods.split(",") if m.strip()] if args.methods else None
    tasks = [t.strip() for t in args.tasks.split(",") if t.strip()] if args.tasks else None
    perturbations = [p.strip() for p in args.perturbations.split(",") if p.strip()] if args.perturbations else None
    return evaluate_benchmark(
        methods=methods,
        task_ids=tasks,
        perturbations=perturbations,
        max_sim_calls=args.max_sim_calls,
        seed=args.seed,
    )


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.version:
        print(f"hydroweaver-engine {ADAPTER_VERSION} (Python {sys.version.split()[0]})")
        return 0
    if args.command is None:
        parser.error("a command is required (or use --version)")

    handlers: dict[str, Callable[[], dict[str, Any]]] = {
        "health": command_health,
        "identity": command_identity,
        "catalog": lambda: command_catalog(args),
        "normalize": lambda: command_normalize(args),
        "assess-case": lambda: command_assess_case(args),
        "retrieve": lambda: command_retrieve(args),
        "recommend": lambda: command_recommend(args),
        "check-constraints": lambda: command_check_constraints(args),
        "optimize": lambda: command_optimize(args),
        "simulate": lambda: command_simulate(args),
        "build-indexes": command_build_indexes,
        "ingest": lambda: command_ingest(args),
        "audit-report": lambda: command_audit_report(args),
        "gym-tasks": command_gym_tasks,
        "gym-eval": lambda: command_gym_eval(args),
    }
    with contextlib.redirect_stdout(sys.stderr):
        payload = handlers[args.command]()
    emit(payload, getattr(args, "output", None))
    if args.command == "health" and payload.get("ok") is not True:
        return 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print(json.dumps({"ok": False, "error": "cancelled"}), file=sys.stderr)
        raise SystemExit(130)
    except Exception as error:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": type(error).__name__,
                    "detail": str(error),
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        raise SystemExit(1)
