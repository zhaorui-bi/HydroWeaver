"""Mechanistic and economic steady-state process simulator for treatment trains."""

from __future__ import annotations

import copy
import math
from typing import Any

from .knowledge import (
    UNIT_SPECS,
    canonicalize_chain,
    default_parameters_for_chain,
    normalize_unit_name,
)

ELECTRICITY_USD_PER_KWH = 0.10
CAPITAL_RECOVERY_FACTOR = 0.08024  # 20-year asset life @ 5% discount rate
FIXED_OM_FRACTION = 0.03
BRINE_DISPOSAL_USD_PER_M3 = 0.35
SLUDGE_DISPOSAL_USD_PER_KG = 0.12

CHEMICAL_PRICES_USD_PER_KG = {
    "coagulant": 0.45,
    "lime": 0.18,
    "oxidant": 1.60,
    "chlorine": 1.20,
    "h2o2": 1.80,
}

ENERGY_TIER_MAX_SEC = {
    "low": 0.85,
    "low-medium": 1.40,
    "medium": 2.40,
    "medium-high": 3.80,
    "high": 6.00,
    "grid_connected": 5.50,
}

BUDGET_TIER_MAX_LCOW = {
    "low": 0.90,
    "medium": 1.85,
    "high": 3.50,
}

SKILL_TIER_MAX_COMPLEXITY = {
    "low": 3,
    "medium": 4,
    "high": 5,
}


def _safe_float(value: Any, default: float) -> float:
    if isinstance(value, bool) or value is None:
        return default
    try:
        num = float(value)
        return num if math.isfinite(num) else default
    except (TypeError, ValueError):
        return default


def _parse_arsenic_iii_fraction(wq: dict[str, Any]) -> float:
    extra = wq.get("extra") if isinstance(wq.get("extra"), dict) else {}
    raw = str(extra.get("arsenic_speciation") or "").lower()
    if not raw or "unknown" in raw or "unspecified" in raw:
        return 0.45
    has_iii = "as(iii)" in raw or "iii" in raw or "arsenite" in raw
    has_v = "as(v)" in raw or "arsenate" in raw
    if has_iii and not has_v:
        return 0.85
    if has_v and not has_iii:
        return 0.05
    if has_iii and has_v:
        return 0.50
    return 0.45


def _nitrate_to_n(value: float, section: dict[str, Any]) -> float:
    extra = section.get("extra") if isinstance(section.get("extra"), dict) else {}
    basis = str(extra.get("nitrate_basis") or "").lower().replace("_", "").replace("-", "").replace(" ", "")
    if basis in {"asno3", "no3", "nitrateasno3"}:
        return value * (14.007 / 62.004)
    return value


def extract_constraints(case: dict[str, Any]) -> dict[str, Any]:
    """Extract numeric water-quality, resource, and cost constraints from a HydroWeaver case."""
    wq = case.get("water_quality") if isinstance(case.get("water_quality"), dict) else {}
    targets = case.get("treatment_targets") if isinstance(case.get("treatment_targets"), dict) else {}
    target_extra = targets.get("extra") if isinstance(targets.get("extra"), dict) else {}
    constraints = case.get("constraints") if isinstance(case.get("constraints"), dict) else {}
    c_extra = constraints.get("extra") if isinstance(constraints.get("extra"), dict) else {}

    wq_limits: dict[str, float] = {}
    for key, stream_key in (
        ("tds_mg_L", "tds_mg_L"),
        ("turbidity_NTU", "turbidity_NTU"),
        ("toc_mg_L", "toc_mg_L"),
        ("arsenic_ug_L", "arsenic_ug_L"),
        ("fluoride_mg_L", "fluoride_mg_L"),
        ("hardness_mg_L", "hardness_mg_L"),
        ("iron_mg_L", "iron_mg_L"),
    ):
        if targets.get(key) is not None and not isinstance(targets.get(key), bool):
            wq_limits[stream_key] = float(targets[key])
    if targets.get("nitrate_mg_L") is not None and not isinstance(targets.get("nitrate_mg_L"), bool):
        wq_limits["nitrate_mg_L"] = _nitrate_to_n(float(targets["nitrate_mg_L"]), targets)
    for key, stream_key in (
        ("lead_ug_L", "lead_ug_L"),
        ("boron_mg_L", "boron_mg_L"),
        ("silica_mg_L", "silica_mg_L"),
    ):
        val = targets.get(key) if targets.get(key) is not None else target_extra.get(key)
        if val is not None and not isinstance(val, bool):
            wq_limits[stream_key] = float(val)

    use_for_drinking = constraints.get("use_for_drinking")
    if use_for_drinking is None:
        use_for_drinking = "drinking" in str(case.get("context") or "").lower()

    design_flow = _safe_float(c_extra.get("design_flow_m3_day"), 500.0)
    if design_flow <= 0:
        design_flow = 500.0

    max_sec = _safe_float(c_extra.get("max_sec_kwh_m3"), -1.0)
    if max_sec <= 0:
        energy_label = str(constraints.get("energy") or "").strip().lower()
        max_sec = ENERGY_TIER_MAX_SEC.get(energy_label, 4.5)

    max_lcow = _safe_float(c_extra.get("max_lcow_usd_m3"), -1.0)
    if max_lcow <= 0:
        budget_label = str(constraints.get("budget") or "").strip().lower()
        max_lcow = BUDGET_TIER_MAX_LCOW.get(budget_label, 2.20)

    min_recovery = _safe_float(c_extra.get("min_recovery"), 0.55)
    max_footprint = _safe_float(c_extra.get("max_footprint_m2"), -1.0)
    if max_footprint <= 0:
        fp_text = str(constraints.get("footprint_constraint") or "").lower()
        if any(tok in fp_text for tok in ("tight", "small", "compact", "limited")):
            max_footprint = max(45.0, 0.14 * design_flow)
        else:
            max_footprint = max(180.0, 0.55 * design_flow)

    skill_label = str(constraints.get("operator_skill") or "medium").strip().lower()
    max_complexity = int(_safe_float(c_extra.get("max_operator_complexity"), SKILL_TIER_MAX_COMPLEXITY.get(skill_label, 4)))

    brine_disposal_allowed = constraints.get("brine_disposal") is not False
    chemical_dosing_allowed = constraints.get("chemical_dosing_allowed") is not False

    min_disinfection_log = _safe_float(c_extra.get("min_disinfection_log"), 4.0 if (use_for_drinking or wq.get("e_coli_CFU_100mL")) else 0.0)

    return {
        "design_flow_m3_day": design_flow,
        "wq_limits": wq_limits,
        "use_for_drinking": bool(use_for_drinking),
        "min_disinfection_log": min_disinfection_log,
        "min_recovery": min_recovery,
        "max_sec_kwh_m3": max_sec,
        "max_lcow_usd_m3": max_lcow,
        "max_footprint_m2": max_footprint,
        "max_operator_complexity": max_complexity,
        "brine_disposal_allowed": brine_disposal_allowed,
        "chemical_dosing_allowed": chemical_dosing_allowed,
        "influent_tds_mg_L": _safe_float(wq.get("tds_mg_L"), 450.0),
    }


