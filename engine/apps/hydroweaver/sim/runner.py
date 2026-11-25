"""WaterTAP / IDAES simulation and Pyomo+IPOPT NLP optimization backend for HydroWeaver.

Runs as an isolated subprocess with a dedicated Python interpreter that has
WaterTAP installed; it never imports WaterTAP into the main HydroWeaver process.
Speaks the same JSON-in / JSON-out contract as the HydroWeaver engine and is
documented in docs/SIMULATION.md.

Commands:
    self-check       report package versions, solver availability, supported units
    simulate         build, solve, and cost a candidate treatment train
    optimize-design  solve a Pyomo+IPOPT NLP to minimize LCOW over operating variables
"""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import math
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from unit_map import (  # noqa: E402
    SUPPORTED_FLOWSHEETS,
    SUPPORTED_UNITS,
    UNSUPPORTED_EXAMPLES,
    classify,
    select_flowsheet_family,
)
from wastewater import WastewaterFlowsheetError, simulate_asm1, simulate_bsm2  # noqa: E402

SCHEMA_VERSION = 1
PACKAGES = ('watertap', 'idaes-pse', 'pyomo', 'cyipopt')
LIMITATIONS = [
    'The NaCl property package models water and sodium chloride salinity; it does not contain trace contaminants, so it cannot predict trace-contaminant rejection.',
    'The ASM1 and BSM2 flowsheets model biological carbon/nitrogen removal (and ADM1 anaerobic digestion in BSM2) under steady-state reference assumptions and are uncalibrated unless site-fitted.',
    'A simulation result reports hydraulic, biological, and energy behavior under the declared conditions; it is not process sizing, costing, or a regulatory guarantee.',
    'Units without a mechanistic model are excluded from the flowsheet and reported as unsupported; they are never silently replaced.',
    'An unconverged solver status means the result is unconverged, not that the train is infeasible.',
]


def package_version(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None
    except Exception:
        return None


def importable(module: str) -> bool:
    try:
        __import__(module)
        return True
    except Exception:
        return False


def solver_available(name: str = 'ipopt') -> dict[str, Any]:
    """Probe the solver through IDAES (which knows its extensions path), then Pyomo."""
    try:
        from watertap.core.solvers import get_solver

        get_solver()
        return {'name': name, 'available': True, 'detail': 'resolved through the IDAES solver configuration'}
    except Exception as idaes_error:
        try:
            from pyomo.environ import SolverFactory

            solver = SolverFactory(name)
            if bool(solver.available(exception_flag=False)):
                return {'name': name, 'available': True, 'detail': 'resolved through Pyomo/PATH'}
            return {
                'name': name,
                'available': False,
                'detail': f'solver {name} not found: {idaes_error}',
            }
        except Exception as error:
            return {'name': name, 'available': False, 'detail': f'{type(error).__name__}: {error}'}


def environment_report() -> dict[str, Any]:
    versions = {name: package_version(name) for name in PACKAGES}
    watertap_ok = versions['watertap'] is not None
    return {
        'versions': versions,
        'python': sys.version.split()[0],
        'watertap_importable': importable('watertap'),
        'asm1_importable': importable('watertap.flowsheets.activated_sludge.ASM1_flowsheet'),
        'bsm2_importable': importable('watertap.flowsheets.full_water_resource_recovery_facility.BSM2'),
        'available': watertap_ok and versions['idaes-pse'] is not None and versions['pyomo'] is not None,
    }


def supported_units() -> list[dict[str, Any]]:
    return [
        {'unit': canonical, 'model': spec.model, 'kind': spec.kind, 'family': spec.family}
        for canonical, spec in sorted(SUPPORTED_UNITS.items())
    ]


def self_check() -> dict[str, Any]:
    environment = environment_report()
    return {
        'kind': 'hydroweaver.simulation-selfcheck',
        'schema_version': SCHEMA_VERSION,
        'available': environment['available'],
        'environment': environment,
        'solver': solver_available('ipopt'),
        'supported_flowsheets': list(SUPPORTED_FLOWSHEETS),
        'supported_units': supported_units(),
        'unsupported_examples': list(UNSUPPORTED_EXAMPLES),
        'limitations': LIMITATIONS,
    }


# --------------------------------------------------------------------------
# simulate
# --------------------------------------------------------------------------

def load_json(path: str) -> Any:
    with open(path, 'r', encoding='utf-8') as handle:
        return json.load(handle)


def json_safe(value: Any) -> Any:
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_safe(item) for item in value]
    return value


