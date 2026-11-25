"""WaterTAP ASM1 and BSM2 mechanistic flowsheet simulation and NLP optimization.

Integrates upstream WaterTAP 1.8.0 activated-sludge (ASM1) and full-plant
water resource recovery facility (BSM2 = ASM1 + ADM1) flowsheets into
HydroWeaver's isolated simulation subprocess contract.
"""

from __future__ import annotations

import contextlib
import io
import logging
from typing import Any

ASM1_COMPONENTS: tuple[str, ...] = (
    "S_I",
    "S_S",
    "X_I",
    "X_S",
    "X_BH",
    "X_BA",
    "X_P",
    "S_O",
    "S_NO",
    "S_NH",
    "S_ND",
    "X_ND",
)


class WastewaterFlowsheetError(Exception):
    """Raised when an ASM1 or BSM2 flowsheet build or solve fails."""


@contextlib.contextmanager
def _suppress_watertap_output():
    """Keep stdout/stderr pure JSON while WaterTAP initialization prints progress."""
    buf_out = io.StringIO()
    buf_err = io.StringIO()
    loggers = [logging.getLogger(name) for name in ("", "idaes", "pyomo", "watertap")]
    prev_levels = [logger.level for logger in loggers]
    prev_disable = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    for logger in loggers:
        logger.setLevel(logging.CRITICAL)
    try:
        with contextlib.redirect_stdout(buf_out), contextlib.redirect_stderr(buf_err):
            yield
    finally:
        logging.disable(prev_disable)
        for logger, level in zip(loggers, prev_levels):
            logger.setLevel(level)