def _clamp_params(chain: list[str], supplied: dict[str, dict[str, Any]] | None, case: dict[str, Any]) -> dict[str, dict[str, float]]:
    base = default_parameters_for_chain(chain, case)
    if not isinstance(supplied, dict):
        return base
    for unit in chain:
        spec = UNIT_SPECS.get(unit)
        if spec is None:
            continue
        raw_unit = supplied.get(unit)
        if not isinstance(raw_unit, dict):
            continue
        for pspec in spec.params:
            if pspec.name in raw_unit and not isinstance(raw_unit[pspec.name], bool):
                val = _safe_float(raw_unit[pspec.name], base[unit][pspec.name])
                base[unit][pspec.name] = max(pspec.lower, min(pspec.upper, val))
    return base


def _add_violation(
    violations: list[dict[str, Any]],
    *,
    category: str,
    code: str,
    severity: str,
    unit: str | None,
    metric: str,
    actual: float | str | bool,
    limit: float | str | bool,
    rel_excess: float,
    message: str,
) -> None:
    violations.append(
        {
            "category": category,  # water_quality | resource | cost | integrity
            "code": code,
            "severity": severity,  # hard | warning
            "unit": unit,
            "metric": metric,
            "actual": round(actual, 4) if isinstance(actual, float) else actual,
            "limit": round(limit, 4) if isinstance(limit, float) else limit,
            "rel_excess": round(max(0.0, rel_excess), 5),
            "message": message,
        }
    )