def write_json(payload: Any, output: str) -> None:
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f'.{target.name}.', suffix='.tmp', dir=target.parent)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
            handle.write(json.dumps(json_safe(payload), ensure_ascii=False, indent=2, allow_nan=False))
            handle.write('\n')
        os.replace(temporary, target)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def declared_number(case: dict[str, Any], section: str, field: str, extra_field: str | None = None) -> float | None:
    """Read an explicitly declared measurement; unknown values stay absent."""
    values = case.get(section)
    if not isinstance(values, dict):
        return None
    value = values.get(field)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if extra_field is not None:
        extra = values.get('extra')
        if isinstance(extra, dict):
            candidate = extra.get(extra_field)
            if isinstance(candidate, (int, float)) and not isinstance(candidate, bool):
                return float(candidate)
    return None


def feed_salinity_g_l(payload: dict[str, Any]) -> tuple[float | None, str]:
    """Salinity from explicit options, else the case's declared TDS, else None."""
    options = payload.get('options') if isinstance(payload.get('options'), dict) else {}
    explicit = options.get('feed_salinity_g_L')
    if isinstance(explicit, (int, float)) and not isinstance(explicit, bool) and float(explicit) >= 0:
        return float(explicit), 'declared option feed_salinity_g_L'
    case = payload.get('case') if isinstance(payload.get('case'), dict) else {}
    tds = declared_number(case, 'water_quality', 'tds_mg_L', 'tds_mg_L')
    if tds is None:
        tds = declared_number(case, 'water_quality', 'salinity_mg_L', 'salinity_mg_L')
    if tds is not None:
        return tds / 1000.0, 'declared water_quality TDS converted from mg/L to g/L'
    return None, 'no salinity declared; the NaCl property package default is used and reported'


def design_flow_m3_day(payload: dict[str, Any]) -> tuple[float | None, str]:
    options = payload.get('options') if isinstance(payload.get('options'), dict) else {}
    explicit = options.get('design_flow_m3_day')
    if isinstance(explicit, (int, float)) and not isinstance(explicit, bool) and float(explicit) > 0:
        return float(explicit), 'declared option design_flow_m3_day'
    case = payload.get('case') if isinstance(payload.get('case'), dict) else {}
    flow = declared_number(case, 'constraints', None, 'design_flow_m3_day')
    if flow is not None and flow > 0:
        return flow, 'declared constraints.extra.design_flow_m3_day'
    return None, 'no design flow declared; a nominal 100 m3/day basis is used and reported'


class FlowsheetError(Exception):
    pass


def target_water_recovery(payload: dict[str, Any]) -> float:
    """Declared water-recovery target; a nominal 0.5 default is reported."""
    options = payload.get('options') if isinstance(payload.get('options'), dict) else {}
    explicit = options.get('water_recovery')
    if isinstance(explicit, (int, float)) and not isinstance(explicit, bool):
        value = float(explicit)
        if 0.05 <= value <= 0.95:
            return value
    return 0.5

# Membrane transport coefficients (WaterTAP steady-state RO/NF examples).
MEMBRANE_COEFFICIENTS = {
    'Reverse Osmosis': {'A': 4.2e-12, 'B': 3.5e-8},
    'Nanofiltration': {'A': 1.2e-11, 'B': 2.5e-7},
}
NOMINAL_PUMP_DP_PA = 1.5e7  # 15 bar nominal boost when the declared basis is absent
FEED_PRESSURE_PA = 201325.0
FEED_TEMPERATURE_K = 298.15
NOMINAL_FLOW_KG_S = 1.0
NOMINAL_SALINITY_KG_KG = 0.030  # ~30 g/L NaCl-equivalent
DEFAULT_MEMBRANE_WIDTH_M = 5.0
CONCENTRATION_POLARIZATION_MODULUS = 1.1
MEMBRANE_PRESSURE_DROP_PA = 3e5  # nominal retentate pressure drop [Pa]
AREA_GUESS_PER_KG_S = 50.0  # initialization area guess scaled with feed flow
PUMP_EFFICIENCY = 0.80