def _num(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    val = float(value)
    return val


def _extract_wastewater_options(
    payload: dict[str, Any],
    *,
    default_flow_m3_day: float,
    default_temp_k: float,
) -> dict[str, Any]:
    options = payload.get("options") if isinstance(payload.get("options"), dict) else {}
    case = payload.get("case") if isinstance(payload.get("case"), dict) else {}
    wq = case.get("water_quality") if isinstance(case.get("water_quality"), dict) else {}
    wq_extra = wq.get("extra") if isinstance(wq.get("extra"), dict) else {}
    targets = case.get("treatment_targets") if isinstance(case.get("treatment_targets"), dict) else {}
    t_extra = targets.get("extra") if isinstance(targets.get("extra"), dict) else {}
    constraints = case.get("constraints") if isinstance(case.get("constraints"), dict) else {}
    c_extra = constraints.get("extra") if isinstance(constraints.get("extra"), dict) else {}

    flow = _num(options.get("design_flow_m3_day")) or _num(c_extra.get("design_flow_m3_day"))
    flow_source = (
        "declared option design_flow_m3_day"
        if _num(options.get("design_flow_m3_day"))
        else "declared constraints.extra.design_flow_m3_day"
        if _num(c_extra.get("design_flow_m3_day"))
        else f"WaterTAP reference default ({default_flow_m3_day:g} m3/day)"
    )

    temp_c = _num(options.get("temperature_C")) or _num(wq.get("temperature_C"))
    temp_k = _num(options.get("temperature_K")) or ((temp_c + 273.15) if temp_c is not None else None)

    asm1_overrides: dict[str, float] = {}
    raw_asm1 = options.get("asm1_mg_L") or wq_extra.get("asm1_mg_L")
    if isinstance(raw_asm1, dict):
        for comp in ASM1_COMPONENTS:
            val = _num(raw_asm1.get(comp))
            if val is not None and val >= 0:
                asm1_overrides[comp] = val

    # Allow scalar NH4-N / NO3-N hints when an ASM1 vector is not explicitly provided.
    if not asm1_overrides:
        nh4 = _num(wq.get("nh4_mg_L")) or _num(wq_extra.get("nh4_mg_N_L"))
        if nh4 is not None and nh4 >= 0:
            asm1_overrides["S_NH"] = nh4
        no3 = _num(wq.get("no3_mg_L")) or _num(wq_extra.get("no3_mg_N_L"))
        if no3 is not None and no3 >= 0:
            asm1_overrides["S_NO"] = no3

    alkalinity = _num(options.get("alkalinity_mol_m3")) or _num(wq_extra.get("alkalinity_mol_m3"))

    do_setpoints = options.get("do_setpoints_mg_L")
    if not isinstance(do_setpoints, list):
        do_setpoints = None

    effluent_targets = {
        "cod_mg_L": _num(options.get("max_cod_mg_L")) or _num(targets.get("cod_mg_L")) or _num(t_extra.get("cod_mg_L")),
        "bod5_mg_L": _num(options.get("max_bod5_mg_L")) or _num(targets.get("bod5_mg_L")) or _num(t_extra.get("bod5_mg_L")),
        "tss_mg_L": _num(options.get("max_tss_mg_L")) or _num(targets.get("tss_mg_L")) or _num(t_extra.get("tss_mg_L")),
        "tn_mg_N_L": _num(options.get("max_tn_mg_N_L")) or _num(targets.get("tn_mg_L")) or _num(t_extra.get("tn_mg_N_L")),
        "nh4_mg_N_L": _num(options.get("max_nh4_mg_N_L")) or _num(targets.get("nh4_mg_L")) or _num(t_extra.get("nh4_mg_N_L")),
    }

    return {
        "flow_m3_day": flow if (flow and flow > 0) else default_flow_m3_day,
        "flow_source": flow_source,
        "has_custom_flow": bool(flow and flow > 0),
        "temperature_K": temp_k if temp_k is not None else default_temp_k,
        "has_custom_temp": temp_k is not None,
        "asm1_mg_L": asm1_overrides,
        "alkalinity_mol_m3": alkalinity,
        "n_anoxic": int(options["n_anoxic"]) if isinstance(options.get("n_anoxic"), int) else 2,
        "anoxic_volume_m3": _num(options.get("anoxic_volume_m3")),
        "aerobic_volume_m3": _num(options.get("aerobic_volume_m3")),
        "do_setpoints_mg_L": [float(v) for v in do_setpoints if _num(v) is not None] if do_setpoints else None,
        "kla_r3_h_inv": _num(options.get("kla_r3_h_inv")),
        "kla_r4_h_inv": _num(options.get("kla_r4_h_inv")),
        "internal_recycle_fraction": _num(options.get("internal_recycle_fraction")),
        "return_sludge_fraction": _num(options.get("return_sludge_fraction")),
        "ad_volume_liquid_m3": _num(options.get("ad_volume_liquid_m3")),
        "ad_temperature_K": _num(options.get("ad_temperature_K")),
        "effluent_targets": effluent_targets,
    }


def _extract_effluent_metrics(props_block: Any, pyo_mod: Any, *, clarifier_block: Any = None) -> dict[str, Any]:
    val = pyo_mod.value
    flow_m3_d = float(val(pyo_mod.units.convert(props_block.flow_vol, to_units=pyo_mod.units.m**3 / pyo_mod.units.day)))
    concs_mg_l = {
        comp: float(val(props_block.conc_mass_comp[comp])) * 1000.0
        for comp in ASM1_COMPONENTS
    }
    cod_mg_l = sum(concs_mg_l[c] for c in ("S_I", "S_S", "X_I", "X_S", "X_BH", "X_BA", "X_P"))
    tn_mg_n_l = (
        concs_mg_l["S_NH"]
        + concs_mg_l["S_NO"]
        + concs_mg_l["S_ND"]
        + concs_mg_l["X_ND"]
        + 0.08 * (concs_mg_l["X_BH"] + concs_mg_l["X_BA"])
        + 0.06 * (concs_mg_l["X_I"] + concs_mg_l["X_P"] + concs_mg_l["X_S"])
    )
    tss_mg_l = 0.75 * (
        concs_mg_l["X_I"] + concs_mg_l["X_S"] + concs_mg_l["X_BH"] + concs_mg_l["X_BA"] + concs_mg_l["X_P"]
    )
    bod5_mg_l = 0.25 * (concs_mg_l["S_S"] + concs_mg_l["X_S"] + 0.92 * (concs_mg_l["X_BH"] + concs_mg_l["X_BA"]))
    if clarifier_block is not None:
        try:
            eff_state = clarifier_block.effluent_state[0]
            if hasattr(eff_state, "COD"):
                cod_mg_l = float(val(eff_state.COD)) * 1000.0
            if hasattr(eff_state, "TSS"):
                tss_mg_l = float(val(eff_state.TSS)) * 1000.0
            if hasattr(eff_state, "Total_N"):
                tn_mg_n_l = float(val(eff_state.Total_N)) * 1000.0
            if hasattr(eff_state, "BOD5"):
                bod5_mg_l = float(val(eff_state.BOD5["effluent"])) * 1000.0
        except Exception:
            pass
    return {
        "product_flow_m3_day": round(flow_m3_d, 3),
        "cod_mg_L": round(cod_mg_l, 3),
        "bod5_mg_L": round(bod5_mg_l, 3),
        "tss_mg_L": round(tss_mg_l, 3),
        "tn_mg_N_L": round(tn_mg_n_l, 3),
        "nh4_mg_N_L": round(concs_mg_l["S_NH"], 3),
        "no3_mg_N_L": round(concs_mg_l["S_NO"], 3),
        "do_mg_L": round(concs_mg_l["S_O"], 3),
        "asm1_effluent_mg_L": {k: round(v, 4) for k, v in concs_mg_l.items()},
    }


def _solver_dict(results: Any) -> tuple[bool, dict[str, Any]]:
    termination = str(results.solver.termination_condition)
    status = str(results.solver.status)
    converged = "optimal" in termination.lower()
    try:
        iterations = int(results.solver.iterations)
    except Exception:
        iterations = None
    return converged, {
        "name": "ipopt",
        "status": status,
        "termination_condition": termination,
        "iterations": iterations,
        "message": str(getattr(results.solver, "message", "") or ""),
    }


def _apply_reactor_and_feed_overrides(m: Any, cfg: dict[str, Any], pyo_mod: Any, *, n_anoxic: int) -> None:
    if cfg["has_custom_flow"]:
        m.fs.FeedWater.flow_vol.fix(cfg["flow_m3_day"] * pyo_mod.units.m**3 / pyo_mod.units.day)
    if cfg["has_custom_temp"]:
        m.fs.FeedWater.temperature.fix(cfg["temperature_K"] * pyo_mod.units.K)
    for comp, val_mg_l in cfg["asm1_mg_L"].items():
        m.fs.FeedWater.conc_mass_comp[0, comp].fix(max(1e-6, val_mg_l) * pyo_mod.units.g / pyo_mod.units.m**3)
    if cfg["alkalinity_mol_m3"] is not None:
        m.fs.FeedWater.alkalinity.fix(cfg["alkalinity_mol_m3"] * pyo_mod.units.mol / pyo_mod.units.m**3)

    for idx in range(1, 6):
        reactor = getattr(m.fs, f"R{idx}")
        if idx <= n_anoxic and cfg["anoxic_volume_m3"] is not None:
            reactor.volume.fix(cfg["anoxic_volume_m3"] * pyo_mod.units.m**3)
        elif idx > n_anoxic and cfg["aerobic_volume_m3"] is not None:
            reactor.volume.fix(cfg["aerobic_volume_m3"] * pyo_mod.units.m**3)

    if cfg["internal_recycle_fraction"] is not None:
        m.fs.SP5.split_fraction[:, "underflow"].fix(cfg["internal_recycle_fraction"])
    if cfg["return_sludge_fraction"] is not None:
        m.fs.SP6.split_fraction[:, "recycle"].fix(cfg["return_sludge_fraction"])


def simulate_asm1(
    modeled: list[str],
    specs: list[Any],
    payload: dict[str, Any],
    *,
    optimize_design: bool = False,
) -> dict[str, Any]:
    """Run or NLP-optimize the WaterTAP ASM1 activated-sludge flowsheet."""
    try:
        import pyomo.environ as pyo
        from idaes.core.util.model_statistics import degrees_of_freedom
        from watertap.core.solvers import get_solver
        from watertap.flowsheets.activated_sludge import ASM1_flowsheet
    except Exception as error:
        raise WastewaterFlowsheetError(f"WaterTAP ASM1 import failed: {type(error).__name__}: {error}") from error

    cfg = _extract_wastewater_options(payload, default_flow_m3_day=18446.0, default_temp_k=298.15)
    try:
        with _suppress_watertap_output():
            m, results = ASM1_flowsheet.build_flowsheet()
            _apply_reactor_and_feed_overrides(m, cfg, pyo, n_anoxic=2)

            if cfg["kla_r3_h_inv"] is not None:
                m.fs.R3.KLa.fix(cfg["kla_r3_h_inv"])
            if cfg["kla_r4_h_inv"] is not None:
                m.fs.R4.KLa.fix(cfg["kla_r4_h_inv"])
            if cfg["do_setpoints_mg_L"]:
                do_list = cfg["do_setpoints_mg_L"]
                if len(do_list) >= 1 and cfg["kla_r3_h_inv"] is None:
                    m.fs.R3.KLa.unfix()
                    m.fs.R3.outlet.conc_mass_comp[:, "S_O"].fix(do_list[0] / 1000.0)
                if len(do_list) >= 2 and cfg["kla_r4_h_inv"] is None:
                    m.fs.R4.KLa.unfix()
                    m.fs.R4.outlet.conc_mass_comp[:, "S_O"].fix(do_list[1] / 1000.0)
                if len(do_list) >= 3:
                    m.fs.R5.outlet.conc_mass_comp[:, "S_O"].fix(do_list[2] / 1000.0)

            solver = get_solver()
            aeration_control = "fixed R3/R4 KLa=10 h^-1, R5 DO=0.449 mg/L"
            if optimize_design:
                for idx in range(1, 6):
                    reactor = getattr(m.fs, f"R{idx}")
                    reactor.volume.unfix()
                    reactor.volume.setlb(250.0)
                    reactor.volume.setub(4000.0)
                m.fs.R3.KLa.unfix()
                m.fs.R3.KLa.setlb(0.5)
                m.fs.R3.KLa.setub(20.0)
                m.fs.R4.KLa.unfix()
                m.fs.R4.KLa.setlb(0.5)
                m.fs.R4.KLa.setub(20.0)
                m.fs.SP5.split_fraction[:, "underflow"].unfix()
                m.fs.SP5.split_fraction[:, "underflow"].setlb(0.25)
                m.fs.SP5.split_fraction[:, "underflow"].setub(0.80)

                targets = cfg["effluent_targets"]
                eff_props = m.fs.Treated.properties[0]
                if targets["nh4_mg_N_L"] is not None:
                    eff_props.conc_mass_comp["S_NH"].setub(targets["nh4_mg_N_L"] / 1000.0)
                if targets["cod_mg_L"] is not None:
                    cod_expr = sum(eff_props.conc_mass_comp[c] for c in ("S_I", "S_S", "X_I", "X_S", "X_BH", "X_BA", "X_P"))
                    m.fs.asm1_cod_limit = pyo.Constraint(expr=cod_expr <= targets["cod_mg_L"] / 1000.0)
                if targets["tn_mg_N_L"] is not None:
                    tn_expr = (
                        eff_props.conc_mass_comp["S_NH"]
                        + eff_props.conc_mass_comp["S_NO"]
                        + eff_props.conc_mass_comp["S_ND"]
                        + eff_props.conc_mass_comp["X_ND"]
                        + 0.08 * (eff_props.conc_mass_comp["X_BH"] + eff_props.conc_mass_comp["X_BA"])
                        + 0.06 * (eff_props.conc_mass_comp["X_I"] + eff_props.conc_mass_comp["X_P"] + eff_props.conc_mass_comp["X_S"])
                    )
                    m.fs.asm1_tn_limit = pyo.Constraint(expr=tn_expr <= targets["tn_mg_N_L"] / 1000.0)

                vol_sum = sum(getattr(m.fs, f"R{idx}").volume[0] for idx in range(1, 6))
                m.fs.asm1_objective = pyo.Objective(
                    expr=(vol_sum / 1000.0) + 0.25 * (m.fs.R3.KLa + m.fs.R4.KLa),
                    sense=pyo.minimize,
                )
                results = solver.solve(m, tee=False)
                aeration_control = "NLP-optimized bioreactor volumes, R3/R4 KLa, and internal recycle"
            else:
                dof = degrees_of_freedom(m)
                if dof != 0:
                    raise WastewaterFlowsheetError(f"ASM1 flowsheet has {dof} degree(s) of freedom after fixation")
                has_overrides = any(
                    [
                        cfg["has_custom_flow"],
                        cfg["has_custom_temp"],
                        cfg["asm1_mg_L"],
                        cfg["alkalinity_mol_m3"] is not None,
                        cfg["anoxic_volume_m3"] is not None,
                        cfg["aerobic_volume_m3"] is not None,
                        cfg["kla_r3_h_inv"] is not None,
                        cfg["kla_r4_h_inv"] is not None,
                        cfg["do_setpoints_mg_L"] is not None,
                        cfg["internal_recycle_fraction"] is not None,
                        cfg["return_sludge_fraction"] is not None,
                    ]
                )
                if has_overrides:
                    results = solver.solve(m, tee=False)
                    if (
                        "optimal" not in str(results.solver.termination_condition).lower()
                        and cfg["kla_r3_h_inv"] is None
                        and cfg["kla_r4_h_inv"] is None
                        and cfg["do_setpoints_mg_L"] is None
                    ):
                        # Rebuild cleanly so restoration iterates do not pollute the DO-controlled re-solve.
                        m, _ = ASM1_flowsheet.build_flowsheet()
                        _apply_reactor_and_feed_overrides(m, cfg, pyo, n_anoxic=2)
                        m.fs.R3.KLa.unfix()
                        m.fs.R4.KLa.unfix()
                        m.fs.R3.outlet.conc_mass_comp[:, "S_O"].fix(2.0e-3)
                        m.fs.R4.outlet.conc_mass_comp[:, "S_O"].fix(2.0e-3)
                        m.fs.R5.outlet.conc_mass_comp[:, "S_O"].fix(2.0e-3)
                        results = solver.solve(m, tee=False)
                        aeration_control = "DO control (2.0 mg/L across R3-R5; KLa computed endogenously)"
    except WastewaterFlowsheetError:
        raise
    except Exception as error:
        raise WastewaterFlowsheetError(f"ASM1 build or solve failed: {type(error).__name__}: {error}") from error

    converged, solver_out = _solver_dict(results)
    flowsheet_out: dict[str, Any] = {}
    units_out: list[dict[str, Any]] = []
    if converged:
        eff_metrics = _extract_effluent_metrics(m.fs.Treated.properties[0], pyo)
        sludge_m3_d = float(
            pyo.value(pyo.units.convert(m.fs.Sludge.properties[0].flow_vol, to_units=pyo.units.m**3 / pyo.units.day))
        )
        total_vol = sum(float(pyo.value(getattr(m.fs, f"R{idx}").volume[0])) for idx in range(1, 6))
        flowsheet_out = {
            **eff_metrics,
            "sludge_waste_m3_day": round(sludge_m3_d, 3),
            "total_bioreactor_volume_m3": round(total_vol, 2),
            "R3_KLa_h_inv": round(float(pyo.value(m.fs.R3.KLa)), 3),
            "R4_KLa_h_inv": round(float(pyo.value(m.fs.R4.KLa)), 3),
            "internal_recycle_fraction": round(float(pyo.value(m.fs.SP5.split_fraction[0, "underflow"])), 4),
            "return_sludge_fraction": round(float(pyo.value(m.fs.SP6.split_fraction[0, "recycle"])), 4),
        }
        units_out = [
            {
                "unit": f"R{idx} ({'Anoxic' if idx <= 2 else 'Aerobic'})",
                "model": "watertap.flowsheets.activated_sludge.ASM1_flowsheet",
                "results": {
                    "volume_m3": round(float(pyo.value(getattr(m.fs, f"R{idx}").volume[0])), 2),
                    "outlet_DO_mg_L": round(float(pyo.value(getattr(m.fs, f"R{idx}").outlet.conc_mass_comp[0, "S_O"])) * 1000.0, 3),
                },
            }
            for idx in range(1, 6)
        ]
    else:
        flowsheet_out = {"note": "ASM1 solver did not converge; no flowsheet totals are reported"}

    return {
        "status": "optimal" if converged else "unconverged",
        "mode": "nlp-design-optimization" if optimize_design else "steady-state-simulation",
        "flowsheet_model": "ASM1",
        "property_package": "ASM1",
        "units": units_out if units_out else [{"unit": u, "model": s.model, "results": {}} for u, s in zip(modeled, specs)],
        "flowsheet": flowsheet_out,
        "solver": solver_out,
        "basis": {
            "design_flow_m3_day": cfg["flow_m3_day"],
            "design_flow_source": cfg["flow_source"],
            "temperature_K": cfg["temperature_K"],
            "aeration_control": aeration_control,
            "reactor_configuration": "2 anoxic CSTR + 3 aerobic CSTR_Injection + CL1 + recycle",
        },
    }


def _swap_bsm2_anoxic_reactor(m: Any, n_anoxic: int, pyo_mod: Any, CSTR_cls: Any, AerationTank_cls: Any, ElectricityConsumption_cls: Any, set_sf: Any, get_sf: Any) -> None:
    """Adjust anoxic reactor count (1, 2, or 3) while preserving BSM2 reaction scaling."""
    if n_anoxic == 2:
        return
    if n_anoxic not in (1, 3):
        raise WastewaterFlowsheetError(f"Unsupported BSM2 n_anoxic={n_anoxic}; expected 1, 2, or 3")
    idx = 2 if n_anoxic == 1 else 3
    name = f"R{idx}"
    adjacent = (f"stream{idx + 1}", f"stream{idx + 2}")
    for arc_name in adjacent:
        arc = getattr(m.fs, arc_name)
        if arc.expanded_block is not None:
            m.fs.del_component(arc.expanded_block)
    m.fs.del_component(getattr(m.fs, name))
    args = {"property_package": m.fs.props_ASM1, "reaction_package": m.fs.ASM1_rxn_props}
    new_unit = (
        AerationTank_cls(**args, electricity_consumption=ElectricityConsumption_cls.calculated)
        if n_anoxic == 1
        else CSTR_cls(**args)
    )
    setattr(m.fs, name, new_unit)
    rxn_sf = get_sf(m.fs.R1.control_volume.rate_reaction_extent[0, "R1"]) or 1e6
    for comp in new_unit.control_volume.rate_reaction_extent.index_set():
        set_sf(new_unit.control_volume.rate_reaction_extent[comp], rxn_sf)
    getattr(m.fs, adjacent[0]).set_value({"source": getattr(m.fs, f"R{idx - 1}").outlet, "destination": new_unit.inlet})
    getattr(m.fs, adjacent[1]).set_value({"source": new_unit.outlet, "destination": getattr(m.fs, f"R{idx + 1}").inlet})
    for arc_name in adjacent:
        getattr(m.fs, arc_name).activate()
    pyo_mod.TransformationFactory("network.expand_arcs").apply_to(m)


def simulate_bsm2(
    modeled: list[str],
    specs: list[Any],
    payload: dict[str, Any],
    *,
    optimize_design: bool = False,
) -> dict[str, Any]:
    """Run or NLP-optimize the WaterTAP BSM2 (ASM1 + ADM1) full-plant flowsheet."""
    try:
        import pyomo.environ as pyo
        from idaes.core.scaling import get_scaling_factor, set_scaling_factor
        from idaes.core.util.model_statistics import degrees_of_freedom
        from watertap.core.solvers import get_solver
        from watertap.flowsheets.full_water_resource_recovery_facility import BSM2
        from watertap.unit_models.aeration_tank import AerationTank, ElectricityConsumption
        from watertap.unit_models.cstr import CSTR
    except Exception as error:
        raise WastewaterFlowsheetError(f"WaterTAP BSM2 import failed: {type(error).__name__}: {error}") from error

    cfg = _extract_wastewater_options(payload, default_flow_m3_day=20648.0, default_temp_k=308.15)
    n_anoxic = cfg["n_anoxic"]
    try:
        with _suppress_watertap_output():
            m = BSM2.build()
            BSM2.set_operating_conditions(m)
            if n_anoxic != 2:
                _swap_bsm2_anoxic_reactor(
                    m,
                    n_anoxic,
                    pyo,
                    CSTR,
                    AerationTank,
                    ElectricityConsumption,
                    set_scaling_factor,
                    get_scaling_factor,
                )

            _apply_reactor_and_feed_overrides(m, cfg, pyo, n_anoxic=n_anoxic)

            # Configure aerobic DO setpoints for reactors idx > n_anoxic
            do_list = cfg["do_setpoints_mg_L"]
            for idx in range(1, 6):
                if idx > n_anoxic:
                    reactor = getattr(m.fs, f"R{idx}")
                    for comp in m.fs.props_ASM1.component_list:
                        if comp != "S_O":
                            reactor.injection[:, :, comp].fix(0)
                    reactor.injection[:, :, "S_O"].unfix()
                    reactor.KLa.unfix()
                    if do_list is not None:
                        pos = idx - n_anoxic - 1
                        if pos < len(do_list):
                            reactor.outlet.conc_mass_comp[:, "S_O"].fix(do_list[pos] / 1000.0)
                    elif idx == 2 and n_anoxic == 1:
                        reactor.outlet.conc_mass_comp[:, "S_O"].fix(2.0e-3)

            if cfg["ad_volume_liquid_m3"] is not None:
                m.fs.RADM.volume_liquid.fix(cfg["ad_volume_liquid_m3"])
            if cfg["ad_temperature_K"] is not None:
                m.fs.RADM.liquid_outlet.temperature.fix(cfg["ad_temperature_K"])

            BSM2.initialize_system(m)
            BSM2.add_costing(m)
            m.fs.costing.initialize()
            BSM2.scale_system(m)

            scaling = pyo.TransformationFactory("core.scale_model")
            scaled_model = scaling.create_using(m, rename=False)
            solver = get_solver()
            if not optimize_design:
                dof = degrees_of_freedom(scaled_model)
                if dof != 0:
                    raise WastewaterFlowsheetError(f"BSM2 flowsheet has {dof} degree(s) of freedom after fixation")
            results = solver.solve(scaled_model, tee=False)
            scaling.propagate_solution(scaled_model, m)

            if optimize_design:
                if n_anoxic == 2:
                    BSM2.setup_optimization(m, reactor_volume_equalities=True)
                else:
                    for idx in range(1, 6):
                        reactor = getattr(m.fs, f"R{idx}")
                        reactor.volume.unfix()
                        reactor.volume.setlb(1.0)
                        reactor.volume.setub(2000.0)
                        if idx > n_anoxic:
                            reactor.outlet.conc_mass_comp[:, "S_O"].unfix()
                            reactor.outlet.conc_mass_comp[:, "S_O"].setub(8.2e-3)
                    m.fs.SP5.split_fraction[:, "underflow"].unfix()
                    m.fs.SP6.split_fraction[:, "recycle"].unfix()
                    BSM2.add_effluent_violations(m)

                targets = cfg["effluent_targets"]
                if targets["cod_mg_L"] is not None:
                    m.fs.COD_max.fix(targets["cod_mg_L"] / 1000.0)
                if targets["tss_mg_L"] is not None:
                    m.fs.TSS_max.fix(targets["tss_mg_L"] / 1000.0)
                if targets["bod5_mg_L"] is not None:
                    m.fs.BOD5_max.fix(targets["bod5_mg_L"] / 1000.0)
                if targets["tn_mg_N_L"] is not None:
                    m.fs.totalN_max.fix(targets["tn_mg_N_L"] / 1000.0)

                BSM2.rescale_system(m)
                rescaling = pyo.TransformationFactory("core.scale_model")
                rescaled_model = rescaling.create_using(m, rename=False)
                results = solver.solve(rescaled_model, tee=False)
                rescaling.propagate_solution(rescaled_model, m)
    except WastewaterFlowsheetError:
        raise
    except Exception as error:
        raise WastewaterFlowsheetError(f"BSM2 build or solve failed: {type(error).__name__}: {error}") from error

    converged, solver_out = _solver_dict(results)
    flowsheet_out: dict[str, Any] = {}
    units_out: list[dict[str, Any]] = []
    if converged:
        eff_metrics = _extract_effluent_metrics(m.fs.Treated.properties[0], pyo, clarifier_block=m.fs.CL1)
        total_vol = sum(float(pyo.value(getattr(m.fs, f"R{idx}").volume[0])) for idx in range(1, 6))
        kla_vals = [
            float(pyo.value(getattr(m.fs, f"R{idx}").KLa))
            for idx in range(1, 6)
            if idx > n_anoxic and hasattr(getattr(m.fs, f"R{idx}"), "KLa")
        ]
        biogas_m3_d = float(
            pyo.value(pyo.units.convert(m.fs.RADM.vapor_outlet.flow_vol[0], to_units=pyo.units.m**3 / pyo.units.day))
        )
        flowsheet_out = {
            **eff_metrics,
            "total_bioreactor_volume_m3": round(total_vol, 2),
            "kla_max_h_inv": round(max(kla_vals), 3) if kla_vals else None,
            "biogas_flow_m3_day": round(biogas_m3_d, 2),
            "capex_usd": round(float(pyo.value(m.fs.costing.total_capital_cost)), 2),
            "opex_usd_yr": round(float(pyo.value(m.fs.costing.total_operating_cost)), 2),
            "lcow_usd_m3": round(float(pyo.value(m.fs.costing.LCOW)), 4),
            "watertap_sec_kWh_m3": round(float(pyo.value(m.fs.costing.specific_energy_consumption)), 4),
            "internal_recycle_fraction": round(float(pyo.value(m.fs.SP5.split_fraction[0, "underflow"])), 4),
            "return_sludge_fraction": round(float(pyo.value(m.fs.SP6.split_fraction[0, "recycle"])), 4),
        }
        units_out = [
            {
                "unit": f"R{idx} ({'Anoxic' if idx <= n_anoxic else 'Aerobic'})",
                "model": "watertap.flowsheets.full_water_resource_recovery_facility.BSM2",
                "results": {
                    "volume_m3": round(float(pyo.value(getattr(m.fs, f"R{idx}").volume[0])), 2),
                    "outlet_DO_mg_L": round(float(pyo.value(getattr(m.fs, f"R{idx}").outlet.conc_mass_comp[0, "S_O"])) * 1000.0, 3),
                },
            }
            for idx in range(1, 6)
        ] + [
            {
                "unit": "RADM (Anaerobic Digester ADM1)",
                "model": "watertap.unit_models.anaerobic_digester.AD",
                "results": {
                    "liquid_volume_m3": round(float(pyo.value(m.fs.RADM.volume_liquid[0])), 2),
                    "biogas_flow_m3_day": round(biogas_m3_d, 2),
                },
            }
        ]
    else:
        flowsheet_out = {"note": "BSM2 solver did not converge; no flowsheet totals are reported"}

    return {
        "status": "optimal" if converged else "unconverged",
        "mode": "nlp-design-optimization" if optimize_design else "steady-state-simulation",
        "flowsheet_model": "BSM2",
        "property_package": "ASM1_ADM1",
        "units": units_out if units_out else [{"unit": u, "model": s.model, "results": {}} for u, s in zip(modeled, specs)],
        "flowsheet": flowsheet_out,
        "solver": solver_out,
        "basis": {
            "design_flow_m3_day": cfg["flow_m3_day"],
            "design_flow_source": cfg["flow_source"],
            "temperature_K": cfg["temperature_K"],
            "n_anoxic": n_anoxic,
            "n_aerobic": 5 - n_anoxic,
            "reactor_configuration": f"{n_anoxic} anoxic CSTR + {5 - n_anoxic} aerobic AerationTank + primary/secondary clarifiers + thickener + ADM1 + dewatering",
        },
    }