def simulate_train(
    case: dict[str, Any],
    chain: list[str],
    params: dict[str, dict[str, Any]] | None = None,
    watertap_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run coupled steady-state mass-balance, hydraulic, resource, and LCOW simulation."""
    if not chain:
        raise ValueError("chain must be a non-empty list of treatment units")

    ordered = [normalize_unit_name(u) or u for u in chain]
    unknown_units = [u for u in ordered if u not in UNIT_SPECS]
    if unknown_units:
        raise ValueError(f"Unsupported treatment unit(s): {', '.join(unknown_units)}")

    # Preserve caller order if valid or canonical stage ordering check
    canon_order = canonicalize_chain(ordered)
    out_of_order = ordered != canon_order

    cfg = extract_constraints(case)
    wq = case.get("water_quality") if isinstance(case.get("water_quality"), dict) else {}
    effective_params = _clamp_params(ordered, params, case)
    flow_in = cfg["design_flow_m3_day"]
    temp_c = _safe_float(wq.get("temperature_C"), 20.0)

    state: dict[str, Any] = {
        "flow_m3_day": flow_in,
        "brine_flow_m3_day": 0.0,
        "sludge_kg_day": 0.0,
        "pressure_bar": 1.2,
        "temperature_C": temp_c,
        "pH": _safe_float(wq.get("pH"), 7.2),
        "tds_mg_L": _safe_float(wq.get("tds_mg_L"), 450.0),
        "turbidity_NTU": _safe_float(wq.get("turbidity_NTU"), 1.0),
        "toc_mg_L": _safe_float(wq.get("toc_mg_L"), 2.0),
        "arsenic_ug_L": _safe_float(wq.get("arsenic_ug_L"), 0.0),
        "arsenic_iii_frac": _parse_arsenic_iii_fraction(wq),
        "nitrate_mg_L": _nitrate_to_n(_safe_float(wq.get("nitrate_mg_L"), 0.0), wq),
        "fluoride_mg_L": _safe_float(wq.get("fluoride_mg_L"), 0.0),
        "hardness_mg_L": _safe_float(wq.get("hardness_mg_L"), 100.0),
        "iron_mg_L": _safe_float(wq.get("iron_mg_L"), 0.05),
        "lead_ug_L": _safe_float(wq.get("lead_ug_L"), 0.0),
        "boron_mg_L": _safe_float(wq.get("boron_mg_L"), 0.0),
        "silica_mg_L": _safe_float(wq.get("silica_mg_L"), 10.0),
        "disinfection_log_reduction": 0.0,
        "coag_destabilized": False,
        "brine_pressure_bar": 0.0,
        "brine_tds_mg_L": 0.0,
    }

    total_power_kw = 0.0
    total_capex_usd = 0.0
    total_chem_opex_usd_yr = 0.0
    total_media_mem_opex_usd_yr = 0.0
    total_footprint_m2 = 0.0
    total_chem_dose_mg_L = 0.0
    recovered_power_kw = 0.0
    unit_reports: list[dict[str, Any]] = []
    violations: list[dict[str, Any]] = []

    if out_of_order:
        _add_violation(
            violations,
            category="integrity",
            code="SIM-ORDER-001",
            severity="hard",
            unit=None,
            metric="unit_sequence",
            actual=" -> ".join(ordered),
            limit=" -> ".join(canon_order),
            rel_excess=1.0,
            message=f"Treatment units are out of hydraulic process order; expected {' -> '.join(canon_order)}.",
        )

    for idx, unit_name in enumerate(ordered):
        spec = UNIT_SPECS[unit_name]
        up = effective_params[unit_name]
        inlet_snapshot = copy.deepcopy(state)
        unit_flow = state["flow_m3_day"]

        # Scale CAPEX and footprint nonlinearly with flow
        flow_scale = max(unit_flow, 10.0)
        unit_capex = spec.base_capex_usd + spec.capex_per_m3d_usd * flow_scale * ((500.0 / flow_scale) ** (1.0 - spec.capex_scale_exp))
        unit_footprint = spec.base_footprint_m2 + spec.footprint_per_m3d_m2 * flow_scale
        unit_power_kw = 0.02 * (unit_flow / 24.0)  # nominal mixing/instrumentation
        unit_chem_usd_yr = 0.0
        unit_extra: dict[str, Any] = {}

        if not cfg["chemical_dosing_allowed"] and spec.requires_chemical_dosing:
            _add_violation(
                violations,
                category="resource",
                code="RES-CHEM-001",
                severity="hard",
                unit=unit_name,
                metric="chemical_dosing_allowed",
                actual=True,
                limit=False,
                rel_excess=1.0,
                message=f"{unit_name} requires chemical dosing, which is prohibited by site constraints.",
            )

        if spec.operator_complexity > cfg["max_operator_complexity"]:
            _add_violation(
                violations,
                category="resource",
                code="RES-SKILL-001",
                severity="hard",
                unit=unit_name,
                metric="operator_complexity",
                actual=float(spec.operator_complexity),
                limit=float(cfg["max_operator_complexity"]),
                rel_excess=(spec.operator_complexity - cfg["max_operator_complexity"]) / max(1, cfg["max_operator_complexity"]),
                message=f"{unit_name} complexity ({spec.operator_complexity}) exceeds site operator skill capacity ({cfg['max_operator_complexity']}).",
            )

        # ---- Unit physics ----
        if unit_name == "Oxidation":
            dose = up["oxidant_dose_mg_L"]
            ct = up["contact_time_min"]
            demand_factor = 1.0 + 0.15 * state["toc_mg_L"] + 0.6 * state["iron_mg_L"]
            eff_ct = (dose * ct) / demand_factor
            conv = 1.0 - math.exp(-0.085 * eff_ct)
            state["arsenic_iii_frac"] = state["arsenic_iii_frac"] * (1.0 - conv)
            fe_ox = state["iron_mg_L"] * min(0.95, conv)
            state["turbidity_NTU"] += 0.45 * fe_ox
            state["iron_mg_L"] = max(0.02, state["iron_mg_L"] - fe_ox * 0.4)
            unit_chem_usd_yr = (dose * 1e-3) * unit_flow * 365.0 * CHEMICAL_PRICES_USD_PER_KG["oxidant"]
            total_chem_dose_mg_L += dose
            unit_power_kw = 0.04 * (unit_flow / 24.0)
            unit_extra = {"as_iii_conversion": round(conv, 4), "remaining_as_iii_frac": round(state["arsenic_iii_frac"], 4)}

        elif unit_name == "Coagulation":
            dose = up["coagulant_dose_mg_L"]
            g_val = up["rapid_mix_g_s"]
            ph_penalty = math.exp(-0.35 * ((state["pH"] - 7.0) / 1.4) ** 2)
            mix_factor = min(1.05, 0.75 + 0.30 * (g_val / 700.0))
            eff = (1.0 - math.exp(-0.048 * dose)) * ph_penalty * mix_factor
            state["coag_destabilized"] = True
            state["toc_mg_L"] *= max(0.32, 1.0 - 0.58 * eff)
            as_v_frac = 1.0 - state["arsenic_iii_frac"]
            as_removed_frac = eff * (0.88 * as_v_frac + 0.18 * state["arsenic_iii_frac"])
            state["arsenic_ug_L"] *= max(0.05, 1.0 - as_removed_frac)
            state["lead_ug_L"] *= max(0.08, 1.0 - 0.85 * eff)
            # Coagulant forms microflocs that remain in suspension until separated downstream
            downstream = ordered[idx + 1 :]
            has_sep = any(u in downstream for u in ("Sedimentation", "Media Filtration", "Ultrafiltration"))
            if not has_sep:
                state["turbidity_NTU"] += 0.18 * dose
                _add_violation(
                    violations,
                    category="integrity",
                    code="SIM-COAG-001",
                    severity="hard",
                    unit=unit_name,
                    metric="downstream_solids_separation",
                    actual=False,
                    limit=True,
                    rel_excess=1.0,
                    message="Coagulation requires downstream Sedimentation, Media Filtration, or Ultrafiltration to remove precipitated flocs.",
                )
            state["sludge_kg_day"] += (0.55 * dose + 1.2 * state["turbidity_NTU"]) * unit_flow * 1e-3
            unit_chem_usd_yr = (dose * 1e-3) * unit_flow * 365.0 * CHEMICAL_PRICES_USD_PER_KG["coagulant"]
            total_chem_dose_mg_L += dose
            unit_power_kw = (0.015 + 0.00004 * g_val) * (unit_flow / 24.0)
            unit_extra = {"destabilization_efficiency": round(eff, 4)}

        elif unit_name == "Flocculation":
            ft = up["floc_time_min"]
            g_val = up["velocity_gradient_s"]
            agg = 1.0 - math.exp(-0.05 * ft) * math.exp(-0.02 * (g_val / 40.0))
            unit_power_kw = (0.012 + 0.0002 * g_val) * (unit_flow / 24.0)
            unit_footprint *= ft / 25.0
            unit_capex *= 0.8 + 0.2 * (ft / 25.0)
            unit_extra = {"floc_aggregation_index": round(agg, 4)}

        elif unit_name == "Sedimentation":
            sor = up["surface_overflow_rate_m_h"]
            coag_bonus = 1.0 if state["coag_destabilized"] else 0.45
            settling_eff = coag_bonus * max(0.25, min(0.94, 1.02 - 0.16 * sor))
            state["turbidity_NTU"] = max(0.4, state["turbidity_NTU"] * (1.0 - settling_eff))
            state["iron_mg_L"] *= max(0.15, 1.0 - 0.72 * settling_eff)
            state["sludge_kg_day"] += 0.4 * state["turbidity_NTU"] * unit_flow * 1e-3
            # Footprint and CAPEX scale inversely with SOR
            area_m2 = (unit_flow / 24.0) / max(0.4, sor)
            unit_footprint = max(8.0, area_m2 * 1.25)
            unit_capex = spec.base_capex_usd + area_m2 * 1350.0
            unit_extra = {"surface_area_m2": round(area_m2, 2), "settling_efficiency": round(settling_eff, 4)}

        elif unit_name == "Lime Softening":
            lime_dose = up["lime_dose_mg_L"]
            target_ph = up["target_ph"]
            ph_gain = max(0.2, min(1.0, (target_ph - 8.5) / 2.2))
            soft_eff = (1.0 - math.exp(-0.012 * lime_dose)) * ph_gain
            state["hardness_mg_L"] = max(35.0, state["hardness_mg_L"] * (1.0 - 0.82 * soft_eff))
            state["silica_mg_L"] = max(3.0, state["silica_mg_L"] * (1.0 - 0.55 * soft_eff))
            state["arsenic_ug_L"] *= max(0.25, 1.0 - 0.50 * soft_eff)
            state["lead_ug_L"] *= max(0.15, 1.0 - 0.75 * soft_eff)
            state["fluoride_mg_L"] *= max(0.40, 1.0 - 0.40 * soft_eff)
            state["pH"] = min(target_ph, 8.3) if "Reverse Osmosis" in ordered[idx + 1 :] else target_ph
            state["sludge_kg_day"] += 1.4 * lime_dose * unit_flow * 1e-3
            unit_chem_usd_yr = (lime_dose * 1e-3) * unit_flow * 365.0 * CHEMICAL_PRICES_USD_PER_KG["lime"]
            total_chem_dose_mg_L += lime_dose
            unit_power_kw = 0.05 * (unit_flow / 24.0)
            unit_extra = {"hardness_removal": round(0.82 * soft_eff, 4)}

        elif unit_name == "Media Filtration":
            rate = up["filtration_rate_m_h"]
            depth = up["bed_depth_m"]
            coag_bonus = 1.0 if state["coag_destabilized"] else 0.75
            filt_eff = coag_bonus * min(0.96, max(0.45, (1.0 - 0.024 * rate) * (0.82 + 0.14 * depth)))
            state["turbidity_NTU"] = max(0.12, state["turbidity_NTU"] * (1.0 - filt_eff))
            state["iron_mg_L"] = max(0.03, state["iron_mg_L"] * (1.0 - 0.80 * filt_eff))
            state["lead_ug_L"] *= max(0.35, 1.0 - 0.45 * filt_eff)
            if state["coag_destabilized"]:
                state["arsenic_ug_L"] *= max(0.25, 1.0 - 0.35 * filt_eff)
            bed_area = (unit_flow / 24.0) / rate
            unit_footprint = max(5.0, bed_area * 1.4)
            unit_capex = spec.base_capex_usd + bed_area * 1850.0 * (0.7 + 0.3 * depth)
            unit_power_kw = (0.04 + 0.004 * rate * depth) * (unit_flow / 24.0)
            state["coag_destabilized"] = False
            unit_extra = {"filter_area_m2": round(bed_area, 2), "turbidity_removal": round(filt_eff, 4)}

        elif unit_name == "Ultrafiltration":
            flux = up["flux_lmh"]
            rec = up["recovery"]
            tmp = up["transmembrane_pressure_bar"]
            if state["turbidity_NTU"] > 25.0:
                _add_violation(
                    violations,
                    category="integrity",
                    code="SIM-UF-FOUL",
                    severity="hard",
                    unit=unit_name,
                    metric="inlet_turbidity_NTU",
                    actual=state["turbidity_NTU"],
                    limit=25.0,
                    rel_excess=(state["turbidity_NTU"] - 25.0) / 25.0,
                    message=f"UF inlet turbidity ({state['turbidity_NTU']:.1f} NTU) exceeds 25 NTU limit without upstream clarification.",
                )
            area_m2 = (unit_flow * 1000.0 / 24.0) / flux
            permeate_flow = unit_flow * rec
            reject_flow = unit_flow - permeate_flow
            state["flow_m3_day"] = permeate_flow
            state["sludge_kg_day"] += reject_flow * state["turbidity_NTU"] * 0.002
            state["turbidity_NTU"] = min(0.08, state["turbidity_NTU"] * 0.02)
            state["toc_mg_L"] *= 0.80
            state["iron_mg_L"] = min(0.05, state["iron_mg_L"] * 0.15)
            state["disinfection_log_reduction"] += 4.0
            state["coag_destabilized"] = False
            unit_power_kw = (unit_flow / 24.0 / 3600.0) * (tmp * 1e5) / 0.78 / 1000.0
            unit_capex = spec.base_capex_usd + area_m2 * 95.0
            total_media_mem_opex_usd_yr += area_m2 * 14.0
            unit_footprint = max(6.0, area_m2 * 0.035)
            unit_extra = {"membrane_area_m2": round(area_m2, 2), "recovery": round(rec, 4)}

        elif unit_name == "Pumping":
            p_target = up["feed_pressure_bar"]
            eta = up["pump_efficiency"]
            dp_bar = max(0.5, p_target - state["pressure_bar"])
            state["pressure_bar"] = p_target
            unit_power_kw = ((unit_flow / 24.0 / 3600.0) * (dp_bar * 1e5) / eta) / 1000.0
            unit_capex = spec.base_capex_usd + (unit_flow * (0.25 + 0.015 * p_target)) * 120.0
            unit_extra = {"outlet_pressure_bar": round(p_target, 3), "pump_power_kW": round(unit_power_kw, 3)}

        elif unit_name in ("Reverse Osmosis", "Nanofiltration"):
            is_ro = unit_name == "Reverse Osmosis"
            rec = up["recovery"]
            p_unit = up["feed_pressure_bar"]
            p_feed = state["pressure_bar"] if state["pressure_bar"] >= 3.0 else p_unit
            if state["pressure_bar"] < 3.0:
                _add_violation(
                    violations,
                    category="integrity",
                    code="SIM-MEM-PUMP",
                    severity="hard",
                    unit=unit_name,
                    metric="inlet_pressure_bar",
                    actual=state["pressure_bar"],
                    limit=3.0,
                    rel_excess=(3.0 - state["pressure_bar"]) / 3.0,
                    message=f"{unit_name} requires an upstream Pumping stage to pressurize feed above 3 bar.",
                )
            else:
                # Allow parameter optimizer tuning feed_pressure_bar directly on pump or membrane coherently
                p_feed = max(state["pressure_bar"], p_unit) if "Pumping" not in ordered[:idx] else state["pressure_bar"]

            # Fouling check
            turb_limit = 1.0 if is_ro else 1.5
            if state["turbidity_NTU"] > turb_limit:
                _add_violation(
                    violations,
                    category="integrity",
                    code="SIM-MEM-FOUL-TURB",
                    severity="hard",
                    unit=unit_name,
                    metric="inlet_turbidity_NTU",
                    actual=state["turbidity_NTU"],
                    limit=turb_limit,
                    rel_excess=(state["turbidity_NTU"] - turb_limit) / turb_limit,
                    message=f"{unit_name} inlet turbidity ({state['turbidity_NTU']:.2f} NTU) exceeds {turb_limit} NTU membrane fouling threshold; add filtration/UF pretreatment.",
                )
            if state["iron_mg_L"] > 0.30:
                _add_violation(
                    violations,
                    category="integrity",
                    code="SIM-MEM-FOUL-FE",
                    severity="hard",
                    unit=unit_name,
                    metric="inlet_iron_mg_L",
                    actual=state["iron_mg_L"],
                    limit=0.30,
                    rel_excess=(state["iron_mg_L"] - 0.30) / 0.30,
                    message=f"{unit_name} inlet iron ({state['iron_mg_L']:.2f} mg/L) risks iron fouling; add oxidation/filtration pretreatment.",
                )

            # Scaling check
            cf = 1.0 / max(0.05, 1.0 - rec)
            brine_hardness = state["hardness_mg_L"] * cf
            hardness_limit = 1250.0 if state["tds_mg_L"] > 10000.0 else (800.0 if is_ro else 950.0)
            if brine_hardness > hardness_limit:
                _add_violation(
                    violations,
                    category="integrity",
                    code="SIM-MEM-SCALE-HARD",
                    severity="hard",
                    unit=unit_name,
                    metric="brine_hardness_mg_L",
                    actual=brine_hardness,
                    limit=hardness_limit,
                    rel_excess=(brine_hardness - hardness_limit) / hardness_limit,
                    message=f"{unit_name} brine hardness ({brine_hardness:.0f} mg/L at R={rec:.2f}) exceeds scaling threshold ({hardness_limit:.0f} mg/L); lower recovery or add Lime Softening.",
                )
            brine_silica = state["silica_mg_L"] * cf
            if brine_silica > 150.0:
                _add_violation(
                    violations,
                    category="integrity",
                    code="SIM-MEM-SCALE-SI",
                    severity="hard",
                    unit=unit_name,
                    metric="brine_silica_mg_L",
                    actual=brine_silica,
                    limit=150.0,
                    rel_excess=(brine_silica - 150.0) / 150.0,
                    message=f"{unit_name} brine silica ({brine_silica:.1f} mg/L) exceeds 150 mg/L amorphous silica limit; lower recovery or soften.",
                )

            # Solution-diffusion osmotic & flux physics
            pi_feed = 0.00078 * state["tds_mg_L"] * ((temp_c + 273.15) / 298.15)
            cp_mod = 1.12
            pi_avg = pi_feed * (0.5 + 0.5 * cf) * cp_mod
            dp_ret = 2.0
            p_perm = 1.01325
            ndp_bar = p_feed - 0.5 * dp_ret - p_perm - pi_avg
            if ndp_bar < 0.8:
                _add_violation(
                    violations,
                    category="integrity",
                    code="SIM-MEM-NDP",
                    severity="hard",
                    unit=unit_name,
                    metric="net_driving_pressure_bar",
                    actual=ndp_bar,
                    limit=0.8,
                    rel_excess=(0.8 - ndp_bar) / max(1.0, pi_avg),
                    message=f"{unit_name} net driving pressure ({ndp_bar:.2f} bar) is below 0.8 bar minimum at feed pressure {p_feed:.1f} bar and recovery {rec:.2f}; increase feed pressure or reduce recovery.",
                )

            a_coeff = 4.2e-12 if is_ro else 1.1e-11
            ndp_eff_pa = max(0.3e5, ndp_bar * 1e5)
            flux_lmh = min(45.0 if is_ro else 55.0, a_coeff * ndp_eff_pa * 3.6e6)
            perm_flow = unit_flow * rec
            brine_flow = unit_flow - perm_flow
            area_m2 = (perm_flow * 1000.0 / 24.0) / max(1.0, flux_lmh)

            # Rejection modeled via water flux vs solute permeability B
            # Higher flux / NDP improves rejection; higher recovery increases average retentate concentration
            conc_factor_avg = 0.45 + 0.55 * cf
            if is_ro:
                b_nacl = 3.5e-8
                jw_ms = flux_lmh / 3.6e6
                salt_passage = min(0.25, (b_nacl * conc_factor_avg) / (jw_ms + b_nacl))
                tds_rej = 1.0 - salt_passage
                state["tds_mg_L"] *= 1.0 - tds_rej
                state["hardness_mg_L"] *= 0.015 * conc_factor_avg
                state["toc_mg_L"] *= 0.03
                state["nitrate_mg_L"] *= min(0.22, 0.045 * conc_factor_avg)
                state["fluoride_mg_L"] *= min(0.18, 0.035 * conc_factor_avg)
                state["lead_ug_L"] *= 0.01
                state["silica_mg_L"] *= 0.02
                as_rej = (1.0 - state["arsenic_iii_frac"]) * 0.97 + state["arsenic_iii_frac"] * 0.55
                state["arsenic_ug_L"] *= 1.0 - as_rej
                boron_rej = 0.72 + (0.14 if state["pH"] >= 8.5 else 0.0)
                state["boron_mg_L"] *= 1.0 - boron_rej
                state["disinfection_log_reduction"] += 4.0
            else:
                b_nf = 2.5e-7
                jw_ms = flux_lmh / 3.6e6
                tds_rej = max(0.35, min(0.78, 1.0 - (b_nf * conc_factor_avg) / (jw_ms + b_nf)))
                state["tds_mg_L"] *= 1.0 - tds_rej
                state["hardness_mg_L"] *= min(0.25, 0.06 * conc_factor_avg)
                state["toc_mg_L"] *= 0.08
                state["nitrate_mg_L"] *= 0.65
                state["fluoride_mg_L"] *= 0.30
                state["lead_ug_L"] *= 0.05
                state["silica_mg_L"] *= 0.35
                as_rej = (1.0 - state["arsenic_iii_frac"]) * 0.92 + state["arsenic_iii_frac"] * 0.30
                state["arsenic_ug_L"] *= 1.0 - as_rej
                state["boron_mg_L"] *= 0.65
                state["disinfection_log_reduction"] += 3.0

            state["turbidity_NTU"] = min(0.05, state["turbidity_NTU"] * 0.02)
            state["iron_mg_L"] = min(0.02, state["iron_mg_L"] * 0.05)
            state["flow_m3_day"] = perm_flow
            state["brine_flow_m3_day"] += brine_flow
            state["brine_pressure_bar"] = max(1.0, p_feed - dp_ret)
            state["brine_tds_mg_L"] = inlet_snapshot["tds_mg_L"] * cf
            state["pressure_bar"] = 1.2
            unit_capex = spec.base_capex_usd + area_m2 * (72.0 if is_ro else 62.0) + unit_flow * 85.0
            total_media_mem_opex_usd_yr += area_m2 * 16.0
            unit_footprint = max(8.0, area_m2 * 0.022)
            unit_extra = {
                "recovery": round(rec, 4),
                "feed_pressure_bar": round(p_feed, 3),
                "osmotic_pressure_avg_bar": round(pi_avg, 3),
                "net_driving_pressure_bar": round(ndp_bar, 3),
                "flux_lmh": round(flux_lmh, 2),
                "membrane_area_m2": round(area_m2, 2),
                "brine_flow_m3_day": round(brine_flow, 2),
            }

        elif unit_name == "Energy Recovery":
            eta_erd = up["erd_efficiency"]
            if state["brine_flow_m3_day"] <= 0.0 or state["brine_pressure_bar"] <= 1.5:
                _add_violation(
                    violations,
                    category="integrity",
                    code="SIM-ERD-NOBRINE",
                    severity="warning",
                    unit=unit_name,
                    metric="brine_energy_available",
                    actual=state["brine_pressure_bar"],
                    limit=1.5,
                    rel_excess=0.25,
                    message="Energy Recovery has no pressurized membrane concentrate stream upstream.",
                )
            else:
                q_m3s = state["brine_flow_m3_day"] / 24.0 / 3600.0
                dp_pa = (state["brine_pressure_bar"] - 1.2) * 1e5
                rec_kw = (q_m3s * dp_pa * eta_erd) / 1000.0
                recovered_power_kw += rec_kw
                state["brine_pressure_bar"] = 1.2
                unit_extra = {"recovered_power_kW": round(rec_kw, 3)}

        elif unit_name == "Adsorption":
            ebct = up["ebct_min"]
            repl_days = up["media_replacement_days"]
            if state["turbidity_NTU"] > 3.0:
                _add_violation(
                    violations,
                    category="integrity",
                    code="SIM-ADS-FOUL",
                    severity="hard",
                    unit=unit_name,
                    metric="inlet_turbidity_NTU",
                    actual=state["turbidity_NTU"],
                    limit=3.0,
                    rel_excess=(state["turbidity_NTU"] - 3.0) / 3.0,
                    message=f"Adsorption bed inlet turbidity ({state['turbidity_NTU']:.2f} NTU) exceeds 3.0 NTU; add Media Filtration upstream.",
                )
            # Competing ions / pH / speciation effects
            comp_penalty = 1.0 / (1.0 + 0.045 * state["toc_mg_L"] + 0.008 * max(0.0, state["silica_mg_L"] - 15.0))
            ph_penalty = 1.0 if state["pH"] <= 8.0 else max(0.45, 1.0 - 0.18 * (state["pH"] - 8.0))
            freshness = max(0.75, min(1.02, 1.02 - 0.00020 * max(0.0, repl_days - 120.0)))
            kinetic = 1.0 - math.exp(-0.24 * ebct * comp_penalty)
            as_v_eff = min(0.985, kinetic * ph_penalty * freshness)
            as_iii_eff = 0.25 * kinetic
            as_rem = (1.0 - state["arsenic_iii_frac"]) * as_v_eff + state["arsenic_iii_frac"] * as_iii_eff
            state["arsenic_ug_L"] *= max(0.01, 1.0 - as_rem)
            state["toc_mg_L"] *= max(0.15, 1.0 - 0.80 * (1.0 - math.exp(-0.18 * ebct)) * freshness)
            state["fluoride_mg_L"] *= max(0.10, 1.0 - 0.88 * kinetic * ph_penalty * freshness)
            state["lead_ug_L"] *= max(0.03, 1.0 - 0.965 * kinetic * freshness)

            bed_vol_m3 = (unit_flow / 24.0 / 60.0) * ebct
            unit_capex = spec.base_capex_usd + bed_vol_m3 * 3800.0
            unit_footprint = max(5.0, bed_vol_m3 * 0.9)
            unit_power_kw = 0.025 * (unit_flow / 24.0)
            media_changes_yr = 365.0 / max(60.0, repl_days)
            total_media_mem_opex_usd_yr += bed_vol_m3 * 1650.0 * media_changes_yr
            unit_extra = {
                "bed_volume_m3": round(bed_vol_m3, 2),
                "arsenic_removal_eff": round(as_rem, 4),
            }

        elif unit_name == "Ion Exchange":
            ebct = up["ebct_min"]
            regen_bv = up["regeneration_bv"]
            if state["turbidity_NTU"] > 2.0:
                _add_violation(
                    violations,
                    category="integrity",
                    code="SIM-IX-FOUL",
                    severity="hard",
                    unit=unit_name,
                    metric="inlet_turbidity_NTU",
                    actual=state["turbidity_NTU"],
                    limit=2.0,
                    rel_excess=(state["turbidity_NTU"] - 2.0) / 2.0,
                    message=f"Ion Exchange resin inlet turbidity ({state['turbidity_NTU']:.2f} NTU) exceeds 2.0 NTU; add Media Filtration upstream.",
                )
            tds_comp = 1.0 / (1.0 + 0.0004 * state["tds_mg_L"])
            regen_factor = max(0.55, min(1.0, 1.08 - 0.00065 * regen_bv))
            ix_eff = (1.0 - math.exp(-0.32 * ebct)) * tds_comp * regen_factor
            state["nitrate_mg_L"] *= max(0.04, 1.0 - 0.94 * ix_eff)
            state["hardness_mg_L"] *= max(0.05, 1.0 - 0.93 * ix_eff)
            state["arsenic_ug_L"] *= max(0.06, 1.0 - (1.0 - state["arsenic_iii_frac"]) * 0.92 * ix_eff)
            state["fluoride_mg_L"] *= max(0.15, 1.0 - 0.80 * ix_eff)
            state["lead_ug_L"] *= max(0.08, 1.0 - 0.90 * ix_eff)
            regen_brine = unit_flow / max(80.0, regen_bv) * 2.5
            state["flow_m3_day"] = max(1.0, unit_flow - regen_brine)
            state["brine_flow_m3_day"] += regen_brine
            bed_vol_m3 = (unit_flow / 24.0 / 60.0) * ebct
            unit_capex = spec.base_capex_usd + bed_vol_m3 * 4500.0
            unit_footprint = max(5.0, bed_vol_m3 * 0.85)
            unit_power_kw = 0.03 * (unit_flow / 24.0)
            total_media_mem_opex_usd_yr += bed_vol_m3 * 1200.0
            unit_chem_usd_yr = regen_brine * 365.0 * 1.10  # salt regenerant
            unit_extra = {"regen_brine_m3_day": round(regen_brine, 2), "ix_efficiency": round(ix_eff, 4)}

        elif unit_name == "Advanced Oxidation":
            uv_dose = up["uv_dose_mj_cm2"]
            h2o2 = up["h2o2_dose_mg_L"]
            if state["turbidity_NTU"] > 2.5:
                _add_violation(
                    violations,
                    category="integrity",
                    code="SIM-AOP-UVT",
                    severity="hard",
                    unit=unit_name,
                    metric="inlet_turbidity_NTU",
                    actual=state["turbidity_NTU"],
                    limit=2.5,
                    rel_excess=(state["turbidity_NTU"] - 2.5) / 2.5,
                    message=f"AOP inlet turbidity ({state['turbidity_NTU']:.2f} NTU) blocks UV transmittance; add filtration pretreatment.",
                )
            uvt_penalty = 1.0 / (1.0 + 0.12 * state["turbidity_NTU"] + 0.05 * state["toc_mg_L"])
            aop_eff = 1.0 - math.exp(-0.00085 * uv_dose * (h2o2 ** 0.55) * uvt_penalty)
            state["toc_mg_L"] *= max(0.08, 1.0 - 0.88 * aop_eff)
            state["arsenic_iii_frac"] *= max(0.02, 1.0 - 0.96 * aop_eff)
            state["disinfection_log_reduction"] += 4.5
            unit_power_kw = (0.0018 * uv_dose) * (unit_flow / 24.0)
            unit_chem_usd_yr = (h2o2 * 1e-3) * unit_flow * 365.0 * CHEMICAL_PRICES_USD_PER_KG["h2o2"]
            total_chem_dose_mg_L += h2o2
            unit_extra = {"aop_destruction_eff": round(aop_eff, 4)}

        elif unit_name == "UV Disinfection":
            uv_dose = up["uv_dose_mj_cm2"]
            if state["turbidity_NTU"] > 3.0:
                _add_violation(
                    violations,
                    category="integrity",
                    code="SIM-UV-TURB",
                    severity="hard",
                    unit=unit_name,
                    metric="inlet_turbidity_NTU",
                    actual=state["turbidity_NTU"],
                    limit=3.0,
                    rel_excess=(state["turbidity_NTU"] - 3.0) / 3.0,
                    message=f"UV Disinfection inlet turbidity ({state['turbidity_NTU']:.2f} NTU) exceeds 3.0 NTU; add upstream filtration.",
                )
            uvt_factor = max(0.35, 1.0 / (1.0 + 0.25 * state["turbidity_NTU"] + 0.04 * state["toc_mg_L"]))
            log_red = 0.105 * uv_dose * uvt_factor
            state["disinfection_log_reduction"] += min(6.0, log_red)
            unit_power_kw = (0.0009 * uv_dose) * (unit_flow / 24.0)
            unit_extra = {"uv_log_reduction": round(min(6.0, log_red), 3), "uvt_factor": round(uvt_factor, 3)}

        elif unit_name == "Chlorination":
            dose = up["chlorine_dose_mg_L"]
            ct_min = up["contact_time_min"]
            if state["toc_mg_L"] > 3.5:
                _add_violation(
                    violations,
                    category="water_quality",
                    code="WQ-DBP-001",
                    severity="hard",
                    unit=unit_name,
                    metric="toc_before_chlorination_mg_L",
                    actual=state["toc_mg_L"],
                    limit=3.5,
                    rel_excess=(state["toc_mg_L"] - 3.5) / 3.5,
                    message=f"High TOC ({state['toc_mg_L']:.2f} mg/L) entering Chlorination creates DBP risk; add NOM removal (Coagulation/Adsorption/NF) or use UV Disinfection.",
                )
            demand = 0.35 * state["toc_mg_L"] + 0.4 * state["iron_mg_L"]
            free_cl2 = max(0.05, dose - demand)
            ct_val = free_cl2 * ct_min
            log_red = min(6.0, ct_val / 7.5)
            state["disinfection_log_reduction"] += log_red
            unit_chem_usd_yr = (dose * 1e-3) * unit_flow * 365.0 * CHEMICAL_PRICES_USD_PER_KG["chlorine"]
            total_chem_dose_mg_L += dose
            unit_footprint = max(4.0, (unit_flow / 24.0 / 60.0) * ct_min * 0.35)
            unit_extra = {"free_chlorine_mg_L": round(free_cl2, 3), "ct_mg_min_L": round(ct_val, 2), "ct_log_reduction": round(log_red, 3)}

        elif unit_name == "Brine Concentrator":
            c_rec = up["concentrate_recovery"]
            if state["brine_flow_m3_day"] <= 0.0:
                _add_violation(
                    violations,
                    category="integrity",
                    code="SIM-BC-NOBRINE",
                    severity="warning",
                    unit=unit_name,
                    metric="inlet_brine_flow",
                    actual=0.0,
                    limit=1.0,
                    rel_excess=0.2,
                    message="Brine Concentrator has no upstream concentrate stream to treat.",
                )
            else:
                brine_in = state["brine_flow_m3_day"]
                distillate = brine_in * c_rec
                residual_brine = brine_in - distillate
                state["flow_m3_day"] += distillate
                state["brine_flow_m3_day"] = residual_brine
                state["sludge_kg_day"] += residual_brine * state["brine_tds_mg_L"] * 1e-3
                # Distillate dilutes product slightly (essentially pure water)
                blend_ratio = distillate / max(1.0, state["flow_m3_day"])
                for k in ("tds_mg_L", "hardness_mg_L", "nitrate_mg_L", "arsenic_ug_L", "fluoride_mg_L", "toc_mg_L"):
                    state[k] *= max(0.0, 1.0 - 0.98 * blend_ratio)
                unit_power_kw = 18.0 * (brine_in / 24.0)  # MVC brine concentration ~18 kWh/m3 brine
                unit_capex = spec.base_capex_usd + brine_in * 420.0
                unit_footprint = max(8.0, brine_in * 0.06)
                unit_extra = {"distillate_recovered_m3_day": round(distillate, 2), "residual_brine_m3_day": round(residual_brine, 2)}

        total_power_kw += unit_power_kw
        total_capex_usd += unit_capex
        total_chem_opex_usd_yr += unit_chem_usd_yr
        total_footprint_m2 += unit_footprint

        unit_reports.append(
            {
                "unit": unit_name,
                "stage": spec.stage,
                "parameters": up,
                "power_kW": round(unit_power_kw, 3),
                "capex_usd": round(unit_capex, 2),
                "footprint_m2": round(unit_footprint, 2),
                "outlet_tds_mg_L": round(state["tds_mg_L"], 2),
                "outlet_turbidity_NTU": round(state["turbidity_NTU"], 3),
                "outlet_arsenic_ug_L": round(state["arsenic_ug_L"], 3),
                "metrics": unit_extra,
            }
        )

    # ---- Totals & Economics ----
    net_power_kw = max(0.05, total_power_kw - recovered_power_kw)
    product_flow = max(0.1, state["flow_m3_day"])
    overall_recovery = min(1.0, product_flow / flow_in)
    sec_kwh_m3 = (net_power_kw * 24.0) / product_flow

    annualized_capex = total_capex_usd * CAPITAL_RECOVERY_FACTOR
    elec_opex = net_power_kw * 24.0 * 365.0 * ELECTRICITY_USD_PER_KWH
    fixed_om = total_capex_usd * FIXED_OM_FRACTION
    brine_opex = state["brine_flow_m3_day"] * 365.0 * BRINE_DISPOSAL_USD_PER_M3
    sludge_opex = state["sludge_kg_day"] * 365.0 * SLUDGE_DISPOSAL_USD_PER_KG
    total_opex_usd_yr = elec_opex + total_chem_opex_usd_yr + total_media_mem_opex_usd_yr + fixed_om + brine_opex + sludge_opex
    lcow_usd_m3 = (annualized_capex + total_opex_usd_yr) / (product_flow * 365.0)

    # ---- Constraint Checks ----
    # 1. Water quality endpoints
    for field_name, limit_val in cfg["wq_limits"].items():
        actual_val = float(state.get(field_name, 0.0))
        if actual_val > limit_val + 1e-9:
            _add_violation(
                violations,
                category="water_quality",
                code=f"WQ-{field_name.upper()}",
                severity="hard",
                unit=None,
                metric=field_name,
                actual=actual_val,
                limit=limit_val,
                rel_excess=(actual_val - limit_val) / max(1.0, limit_val),
                message=f"Effluent {field_name} ({actual_val:.3g}) exceeds target limit ({limit_val:.3g}).",
            )

    if cfg["min_disinfection_log"] > 0:
        has_disinfection = any(UNIT_SPECS[u].provides_disinfection for u in ordered)
        if not has_disinfection:
            _add_violation(
                violations,
                category="water_quality",
                code="WQ-DISINF-UNIT",
                severity="hard",
                unit=None,
                metric="disinfection_barrier",
                actual=False,
                limit=True,
                rel_excess=1.0,
                message="Drinking/pathogen-controlled train lacks a dedicated disinfection unit (Chlorination, UV Disinfection, or AOP).",
            )
        if state["disinfection_log_reduction"] < cfg["min_disinfection_log"] - 1e-6:
            _add_violation(
                violations,
                category="water_quality",
                code="WQ-DISINF-LOG",
                severity="hard",
                unit=None,
                metric="disinfection_log_reduction",
                actual=state["disinfection_log_reduction"],
                limit=cfg["min_disinfection_log"],
                rel_excess=(cfg["min_disinfection_log"] - state["disinfection_log_reduction"]) / cfg["min_disinfection_log"],
                message=f"Cumulative disinfection ({state['disinfection_log_reduction']:.2f}-log) is below {cfg['min_disinfection_log']:.1f}-log requirement.",
            )

    # 2. Resource constraints
    brine_frac = state["brine_flow_m3_day"] / flow_in
    if not cfg["brine_disposal_allowed"] and brine_frac > 0.05:
        _add_violation(
            violations,
            category="resource",
            code="RES-BRINE-001",
            severity="hard",
            unit=None,
            metric="brine_fraction",
            actual=brine_frac,
            limit=0.05,
            rel_excess=(brine_frac - 0.05) / 0.05,
            message=f"Reject brine fraction ({brine_frac:.1%}) violates no-brine-disposal constraint (>5% reject without Brine Concentrator or non-brine process).",
        )

    if overall_recovery < cfg["min_recovery"] - 1e-6:
        _add_violation(
            violations,
            category="resource",
            code="RES-REC-001",
            severity="hard",
            unit=None,
            metric="recovery_fraction",
            actual=overall_recovery,
            limit=cfg["min_recovery"],
            rel_excess=(cfg["min_recovery"] - overall_recovery) / cfg["min_recovery"],
            message=f"Overall water recovery ({overall_recovery:.1%}) is below minimum requirement ({cfg['min_recovery']:.1%}).",
        )

    if sec_kwh_m3 > cfg["max_sec_kwh_m3"] + 1e-9:
        _add_violation(
            violations,
            category="resource",
            code="RES-SEC-001",
            severity="hard",
            unit=None,
            metric="specific_energy_kWh_m3",
            actual=sec_kwh_m3,
            limit=cfg["max_sec_kwh_m3"],
            rel_excess=(sec_kwh_m3 - cfg["max_sec_kwh_m3"]) / max(0.1, cfg["max_sec_kwh_m3"]),
            message=f"Specific energy ({sec_kwh_m3:.2f} kWh/m³) exceeds energy budget ({cfg['max_sec_kwh_m3']:.2f} kWh/m³).",
        )

    if total_footprint_m2 > cfg["max_footprint_m2"] + 1e-6:
        _add_violation(
            violations,
            category="resource",
            code="RES-FOOTPRINT-001",
            severity="hard",
            unit=None,
            metric="footprint_m2",
            actual=total_footprint_m2,
            limit=cfg["max_footprint_m2"],
            rel_excess=(total_footprint_m2 - cfg["max_footprint_m2"]) / cfg["max_footprint_m2"],
            message=f"Plant footprint ({total_footprint_m2:.1f} m²) exceeds site limit ({cfg['max_footprint_m2']:.1f} m²).",
        )

    # 3. Cost constraint
    if lcow_usd_m3 > cfg["max_lcow_usd_m3"] + 1e-9:
        _add_violation(
            violations,
            category="cost",
            code="COST-LCOW-001",
            severity="hard",
            unit=None,
            metric="lcow_usd_m3",
            actual=lcow_usd_m3,
            limit=cfg["max_lcow_usd_m3"],
            rel_excess=(lcow_usd_m3 - cfg["max_lcow_usd_m3"]) / max(0.1, cfg["max_lcow_usd_m3"]),
            message=f"Levelized cost of water (${lcow_usd_m3:.2f}/m³) exceeds budget ceiling (${cfg['max_lcow_usd_m3']:.2f}/m³).",
        )

    hard_violations = [v for v in violations if v["severity"] == "hard"]
    total_rel_violation = sum(v["rel_excess"] for v in hard_violations)
    feasible = len(hard_violations) == 0

    result: dict[str, Any] = {
        "kind": "hydroweaver.process-simulation",
        "feasible": feasible,
        "overall_status": "PASS" if feasible else "FAIL",
        "chain": ordered,
        "parameters": effective_params,
        "effluent": {
            "tds_mg_L": round(state["tds_mg_L"], 2),
            "turbidity_NTU": round(state["turbidity_NTU"], 3),
            "toc_mg_L": round(state["toc_mg_L"], 3),
            "arsenic_ug_L": round(state["arsenic_ug_L"], 3),
            "arsenic_iii_frac": round(state["arsenic_iii_frac"], 4),
            "nitrate_mg_L": round(state["nitrate_mg_L"], 3),
            "fluoride_mg_L": round(state["fluoride_mg_L"], 3),
            "hardness_mg_L": round(state["hardness_mg_L"], 2),
            "iron_mg_L": round(state["iron_mg_L"], 3),
            "lead_ug_L": round(state["lead_ug_L"], 3),
            "boron_mg_L": round(state["boron_mg_L"], 3),
            "silica_mg_L": round(state["silica_mg_L"], 2),
            "pH": round(state["pH"], 2),
            "disinfection_log_reduction": round(state["disinfection_log_reduction"], 3),
        },
        "flowsheet": {
            "feed_flow_m3_day": round(flow_in, 2),
            "product_flow_m3_day": round(product_flow, 2),
            "brine_flow_m3_day": round(state["brine_flow_m3_day"], 2),
            "brine_fraction": round(brine_frac, 4),
            "recovery_fraction": round(overall_recovery, 4),
            "gross_power_kW": round(total_power_kw, 3),
            "recovered_power_kW": round(recovered_power_kw, 3),
            "net_power_kW": round(net_power_kw, 3),
            "specific_energy_kWh_m3": round(sec_kwh_m3, 4),
            "footprint_m2": round(total_footprint_m2, 2),
            "total_chemical_dose_mg_L": round(total_chem_dose_mg_L, 2),
            "sludge_kg_day": round(state["sludge_kg_day"], 2),
        },
        "economics": {
            "capex_usd": round(total_capex_usd, 2),
            "annualized_capex_usd_yr": round(annualized_capex, 2),
            "opex_usd_yr": round(total_opex_usd_yr, 2),
            "electricity_opex_usd_yr": round(elec_opex, 2),
            "chemical_opex_usd_yr": round(total_chem_opex_usd_yr, 2),
            "media_membrane_opex_usd_yr": round(total_media_mem_opex_usd_yr, 2),
            "brine_sludge_opex_usd_yr": round(brine_opex + sludge_opex, 2),
            "lcow_usd_m3": round(lcow_usd_m3, 4),
        },
        "constraints": cfg,
        "units": unit_reports,
        "violations": violations,
        "hard_violation_count": len(hard_violations),
        "total_rel_violation": round(total_rel_violation, 5),
    }
    if watertap_result is not None:
        result["watertap_verification"] = watertap_result
    return result