def build_and_solve(
    modeled: list[str],
    specs,
    payload: dict[str, Any],
    *,
    optimize_design: bool = False,
) -> dict[str, Any]:
    """Build the WaterTAP flowsheet, attach costing, solve (or NLP-optimize), and collect results.

    Follows the WaterTAP steady-state membrane example recipe: an IDAES Feed
    boundary, the declared unit chain joined by arcs, explicit fixations derived
    only from the declared case or explicit options, optional WaterTAPCosting
    attachment, property and unit scaling, per-unit initialization, and an IPOPT
    solve. When ``optimize_design=True``, unfixes pump discharge pressure,
    membrane area, and recovery within bounds and minimizes LCOW subject to
    permeate TDS limits.
    """
    try:
        from pyomo.environ import ConcreteModel, Objective, TransformationFactory, value
        from pyomo.network import Arc
        from idaes.core import FlowsheetBlock
        from watertap.core.solvers import get_solver
        from idaes.core.util import scaling as iscale
        from idaes.core.util.model_statistics import degrees_of_freedom
        from idaes.models.unit_models import Feed
        from watertap.property_models.NaCl_prop_pack import NaClParameterBlock
    except Exception as error:
        raise FlowsheetError(f'simulation backend import failed: {type(error).__name__}: {error}') from error

    costing_cls = None
    unit_costing_cls = None
    try:
        from idaes.core import UnitModelCostingBlock
        from watertap.costing import WaterTAPCosting

        costing_cls = WaterTAPCosting
        unit_costing_cls = UnitModelCostingBlock
    except Exception:
        costing_cls = None
        unit_costing_cls = None

    salinity, salinity_source = feed_salinity_g_l(payload)
    flow, flow_source = design_flow_m3_day(payload)
    salt_mass_fraction = (salinity / 1000.0) if salinity is not None else NOMINAL_SALINITY_KG_KG
    feed_mass_flow = _feed_mass_flow(flow)
    target_recovery = target_water_recovery(payload)
    model = ConcreteModel()
    model.fs = FlowsheetBlock(dynamic=False)
    model.fs.properties = NaClParameterBlock()
    # Property-level default scaling must be declared before the state blocks
    # are constructed; it covers the permeate-side and mixed-permeate states
    # that explicit per-variable factors do not reach.
    model.fs.properties.set_default_scaling('flow_mass_phase_comp', 1.0, index=('Liq', 'H2O'))
    model.fs.properties.set_default_scaling('flow_mass_phase_comp', 1e2, index=('Liq', 'NaCl'))
    if costing_cls is not None:
        model.fs.costing = costing_cls()
    model.fs.feed = Feed(property_package=model.fs.properties)

    blocks: list[tuple[str, object, object]] = []
    try:
        for index, (name, spec) in enumerate(zip(modeled, specs)):
            block = _add_unit(model.fs, name, spec, index)
            if costing_cls is not None and unit_costing_cls is not None:
                block.costing = unit_costing_cls(flowsheet_costing_block=model.fs.costing)
            blocks.append((name, spec, block))
        for index in range(len(blocks)):
            source = model.fs.feed if index == 0 else blocks[index - 1][2]
            destination = blocks[index][2]
            arc = Arc(source=_outlet(source), destination=_inlet(destination))
            setattr(model.fs, f's{index:02d}', arc)
        TransformationFactory('network.expand_arcs').apply_to(model)

        _fix_feed(model, feed_mass_flow, salt_mass_fraction)
        for name, spec, block in blocks:
            _apply_fixations(name, spec, block, feed_mass_flow)
        membranes_all = [(name, block) for name, spec, block in blocks if spec.kind == 'membrane']
        if costing_cls is not None and membranes_all:
            model.fs.costing.cost_process()
            last_membrane = membranes_all[-1][1]
            model.fs.costing.add_annual_water_production(last_membrane.mixed_permeate[0].flow_vol)
            model.fs.costing.add_LCOW(last_membrane.mixed_permeate[0].flow_vol)
            model.fs.costing.add_specific_energy_consumption(last_membrane.mixed_permeate[0].flow_vol)
        _apply_scaling(model, blocks)

        solver = get_solver()
        solver.options['nlp_scaling_method'] = 'user-scaling'
        solver.options['bound_push'] = 1e-8
        solver.options['halt_on_ampl_error'] = 'yes'
        solver.options['max_iter'] = 3000

        # WaterTAP membrane recipe: compute the operating pressure from the feed
        # osmotic pressure plus the atmospheric and pressure-drop floors, seed
        # each membrane's inlet state, initialize with the relaxed area
        # objective, then swap the free area for the declared water-recovery
        # target and solve.
        operating_pressure = _operating_pressure(model, blocks, target_recovery, solver)
        for name, spec, block in blocks:
            if spec.kind == 'pump':
                block.control_volume.properties_out[0].pressure.fix(operating_pressure)

        from idaes.core.util.initialization import propagate_state

        membranes = [(index, name, spec, block) for index, (name, spec, block) in enumerate(blocks) if spec.kind == 'membrane']
        for position, (index, name, spec, block) in enumerate(membranes):
            if position == 0:
                _seed_membrane_state(block, model.fs.feed.properties[0], operating_pressure)
            else:
                previous = membranes[position - 1][3]
                _seed_membrane_state(block, previous.feed_side.properties[0, 0])
        _initialize(model, blocks, target_recovery, solver)
        if costing_cls is not None and membranes_all:
            model.fs.costing.initialize()
        for name, spec, block in blocks:
            if spec.kind == 'membrane':
                block.area.unfix()
                block.recovery_mass_phase_comp[0, 'Liq', 'H2O'].fix(target_recovery)

        if optimize_design:
            from pyomo.environ import minimize

            options = payload.get('options') if isinstance(payload.get('options'), dict) else {}
            case = payload.get('case') if isinstance(payload.get('case'), dict) else {}
            targets = case.get('treatment_targets') if isinstance(case.get('treatment_targets'), dict) else {}
            max_tds_g_l = options.get('max_permeate_tds_g_L')
            if max_tds_g_l is None and isinstance(targets.get('tds_mg_L'), (int, float)):
                max_tds_g_l = float(targets['tds_mg_L']) / 1000.0
            min_rec = float(options.get('min_recovery') or 0.35)
            max_rec = float(options.get('max_recovery') or 0.85)
            for name, spec, block in blocks:
                if spec.kind == 'pump':
                    block.control_volume.properties_out[0].pressure.unfix()
                    block.control_volume.properties_out[0].pressure.setlb(3.5e5)
                    block.control_volume.properties_out[0].pressure.setub(82e5)
                elif spec.kind == 'membrane':
                    block.recovery_mass_phase_comp[0, 'Liq', 'H2O'].unfix()
                    block.recovery_mass_phase_comp[0, 'Liq', 'H2O'].setlb(min_rec)
                    block.recovery_mass_phase_comp[0, 'Liq', 'H2O'].setub(max_rec)
                    block.area.setlb(5.0)
                    block.area.setub(10_000.0)
                    if max_tds_g_l is not None and float(max_tds_g_l) > 0:
                        block.mixed_permeate[0].conc_mass_phase_comp['Liq', 'NaCl'].setub(float(max_tds_g_l))
            if costing_cls is not None and membranes_all:
                model.fs.opt_objective = Objective(expr=model.fs.costing.LCOW, sense=minimize)
            elif membranes_all:
                model.fs.opt_objective = Objective(expr=sum(b.area for _, b in membranes_all), sense=minimize)
        else:
            degrees = degrees_of_freedom(model)
            if degrees != 0:
                raise FlowsheetError(
                    f'flowsheet has {degrees} degree(s) of freedom after fixation; '
                    'the declared case does not determine a unique steady state'
                )
        results = solver.solve(model, tee=False)
    except Exception as error:
        raise FlowsheetError(f'flowsheet build or solve failed: {type(error).__name__}: {error}') from error

    termination = str(results.solver.termination_condition)
    solver_status = str(results.solver.status)
    converged = 'optimal' in termination.lower()
    flowsheet_out = _flowsheet_results(model, blocks, converged, value, feed_mass_flow)
    if converged and costing_cls is not None and hasattr(model.fs, 'costing'):
        try:
            flowsheet_out['capex_usd'] = round(float(value(model.fs.costing.total_capital_cost)), 2)
            flowsheet_out['opex_usd_yr'] = round(float(value(model.fs.costing.total_operating_cost)), 2)
            if hasattr(model.fs.costing, 'LCOW'):
                flowsheet_out['lcow_usd_m3'] = round(float(value(model.fs.costing.LCOW)), 4)
            if hasattr(model.fs.costing, 'specific_energy_consumption'):
                flowsheet_out['watertap_sec_kWh_m3'] = round(float(value(model.fs.costing.specific_energy_consumption)), 4)
        except Exception:
            pass
    return {
        'status': 'optimal' if converged else 'unconverged',
        'mode': 'nlp-design-optimization' if optimize_design else 'steady-state-simulation',
        'units': [
            {'unit': name, 'model': spec.model, 'results': _unit_results(name, spec, block, converged, value)}
            for name, spec, block in blocks
        ],
        'flowsheet': flowsheet_out,
        'solver': {
            'name': 'ipopt',
            'status': solver_status,
            'termination_condition': termination,
            'iterations': _solver_iterations(results),
            'message': str(getattr(results.solver, 'message', '') or ''),
        },
        'basis': {
            'feed_salinity_g_L': salinity,
            'feed_salinity_source': salinity_source,
            'feed_mass_flow_kg_s': feed_mass_flow,
            'feed_salt_mass_fraction': salt_mass_fraction if salinity is not None else None,
            'design_flow_m3_day': flow,
            'design_flow_source': flow_source,
        },
    }


