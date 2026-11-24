"""Simulation feedback diagnosis and structural-vs-parametric routing."""

from __future__ import annotations

import copy
from typing import Any

from .knowledge import UNIT_SPECS, canonicalize_chain, default_parameters_for_chain


def diagnose_simulation(
    case: dict[str, Any],
    sim: dict[str, Any],
    *,
    params_already_optimized: bool = False,
) -> dict[str, Any]:
    """Diagnose constraint violations from simulation feedback and choose structural vs parametric action."""
    if sim.get("feasible"):
        return {
            "status": "feasible",
            "recommended_action": "stop_feasible",
            "structural_causes": [],
            "parametric_causes": [],
            "candidate_structural_edits": [],
            "rationale": "All water-quality, resource, cost, and hydraulic integrity constraints are satisfied.",
        }

    chain: list[str] = list(sim.get("chain") or [])
    all_violations: list[dict[str, Any]] = list(sim.get("violations") or [])
    violations: list[dict[str, Any]] = [v for v in all_violations if v.get("severity") == "hard"]
    wq = case.get("water_quality") if isinstance(case.get("water_quality"), dict) else {}
    constraints = sim.get("constraints") if isinstance(sim.get("constraints"), dict) else {}
    chem_allowed = constraints.get("chemical_dosing_allowed", True)
    brine_allowed = constraints.get("brine_disposal_allowed", True)

    structural_causes: list[dict[str, Any]] = []
    parametric_causes: list[dict[str, Any]] = []
    edits: list[dict[str, Any]] = []
    seen_edits: set[tuple[str, str]] = set()

    def propose_edit(op: str, unit: str | None, replace_with: str | None = None, *, reason: str, priority: int) -> None:
        new_chain = list(chain)
        if op == "add" and unit:
            if unit in new_chain:
                return
            new_chain.append(unit)
        elif op == "remove" and unit:
            if unit not in new_chain:
                return
            new_chain.remove(unit)
        elif op == "replace" and unit and replace_with:
            if unit not in new_chain or replace_with in new_chain:
                return
            new_chain = [replace_with if u == unit else u for u in new_chain]
        elif op == "reorder":
            pass
        else:
            return
        if not new_chain:
            return
        canon = canonicalize_chain(new_chain)
        sig = (op, "->".join(canon))
        if sig in seen_edits:
            return
        seen_edits.add(sig)
        edits.append(
            {
                "op": op,
                "target_unit": unit,
                "replacement_unit": replace_with,
                "new_chain": canon,
                "reason": reason,
                "priority": priority,
            }
        )

    effluent = sim.get("effluent") or {}
    as_iii_frac = float(effluent.get("arsenic_iii_frac") or 0.0)

    for v in violations:
        code = str(v.get("code") or "")
        unit = v.get("unit")
        metric = str(v.get("metric") or "")

        if code == "SIM-ORDER-001":
            structural_causes.append(v)
            propose_edit("reorder", None, reason="Sort units into feasible hydraulic process order.", priority=100)

        elif code == "RES-CHEM-001" and unit:
            structural_causes.append(v)
            if unit == "Chlorination":
                propose_edit("replace", "Chlorination", "UV Disinfection", reason="Replace chemical chlorination with chemical-free UV disinfection.", priority=95)
            elif unit == "Oxidation":
                propose_edit("remove", "Oxidation", reason="Remove disallowed chemical pre-oxidation.", priority=90)
                if "Adsorption" not in chain:
                    propose_edit("add", "Adsorption", reason="Use adsorptive media without chemical dosing.", priority=85)
            elif unit == "Coagulation":
                propose_edit("replace", "Coagulation", "Ultrafiltration", reason="Replace chemical coagulation with physical UF barrier.", priority=90)
            else:
                propose_edit("remove", unit, reason=f"Remove chemical-dosing unit {unit}.", priority=85)

        elif code == "RES-SKILL-001" and unit:
            structural_causes.append(v)
            if unit == "Reverse Osmosis":
                propose_edit("replace", "Reverse Osmosis", "Adsorption", reason="Replace high-complexity RO with simpler Adsorption.", priority=85)
                propose_edit("replace", "Reverse Osmosis", "Media Filtration", reason="Replace high-complexity RO with Media Filtration.", priority=70)
            elif unit == "Nanofiltration":
                propose_edit("replace", "Nanofiltration", "Adsorption", reason="Replace NF with lower-complexity Adsorption.", priority=80)
            else:
                propose_edit("remove", unit, reason=f"Remove unit exceeding operator skill limit ({unit}).", priority=75)

        elif code == "SIM-COAG-001":
            structural_causes.append(v)
            propose_edit("add", "Media Filtration", reason="Add Media Filtration downstream of Coagulation to capture flocs.", priority=95)
            propose_edit("add", "Sedimentation", reason="Add Sedimentation downstream of Coagulation.", priority=88)

        elif code == "SIM-MEM-PUMP":
            structural_causes.append(v)
            propose_edit("add", "Pumping", reason="Add Pumping upstream of membrane unit.", priority=98)

        elif code in ("SIM-MEM-FOUL-TURB", "SIM-MEM-FOUL-FE", "SIM-ADS-FOUL", "SIM-IX-FOUL", "SIM-AOP-UVT", "SIM-UV-TURB"):
            structural_causes.append(v)
            if "Media Filtration" not in chain:
                propose_edit("add", "Media Filtration", reason="Insert Media Filtration pretreatment to reduce inlet turbidity/iron.", priority=92)
            if "Ultrafiltration" not in chain and unit in ("Reverse Osmosis", "Nanofiltration"):
                propose_edit("add", "Ultrafiltration", reason="Insert Ultrafiltration pretreatment for membrane fouling protection.", priority=88)
            if code == "SIM-MEM-FOUL-FE" and chem_allowed and "Oxidation" not in chain:
                propose_edit("add", "Oxidation", reason="Insert Oxidation before filtration to precipitate dissolved iron.", priority=84)

        elif code in ("SIM-MEM-SCALE-HARD", "SIM-MEM-SCALE-SI"):
            if not params_already_optimized:
                parametric_causes.append(v)
            if chem_allowed and "Lime Softening" not in chain:
                propose_edit("add", "Lime Softening", reason="Add Lime Softening to remove hardness/silica and prevent membrane scaling.", priority=90)
            if "Reverse Osmosis" in chain and "Nanofiltration" not in chain and float(wq.get("tds_mg_L") or 0) < 2500:
                propose_edit("replace", "Reverse Osmosis", "Nanofiltration", reason="Switch from RO to NF at lower scaling concentration factor.", priority=72)

        elif code == "SIM-MEM-NDP":
            # Net driving pressure too low -> first try raising Pumping pressure / adjusting recovery via numerical optimizer
            if not params_already_optimized:
                parametric_causes.append(v)
            else:
                structural_causes.append(v)
                if "Pumping" not in chain:
                    propose_edit("add", "Pumping", reason="Add Pumping to raise membrane driving pressure.", priority=95)
                if "Reverse Osmosis" in chain and float(wq.get("tds_mg_L") or 0) < 2000:
                    propose_edit("replace", "Reverse Osmosis", "Nanofiltration", reason="Replace RO with lower-pressure NF.", priority=70)

        elif code == "RES-BRINE-001":
            structural_causes.append(v)
            if "Reverse Osmosis" in chain or "Nanofiltration" in chain:
                if "Brine Concentrator" not in chain and float(wq.get("tds_mg_L") or 0) > 1500:
                    propose_edit("add", "Brine Concentrator", reason="Add Brine Concentrator to minimize concentrate discharge below 5%.", priority=92)
                if float(wq.get("tds_mg_L") or 0) <= 1500:
                    if "Adsorption" not in chain:
                        propose_edit("replace", "Reverse Osmosis" if "Reverse Osmosis" in chain else "Nanofiltration", "Adsorption", reason="Replace brine-generating membrane with non-brine Adsorption.", priority=90)
                    else:
                        propose_edit("remove", "Reverse Osmosis" if "Reverse Osmosis" in chain else "Nanofiltration", reason="Remove brine-generating membrane when non-brine adsorption handles trace contaminants.", priority=88)
            if "Ion Exchange" in chain:
                propose_edit("replace", "Ion Exchange", "Adsorption", reason="Replace IX regenerant-brine process with Adsorption.", priority=85)

        elif code == "WQ-DISINF-UNIT":
            structural_causes.append(v)
            if chem_allowed and float(effluent.get("toc_mg_L") or 0) <= 3.0:
                propose_edit("add", "Chlorination", reason="Add Chlorination barrier for potable disinfection.", priority=94)
            propose_edit("add", "UV Disinfection", reason="Add chemical-free UV Disinfection barrier.", priority=92 if not chem_allowed else 88)

        elif code == "WQ-DBP-001":
            structural_causes.append(v)
            if "Chlorination" in chain:
                propose_edit("replace", "Chlorination", "UV Disinfection", reason="Switch Chlorination to UV Disinfection to prevent DBP formation.", priority=92)
            if "Adsorption" not in chain:
                propose_edit("add", "Adsorption", reason="Add Adsorption upstream of Chlorination to cut DBP precursors (TOC).", priority=86)

        elif code == "WQ-ARSENIC_UG_L":
            if as_iii_frac > 0.20 and chem_allowed and "Oxidation" not in chain:
                structural_causes.append(v)
                propose_edit("add", "Oxidation", reason="Un-oxidized As(III) limits removal; add Oxidation upstream.", priority=94)
            elif not params_already_optimized:
                parametric_causes.append(v)
            else:
                structural_causes.append(v)
                if "Adsorption" not in chain:
                    propose_edit("add", "Adsorption", reason="Add Adsorption polishing for arsenic.", priority=90)
                if chem_allowed and "Coagulation" not in chain:
                    propose_edit("add", "Coagulation", reason="Add ferric Coagulation upstream for As(V) co-precipitation.", priority=86)
                elif "Reverse Osmosis" not in chain and brine_allowed:
                    propose_edit("add", "Reverse Osmosis", reason="Add Reverse Osmosis for high arsenic rejection.", priority=82)
                    propose_edit("add", "Pumping", reason="Support RO pressure.", priority=78)

        elif code == "WQ-TDS_MG_L":
            if "Reverse Osmosis" not in chain and "Nanofiltration" not in chain:
                structural_causes.append(v)
                propose_edit("add", "Reverse Osmosis", reason="Add Reverse Osmosis for dissolved TDS desalination.", priority=95)
            elif not params_already_optimized:
                parametric_causes.append(v)
            else:
                structural_causes.append(v)
                if "Nanofiltration" in chain and "Reverse Osmosis" not in chain:
                    propose_edit("replace", "Nanofiltration", "Reverse Osmosis", reason="Upgrade NF to RO for tighter monovalent TDS rejection.", priority=90)

        elif code == "WQ-NITRATE_MG_L":
            if "Reverse Osmosis" not in chain and "Ion Exchange" not in chain:
                structural_causes.append(v)
                if brine_allowed:
                    propose_edit("add", "Ion Exchange", reason="Add selective Ion Exchange for nitrate removal.", priority=90)
                propose_edit("add", "Reverse Osmosis", reason="Add Reverse Osmosis for nitrate separation.", priority=86)
            elif not params_already_optimized:
                parametric_causes.append(v)
            else:
                structural_causes.append(v)
                if "Ion Exchange" not in chain and "Reverse Osmosis" in chain:
                    propose_edit("add", "Ion Exchange", reason="Add Ion Exchange nitrate polishing downstream of membrane.", priority=82)

        elif code == "WQ-TOC_MG_L":
            if not params_already_optimized and any(u in chain for u in ("Coagulation", "Adsorption", "Advanced Oxidation")):
                parametric_causes.append(v)
            else:
                structural_causes.append(v)
                if "Adsorption" not in chain:
                    propose_edit("add", "Adsorption", reason="Add GAC Adsorption for TOC removal.", priority=88)
                if "Advanced Oxidation" not in chain and chem_allowed:
                    propose_edit("add", "Advanced Oxidation", reason="Add UV/H2O2 AOP for refractory TOC destruction.", priority=80)

        elif code == "WQ-TURBIDITY_NTU":
            if not params_already_optimized and any(u in chain for u in ("Coagulation", "Sedimentation", "Media Filtration")):
                parametric_causes.append(v)
            else:
                structural_causes.append(v)
                if "Media Filtration" not in chain:
                    propose_edit("add", "Media Filtration", reason="Add Media Filtration for turbidity reduction.", priority=90)
                if "Ultrafiltration" not in chain:
                    propose_edit("add", "Ultrafiltration", reason="Add Ultrafiltration for sub-0.1 NTU effluent.", priority=86)

        elif code == "WQ-HARDNESS_MG_L":
            if not params_already_optimized and any(u in chain for u in ("Lime Softening", "Nanofiltration", "Reverse Osmosis", "Ion Exchange")):
                parametric_causes.append(v)
            else:
                structural_causes.append(v)
                if "Nanofiltration" not in chain and "Reverse Osmosis" not in chain:
                    propose_edit("add", "Nanofiltration", reason="Add Nanofiltration for selective divalent hardness removal.", priority=88)
                elif chem_allowed and "Lime Softening" not in chain:
                    propose_edit("add", "Lime Softening", reason="Add Lime Softening for hardness precipitation.", priority=84)

        elif code == "RES-SEC-001":
            if ("Reverse Osmosis" in chain or "Nanofiltration" in chain) and "Energy Recovery" not in chain:
                structural_causes.append(v)
                propose_edit("add", "Energy Recovery", reason="Add Energy Recovery (PX) to lower RO/NF pumping SEC.", priority=94)
            elif not params_already_optimized:
                parametric_causes.append(v)
            else:
                structural_causes.append(v)
                if "Lime Softening" in chain and "Reverse Osmosis" in chain:
                    propose_edit("remove", "Lime Softening", reason="Remove unnecessary Lime Softening stage to simplify train and cut energy/cost.", priority=82)
                if "Brine Concentrator" in chain:
                    propose_edit("remove", "Brine Concentrator", reason="Remove energy-intensive thermal Brine Concentrator if feasible.", priority=78)

        elif code == "RES-REC-001":
            if not params_already_optimized and any(u in chain for u in ("Reverse Osmosis", "Nanofiltration", "Ultrafiltration", "Brine Concentrator")):
                parametric_causes.append(v)
            else:
                structural_causes.append(v)
                if "Ultrafiltration" in chain and "Media Filtration" in chain:
                    propose_edit("remove", "Ultrafiltration", reason="Remove redundant UF stage whose backwash reject reduces net recovery.", priority=90)
                if ("Reverse Osmosis" in chain or "Nanofiltration" in chain) and "Brine Concentrator" not in chain:
                    propose_edit("add", "Brine Concentrator", reason="Add Brine Concentrator to lift overall system recovery.", priority=84)

        elif code == "RES-FOOTPRINT-001":
            structural_causes.append(v)
            if "Sedimentation" in chain:
                propose_edit("replace", "Sedimentation", "Ultrafiltration", reason="Replace large-footprint Sedimentation with compact Ultrafiltration.", priority=92)
            elif not params_already_optimized:
                parametric_causes.append(v)

        elif code == "COST-LCOW-001":
            if not params_already_optimized:
                parametric_causes.append(v)
            else:
                structural_causes.append(v)
                if ("Reverse Osmosis" in chain or "Nanofiltration" in chain) and "Energy Recovery" not in chain:
                    propose_edit("add", "Energy Recovery", reason="Add Energy Recovery to lower electricity OPEX and LCOW.", priority=86)
                if "Sedimentation" in chain and "Flocculation" in chain:
                    propose_edit("remove", "Flocculation", reason="Simplify clarification train to reduce CAPEX/LCOW.", priority=76)
                if "Ultrafiltration" in chain and "Media Filtration" in chain and float(wq.get("turbidity_NTU") or 0) < 5.0:
                    propose_edit("remove", "Ultrafiltration", reason="Remove redundant UF on low-turbidity feed to lower LCOW.", priority=74)

        elif code == "WQ-DISINF-LOG":
            if not params_already_optimized:
                parametric_causes.append(v)
            else:
                structural_causes.append(v)
                if "UV Disinfection" not in chain:
                    propose_edit("add", "UV Disinfection", reason="Add UV Disinfection to boost cumulative pathogen log reduction.", priority=86)

        else:
            if not params_already_optimized:
                parametric_causes.append(v)
            else:
                structural_causes.append(v)

    # Clean up warning-level structural anomalies (e.g. Energy Recovery without RO/NF)
    for w in all_violations:
        if w.get("code") == "SIM-ERD-NOBRINE" and "Energy Recovery" in chain:
            propose_edit("remove", "Energy Recovery", reason="Remove Energy Recovery without upstream RO/NF concentrate.", priority=96)
        elif w.get("code") == "SIM-BC-NOBRINE" and "Brine Concentrator" in chain:
            propose_edit("remove", "Brine Concentrator", reason="Remove Brine Concentrator without upstream brine.", priority=96)
    if "Pumping" in chain and "Reverse Osmosis" not in chain and "Nanofiltration" not in chain:
        propose_edit("remove", "Pumping", reason="Remove standalone high-pressure Pumping when no RO/NF membrane is present.", priority=93)

    # Also ensure any membrane proposal automatically bundles Pumping if Pumping is missing
    expanded_edits: list[dict[str, Any]] = []
    seen_chains: set[tuple[str, ...]] = set()
    for edit in sorted(edits, key=lambda item: -item["priority"]):
        cand_chain = list(edit["new_chain"])
        if ("Reverse Osmosis" in cand_chain or "Nanofiltration" in cand_chain) and "Pumping" not in cand_chain:
            cand_chain = canonicalize_chain([*cand_chain, "Pumping"])
            edit = {**edit, "new_chain": cand_chain}
        if "Reverse Osmosis" not in cand_chain and "Nanofiltration" not in cand_chain:
            cand_chain = [u for u in cand_chain if u not in ("Pumping", "Energy Recovery")]
            edit = {**edit, "new_chain": cand_chain}
        sig = tuple(cand_chain)
        if sig and sig not in seen_chains and sig != tuple(chain):
            seen_chains.add(sig)
            expanded_edits.append(edit)

    # Routing decision: structural vs parametric
    # Hard structural incompatibilities (missing pump, disallowed chemical, unseparated flocs, missing disinfection unit, brine prohibition) MUST revise structure first.
    hard_structural_codes = {
        "SIM-ORDER-001", "RES-CHEM-001", "RES-SKILL-001", "SIM-COAG-001",
        "SIM-MEM-PUMP", "SIM-MEM-FOUL-TURB", "SIM-MEM-FOUL-FE", "SIM-ADS-FOUL",
        "SIM-IX-FOUL", "SIM-AOP-UVT", "SIM-UV-TURB", "RES-BRINE-001",
        "WQ-DISINF-UNIT", "WQ-DBP-001", "RES-FOOTPRINT-001",
    }
    has_blocking_structural = any(v.get("code") in hard_structural_codes for v in violations)

    if has_blocking_structural or (params_already_optimized and expanded_edits):
        decision = "revise_structure"
        rationale = "Simulation feedback diagnosed structural or unit-capability violations requiring topology revision."
    elif parametric_causes and not params_already_optimized:
        decision = "refine_parameters"
        rationale = "Train topology possesses required treatment mechanisms; violations stem from tunable operating setpoints."
    elif expanded_edits:
        decision = "revise_structure"
        rationale = "Parametric refinement cannot resolve remaining deficits; routing to structural revision."
    else:
        decision = "refine_parameters"
        rationale = "No structural edit available; attempting bounded parameter optimization."

    return {
        "status": "infeasible",
        "recommended_action": decision,
        "structural_causes": structural_causes,
        "parametric_causes": parametric_causes,
        "candidate_structural_edits": expanded_edits,
        "rationale": rationale,
    }


def apply_best_structural_edit(
    case: dict[str, Any],
    diagnosis: dict[str, Any],
    seen_topologies: set[tuple[str, ...]],
) -> tuple[list[str], dict[str, dict[str, float]], dict[str, Any]] | None:
    """Pick the highest-priority unseen structural edit from diagnosis."""
    for edit in diagnosis.get("candidate_structural_edits") or []:
        cand = tuple(edit["new_chain"])
        if cand not in seen_topologies:
            chain = list(cand)
            return chain, default_parameters_for_chain(chain, case), edit
    return None