def _add_unit(fs, name, spec, index):
    """Instantiate a WaterTAP unit model and attach it to the flowsheet.

    IDAES unit models are attached by assignment (``fs.unit_0 = Pump(...)``);
    passing the flowsheet as a positional argument would be read as an index.
    """
    module_path, _, class_name = spec.model.rpartition('.')
    try:
        module = __import__(module_path, fromlist=[class_name])
        factory = getattr(module, class_name)
    except Exception as error:
        raise FlowsheetError(f'unit model {spec.model} is unavailable: {type(error).__name__}: {error}') from error
    if spec.kind == 'membrane':
        from watertap.unit_models.reverse_osmosis_0D import (
            ConcentrationPolarizationType,
            MassTransferCoefficient,
        )

        # Screening-grade configuration (the WaterTAP unit-test recipe): fixed
        # concentration-polarization modulus, no correlation-based mass
        # transfer, and a nominal pressure drop. These choices make the
        # initializer robust across salinities; they are documented in
        # docs/SIMULATION.md and reported with every result.
        block = factory(
            property_package=fs.properties,
            has_pressure_change=True,
            concentration_polarization_type=ConcentrationPolarizationType.fixed,
            mass_transfer_coefficient=MassTransferCoefficient.none,
        )
    else:
        block = factory(property_package=fs.properties)
    setattr(fs, f'unit_{index}', block)
    return block


def _outlet(block):
    return getattr(block, 'outlet', None) or getattr(block, 'retentate', None)


def _inlet(block):
    return getattr(block, 'inlet', None) or getattr(block, 'feed_side', None)


def _fix_feed(model, feed_mass_flow, salt_mass_fraction) -> None:
    state = model.fs.feed.properties[0]
    state.pressure.fix(FEED_PRESSURE_PA)
    state.temperature.fix(FEED_TEMPERATURE_K)
    state.flow_mass_phase_comp['Liq', 'H2O'].fix(feed_mass_flow * (1.0 - salt_mass_fraction))
    state.flow_mass_phase_comp['Liq', 'NaCl'].fix(feed_mass_flow * salt_mass_fraction)


def _apply_fixations(name, spec, block, feed_mass_flow) -> None:
    if spec.kind == 'pump':
        block.efficiency_pump.fix(PUMP_EFFICIENCY)
    elif spec.kind == 'membrane':
        coefficients = MEMBRANE_COEFFICIENTS.get(name, MEMBRANE_COEFFICIENTS['Reverse Osmosis'])
        block.A_comp.fix(coefficients['A'])
        block.B_comp.fix(coefficients['B'])
        block.feed_side.cp_modulus.fix(CONCENTRATION_POLARIZATION_MODULUS)
        block.deltaP.fix(-MEMBRANE_PRESSURE_DROP_PA)
        block.permeate.pressure[0].fix(101325.0)
        block.area.fix(AREA_GUESS_PER_KG_S * max(feed_mass_flow, 0.1))


def _operating_pressure(model, blocks, target_recovery, solver) -> float:
    """Estimate the feed pressure the first membrane needs.

    WaterTAP's correlation returns the brine osmotic pressure times the
    over-pressure factor; the feed pressure must additionally carry the
    atmospheric pressure and the membrane pressure drop so the retentate end
    keeps a positive driving force. Without those floors the model is genuinely
    infeasible at low salinity.
    """
    floor = FEED_PRESSURE_PA + MEMBRANE_PRESSURE_DROP_PA
    if not any(spec.kind == 'membrane' for _, spec, _ in blocks):
        return floor + NOMINAL_PUMP_DP_PA
    try:
        from watertap.core.util.unit_models import calculate_operating_pressure

        osmotic = float(calculate_operating_pressure(
            state_block=model.fs.feed.properties[0],
            over_pressure_factor=1.15,
            water_recovery_mass=target_recovery,
            salt_passage=0.01,
            solver=solver,
        ))
        return floor + osmotic
    except Exception:
        return floor + NOMINAL_PUMP_DP_PA


def _initialize(model, blocks, target_recovery, solver) -> None:
    """Initialize the flowsheet with WaterTAP's relaxed membrane recipe.

    The membrane area is released and an area objective drives the declared
    recovery during initialization; the objective is removed and the recovery
    fixed afterwards so the final solve is square.
    """
    from pyomo.environ import Objective

    from idaes.core.util.initialization import propagate_state

    for name, spec, block in blocks:
        if spec.kind == 'membrane':
            block.area.unfix()
            block.area_objective = Objective(
                expr=(block.recovery_mass_phase_comp[0, 'Liq', 'H2O'] - target_recovery) ** 2
            )
            block.initialize(optarg=solver.options, initialization_degrees_of_freedom=1)
            block.recovery_mass_phase_comp[0, 'Liq', 'H2O'].fix(target_recovery)
            block.del_component(block.area_objective)
    model.fs.feed.initialize(optarg=solver.options)
    for index, (name, spec, block) in enumerate(blocks):
        if spec.kind == 'pump':
            propagate_state(getattr(model.fs, f's{index:02d}'))
            block.initialize(optarg=solver.options)


def _seed_membrane_state(block, upstream, pressure_override=None) -> None:
    """Seed the membrane inlet state from the upstream outlet.

    Without this seed the RO initializer starts from default values and fails;
    the WaterTAP membrane examples set these values before initializing.
    """
    from pyomo.environ import value

    # The initializer reads the first feed-side element state, so seed there.
    target = getattr(block.feed_side, 'properties', None)
    target = target[0, 0] if target is not None else block.feed_side.properties_in[0]
    for component in ('H2O', 'NaCl'):
        target.flow_mass_phase_comp['Liq', component] = _source_value(
            upstream, 'flow_mass_phase_comp', component
        )
    target.temperature = _source_value(upstream, 'temperature')
    target.pressure = pressure_override if pressure_override is not None else _source_value(upstream, 'pressure')


def _source_value(source, name: str, component: str | None = None) -> Any:
    """Read a state value from a Port (time-indexed) or a StateBlock."""
    from pyomo.environ import value

    attribute = getattr(source, name)
    if component is not None:
        for key in ((0, 'Liq', component), ('Liq', component)):
            try:
                present = key in attribute
            except TypeError:
                present = False
            if present:
                return value(attribute[key])
        raise FlowsheetError(f'state source has no {name} for component {component}')
    for key in (0, None):
        try:
            present = key is None or key in attribute
        except TypeError:
            present = False
        if present:
            return value(attribute[key] if key is not None else attribute)
    return value(attribute)


def _apply_scaling(model, blocks) -> None:
    from idaes.core.util import scaling as iscale
    from pyomo.environ import Constraint

    iscale.set_scaling_factor(model.fs.feed.properties[0].flow_mass_phase_comp['Liq', 'H2O'], 1.0)
    iscale.set_scaling_factor(model.fs.feed.properties[0].flow_mass_phase_comp['Liq', 'NaCl'], 1e2)
    for name, spec, block in blocks:
        if spec.kind == 'pump':
            iscale.set_scaling_factor(block.control_volume.work, 1e-3)
        elif spec.kind == 'membrane':
            iscale.set_scaling_factor(block.area, 1e-2)
            iscale.set_scaling_factor(block.mixed_permeate[0].conc_mass_phase_comp['Liq', 'NaCl'], 1e5)
            for constraint in block.component_data_objects(Constraint):
                if 'eq_mass_frac_permeate' in constraint.name or 'eq_permeate_production' in constraint.name:
                    iscale.set_scaling_factor(constraint, 1e3)
    iscale.calculate_scaling_factors(model)


def _feed_mass_flow(flow_m3_day: float | None) -> float:
    basis = flow_m3_day if flow_m3_day and flow_m3_day > 0 else 100.0
    return basis * 1000.0 / 24.0 / 3600.0


def _solver_iterations(results) -> int | None:
    try:
        return int(results.solver.iterations)
    except Exception:
        return None


def _unit_results(name, spec, block, converged, value) -> dict[str, Any]:
    if not converged:
        return {'note': 'solver did not converge; no numeric unit results are reported'}
    results: dict[str, Any] = {}
    try:
        if spec.kind == 'pump':
            results['outlet_pressure_bar'] = round(value(block.control_volume.properties_out[0].pressure) / 1e5, 3)
            results['electrical_work_W'] = round(value(block.control_volume.work[0]), 2)
        elif spec.kind == 'membrane':
            permeate = value(block.mixed_permeate[0].flow_mass_phase_comp['Liq', 'H2O'])
            feed = value(block.feed_side.properties[0, 0].flow_mass_phase_comp['Liq', 'H2O'])
            results['permeate_flow_kg_s'] = round(permeate, 6)
            results['recovery_fraction'] = round(permeate / feed, 6) if feed else None
            results['permeate_NaCl_g_L'] = round(value(block.mixed_permeate[0].conc_mass_phase_comp['Liq', 'NaCl']), 5)
            results['membrane_area_m2'] = round(value(block.area), 3)
    except Exception:
        results['note'] = 'result extraction failed for this unit model version'
    return results


def _flowsheet_results(model, blocks, converged, value, feed_mass_flow) -> dict[str, Any]:
    if not converged:
        return {'note': 'solver did not converge; no flowsheet totals are reported'}
    totals: dict[str, Any] = {}
    try:
        membranes = [(name, block) for name, spec, block in blocks if spec.kind == 'membrane']
        pumps = [block for name, spec, block in blocks if spec.kind == 'pump']
        if membranes:
            name, block = membranes[-1]
            permeate = value(block.mixed_permeate[0].flow_mass_phase_comp['Liq', 'H2O'])
            retentate = value(block.feed_side.properties_out[0].flow_mass_phase_comp['Liq', 'H2O'])
            totals['product_water_flow_kg_s'] = round(permeate, 6)
            totals['concentrate_flow_kg_s'] = round(retentate, 6)
            totals['recovery_fraction'] = round(permeate / feed_mass_flow, 6) if feed_mass_flow else None
        if pumps:
            totals['pump_power_W'] = round(sum(value(block.control_volume.work[0]) for block in pumps), 2)
            product = totals.get('product_water_flow_kg_s')
            if product:
                energy_kwh_per_hour = totals['pump_power_W'] * 3600.0 / 3.6e6
                water_m3_per_hour = product * 3600.0 / 1000.0
                totals['specific_energy_kWh_m3'] = round(energy_kwh_per_hour / water_m3_per_hour, 6)
    except Exception:
        totals['note'] = 'flowsheet result extraction failed for this unit model version'
    return totals


def simulate(payload: dict[str, Any], *, optimize_design: bool = False) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError('simulation input must be a JSON object')
    if payload.get('schema_version') != SCHEMA_VERSION:
        raise ValueError(f'simulation input requires schema_version {SCHEMA_VERSION}')
    train = payload.get('train')
    case = payload.get('case')
    if not isinstance(train, dict) or not isinstance(case, dict):
        raise ValueError('simulation input requires train and case objects')
    chain = train.get('chain')
    if not isinstance(chain, list) or not chain or not all(isinstance(unit, str) and unit.strip() for unit in chain):
        raise ValueError('train.chain must be a non-empty string array')

    options = payload.get('options') if isinstance(payload.get('options'), dict) else {}
    coverage = classify(chain)
    family = select_flowsheet_family(coverage['specs'], options)
    environment = environment_report()
    record: dict[str, Any] = {
        'kind': 'hydroweaver.simulation-result',
        'schema_version': SCHEMA_VERSION,
        'flowsheet_model': family.upper() if family in ('asm1', 'bsm2') else 'NaCl',
        'coverage': {
            'modeled': coverage['modeled'],
            'unsupported': coverage['unsupported'],
            'note': 'Unsupported units are excluded from the WaterTAP flowsheet and modeled by HydroWeaver process physics.',
        },
        'train': {'chain_id': str(train.get('chain_id') or 'train'), 'chain': [str(unit) for unit in chain]},
        'environment': {'versions': environment['versions'], 'python': environment['python']},
        'limitations': LIMITATIONS,
    }

    explicit_wastewater = str(options.get('flowsheet_model') or '').strip().lower() in {'asm1', 'bsm2'}
    if not coverage['modeled'] and not explicit_wastewater:
        record['status'] = 'unsupported'
        record['solver'] = {'name': 'ipopt', 'status': 'not_run', 'termination_condition': '', 'iterations': 0, 'message': 'no unit in the train maps to a WaterTAP unit model'}
        return record

    if not environment['available']:
        record['status'] = 'error'
        record['error'] = 'the simulation backend is not installed in this interpreter; run the self-check for details'
        return record

    try:
        if family == 'asm1':
            outcome = simulate_asm1(coverage['modeled'], coverage['specs'], payload, optimize_design=optimize_design)
        elif family == 'bsm2':
            outcome = simulate_bsm2(coverage['modeled'], coverage['specs'], payload, optimize_design=optimize_design)
        else:
            outcome = build_and_solve(coverage['modeled'], coverage['specs'], payload, optimize_design=optimize_design)
    except (FlowsheetError, WastewaterFlowsheetError) as error:
        record['status'] = 'error'
        record['error'] = str(error)
        return record
    record.update(outcome)
    return record


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description='HydroWeaver simulation runner (WaterTAP/IDAES/Pyomo/IPOPT)')
    parser.add_argument('command', choices=('self-check', 'simulate', 'optimize-design'))
    parser.add_argument('--input', dest='input')
    parser.add_argument('--output', dest='output')
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == 'self-check':
        payload = self_check()
    else:
        if not args.input or not args.output:
            raise ValueError(f'{args.command} requires --input and --output')
        payload = simulate(load_json(args.input), optimize_design=(args.command == 'optimize-design'))
    if args.output:
        write_json(payload, args.output)
    else:
        sys.stdout.write(json.dumps(json_safe(payload), ensure_ascii=False, indent=2) + '\n')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as error:
        sys.stderr.write(json.dumps({'ok': False, 'error': type(error).__name__, 'detail': str(error)}) + '\n')
        raise SystemExit(1)
