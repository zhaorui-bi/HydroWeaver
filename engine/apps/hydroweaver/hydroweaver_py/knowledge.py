"""Standalone domain knowledge base, unit taxonomy, parameter bounds, and case screening."""

from __future__ import annotations

import copy
import math
import re
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ParamSpec:
    """Continuous operating parameter specification for a treatment unit."""

    name: str
    unit: str
    lower: float
    upper: float
    default: float
    description: str


@dataclass(frozen=True)
class UnitSpec:
    """Complete mechanistic, operational, resource, and cost specification of a unit."""

    name: str
    stage: str
    stage_order: int
    aliases: tuple[str, ...]
    mechanisms: tuple[str, ...]
    target_contaminants: tuple[str, ...]
    params: tuple[ParamSpec, ...]
    generates_brine: bool = False
    requires_chemical_dosing: bool = False
    provides_disinfection: bool = False
    requires_upstream_pump: bool = False
    operator_complexity: int = 1  # 1 (simple) .. 5 (complex)
    energy_tier: str = "low"  # low, medium, high
    base_capex_usd: float = 15_000.0
    capex_per_m3d_usd: float = 120.0
    capex_scale_exp: float = 0.78
    base_footprint_m2: float = 6.0
    footprint_per_m3d_m2: float = 0.04
    watertap_supported: bool = False
    evidence_summary: str = ""
    evidence_id: str = ""


UNIT_SPECS: dict[str, UnitSpec] = {
    "Oxidation": UnitSpec(
        name="Oxidation",
        stage="pre_oxidation",
        stage_order=10,
        aliases=("pre-oxidation", "preoxidation", "chemical oxidation", "chlorine oxidation", "permanganate oxidation", "ozonation"),
        mechanisms=("As(III) to As(V) oxidation", "Fe(II)/Mn(II) oxidation"),
        target_contaminants=("arsenic", "iron", "toc"),
        params=(
            ParamSpec("oxidant_dose_mg_L", "mg/L", 0.5, 12.0, 3.0, "Chemical oxidant dose (Cl2/MnO4 equivalent)"),
            ParamSpec("contact_time_min", "min", 5.0, 45.0, 15.0, "Oxidation contactor hydraulic retention time"),
        ),
        requires_chemical_dosing=True,
        operator_complexity=2,
        energy_tier="low",
        base_capex_usd=18_000.0,
        capex_per_m3d_usd=55.0,
        base_footprint_m2=5.0,
        footprint_per_m3d_m2=0.015,
        evidence_id="HW-UNIT-OX-01",
        evidence_summary="Pre-oxidation converts dissolved As(III) and Fe(II) into As(V) and Fe(III) oxyhydroxides prior to adsorption, coagulation, or filtration.",
    ),
    "Coagulation": UnitSpec(
        name="Coagulation",
        stage="clarification",
        stage_order=20,
        aliases=("coag", "ferric coagulation", "alum coagulation", "coagulation-flocculation"),
        mechanisms=("charge neutralization", "sweep flocculation", "As(V) co-precipitation"),
        target_contaminants=("turbidity", "toc", "arsenic", "lead", "iron"),
        params=(
            ParamSpec("coagulant_dose_mg_L", "mg/L", 5.0, 120.0, 35.0, "Ferric or alum coagulant dose"),
            ParamSpec("rapid_mix_g_s", "1/s", 200.0, 900.0, 500.0, "Rapid-mix velocity gradient G"),
        ),
        requires_chemical_dosing=True,
        operator_complexity=2,
        energy_tier="low",
        base_capex_usd=22_000.0,
        capex_per_m3d_usd=65.0,
        base_footprint_m2=6.0,
        footprint_per_m3d_m2=0.012,
        watertap_supported=True,
        evidence_id="HW-UNIT-COAG-01",
        evidence_summary="Ferric/alum coagulation destabilizes colloids, NOM, and As(V) species; requires downstream solid-liquid separation.",
    ),
    "Flocculation": UnitSpec(
        name="Flocculation",
        stage="clarification",
        stage_order=22,
        aliases=("floc", "gentle mixing"),
        mechanisms=("floc aggregation",),
        target_contaminants=("turbidity", "toc", "arsenic"),
        params=(
            ParamSpec("floc_time_min", "min", 10.0, 60.0, 25.0, "Flocculation hydraulic detention time"),
            ParamSpec("velocity_gradient_s", "1/s", 15.0, 75.0, 40.0, "Paddle/baffle mixing gradient G"),
        ),
        operator_complexity=1,
        energy_tier="low",
        base_capex_usd=16_000.0,
        capex_per_m3d_usd=45.0,
        base_footprint_m2=8.0,
        footprint_per_m3d_m2=0.025,
        evidence_id="HW-UNIT-FLOC-01",
        evidence_summary="Controlled gentle mixing aggregates destabilized microflocs to improve settling and granular-media capture.",
    ),
    "Sedimentation": UnitSpec(
        name="Sedimentation",
        stage="clarification",
        stage_order=24,
        aliases=("clarifier", "clarification", "settling", "lamella clarifier"),
        mechanisms=("gravity settling", "floc removal"),
        target_contaminants=("turbidity", "toc", "arsenic", "iron", "lead"),
        params=(
            ParamSpec("surface_overflow_rate_m_h", "m/h", 0.5, 4.0, 1.5, "Clarifier surface overflow rate"),
        ),
        operator_complexity=2,
        energy_tier="low",
        base_capex_usd=35_000.0,
        capex_per_m3d_usd=140.0,
        base_footprint_m2=18.0,
        footprint_per_m3d_m2=0.11,
        watertap_supported=True,
        evidence_id="HW-UNIT-SED-01",
        evidence_summary="Gravity clarification lowers high suspended-solids and coagulated-floc loads prior to filtration or membrane stages.",
    ),
    "Lime Softening": UnitSpec(
        name="Lime Softening",
        stage="pretreatment_softening",
        stage_order=26,
        aliases=("softening", "chemical softening", "precipitative softening"),
        mechanisms=("Ca/Mg precipitation", "silica co-precipitation", "scaling control"),
        target_contaminants=("hardness", "silica", "arsenic", "lead", "fluoride"),
        params=(
            ParamSpec("lime_dose_mg_L", "mg/L", 40.0, 380.0, 140.0, "Hydrated lime dose as Ca(OH)2"),
            ParamSpec("target_ph", "pH", 9.0, 11.2, 10.2, "Softening reactor operating pH"),
        ),
        requires_chemical_dosing=True,
        operator_complexity=3,
        energy_tier="low",
        base_capex_usd=42_000.0,
        capex_per_m3d_usd=150.0,
        base_footprint_m2=16.0,
        footprint_per_m3d_m2=0.085,
        evidence_id="HW-UNIT-LIME-01",
        evidence_summary="Lime softening precipitates carbonate/non-carbonate hardness and reduces RO/NF scaling potential at high recovery.",
    ),
    "Media Filtration": UnitSpec(
        name="Media Filtration",
        stage="clarification",
        stage_order=28,
        aliases=("sand filtration", "dual media filtration", "rapid sand filtration", "granular media filtration", "dmf", "filtration"),
        mechanisms=("depth filtration", "particulate capture"),
        target_contaminants=("turbidity", "iron", "arsenic", "lead"),
        params=(
            ParamSpec("filtration_rate_m_h", "m/h", 4.0, 18.0, 8.0, "Hydraulic loading rate"),
            ParamSpec("bed_depth_m", "m", 0.6, 1.8, 1.0, "Filter media depth"),
        ),
        operator_complexity=2,
        energy_tier="low",
        base_capex_usd=28_000.0,
        capex_per_m3d_usd=110.0,
        base_footprint_m2=10.0,
        footprint_per_m3d_m2=0.035,
        evidence_id="HW-UNIT-MF-01",
        evidence_summary="Dual/granular media filtration polishes turbidity and particulate iron/arsenic down to membrane-safe pretreatment levels.",
    ),
    "Ultrafiltration": UnitSpec(
        name="Ultrafiltration",
        stage="membrane_pretreatment",
        stage_order=30,
        aliases=("uf", "microfiltration", "mf"),
        mechanisms=("size exclusion", "colloid and pathogen barrier"),
        target_contaminants=("turbidity", "e_coli", "toc", "iron"),
        params=(
            ParamSpec("flux_lmh", "LMH", 30.0, 100.0, 60.0, "Design permeate flux"),
            ParamSpec("recovery", "-", 0.85, 0.96, 0.92, "UF hydraulic recovery fraction"),
            ParamSpec("transmembrane_pressure_bar", "bar", 0.6, 2.8, 1.4, "Operating transmembrane pressure"),
        ),
        operator_complexity=3,
        energy_tier="medium",
        base_capex_usd=45_000.0,
        capex_per_m3d_usd=185.0,
        base_footprint_m2=10.0,
        footprint_per_m3d_m2=0.02,
        evidence_id="HW-UNIT-UF-01",
        evidence_summary="Ultrafiltration delivers low-turbidity (<0.1 NTU) filtrate and >=4-log pathogen barrier ahead of RO/NF or potable polishing.",
    ),
    "Pumping": UnitSpec(
        name="Pumping",
        stage="hydraulics",
        stage_order=40,
        aliases=("pump", "feed pump", "high pressure pump", "booster pump"),
        mechanisms=("hydraulic pressurization",),
        target_contaminants=(),
        params=(
            ParamSpec("feed_pressure_bar", "bar", 2.0, 82.0, 14.0, "Pump discharge pressure"),
            ParamSpec("pump_efficiency", "-", 0.65, 0.88, 0.80, "Wire-to-water pump efficiency"),
        ),
        operator_complexity=1,
        energy_tier="medium",
        base_capex_usd=12_000.0,
        capex_per_m3d_usd=48.0,
        base_footprint_m2=4.0,
        footprint_per_m3d_m2=0.008,
        watertap_supported=True,
        evidence_id="HW-UNIT-PUMP-01",
        evidence_summary="High-pressure feed pumping supplies transmembrane driving pressure for NF/RO separation.",
    ),
    "Nanofiltration": UnitSpec(
        name="Nanofiltration",
        stage="desalination_separation",
        stage_order=50,
        aliases=("nf",),
        mechanisms=("Donnan exclusion", "steric divalent rejection", "NOM rejection"),
        target_contaminants=("hardness", "toc", "arsenic", "fluoride", "lead", "tds", "e_coli"),
        params=(
            ParamSpec("recovery", "-", 0.40, 0.88, 0.72, "NF water recovery fraction"),
            ParamSpec("feed_pressure_bar", "bar", 4.0, 25.0, 9.0, "Operating NF feed pressure"),
        ),
        generates_brine=True,
        requires_upstream_pump=True,
        operator_complexity=4,
        energy_tier="medium",
        base_capex_usd=55_000.0,
        capex_per_m3d_usd=260.0,
        base_footprint_m2=12.0,
        footprint_per_m3d_m2=0.025,
        watertap_supported=True,
        evidence_id="HW-UNIT-NF-01",
        evidence_summary="Nanofiltration rejects divalent hardness, NOM/DBP precursors, and As(V) at lower osmotic pressure than RO while generating concentrate.",
    ),
    "Reverse Osmosis": UnitSpec(
        name="Reverse Osmosis",
        stage="desalination_separation",
        stage_order=52,
        aliases=("ro", "membrane separation", "brackish ro", "seawater ro"),
        mechanisms=("solution-diffusion desalination", "multi-solute rejection"),
        target_contaminants=("tds", "nitrate", "arsenic", "fluoride", "hardness", "lead", "toc", "boron", "e_coli"),
        params=(
            ParamSpec("recovery", "-", 0.30, 0.86, 0.65, "RO water recovery fraction"),
            ParamSpec("feed_pressure_bar", "bar", 6.0, 82.0, 18.0, "Operating RO feed pressure"),
        ),
        generates_brine=True,
        requires_upstream_pump=True,
        operator_complexity=4,
        energy_tier="high",
        base_capex_usd=68_000.0,
        capex_per_m3d_usd=330.0,
        base_footprint_m2=14.0,
        footprint_per_m3d_m2=0.03,
        watertap_supported=True,
        evidence_id="HW-UNIT-RO-01",
        evidence_summary="Reverse osmosis achieves broad dissolved-solute removal when feed fouling, scaling limits, osmotic driving pressure, and brine disposal are managed.",
    ),
    "Energy Recovery": UnitSpec(
        name="Energy Recovery",
        stage="hydraulics_recovery",
        stage_order=54,
        aliases=("erd", "pressure exchanger", "px"),
        mechanisms=("brine pressure energy recovery",),
        target_contaminants=(),
        params=(
            ParamSpec("erd_efficiency", "-", 0.82, 0.97, 0.93, "Isobaric energy-recovery device efficiency"),
        ),
        operator_complexity=3,
        energy_tier="low",
        base_capex_usd=24_000.0,
        capex_per_m3d_usd=60.0,
        base_footprint_m2=4.0,
        footprint_per_m3d_m2=0.006,
        watertap_supported=True,
        evidence_id="HW-UNIT-ERD-01",
        evidence_summary="Isobaric pressure exchangers recover hydraulic energy from RO/NF concentrate, cutting net specific energy consumption on brackish/seawater trains.",
    ),
    "Adsorption": UnitSpec(
        name="Adsorption",
        stage="polishing",
        stage_order=60,
        aliases=("gac", "granular activated carbon", "activated alumina", "iron oxide media", "iron-oxide adsorption", "gfH"),
        mechanisms=("surface complexation", "porous adsorption"),
        target_contaminants=("arsenic", "toc", "fluoride", "lead"),
        params=(
            ParamSpec("ebct_min", "min", 3.0, 30.0, 10.0, "Empty-bed contact time"),
            ParamSpec("media_replacement_days", "days", 120.0, 730.0, 365.0, "Media replacement interval"),
        ),
        operator_complexity=2,
        energy_tier="low",
        base_capex_usd=24_000.0,
        capex_per_m3d_usd=135.0,
        base_footprint_m2=8.0,
        footprint_per_m3d_m2=0.03,
        watertap_supported=True,
        evidence_id="HW-UNIT-ADS-01",
        evidence_summary="Fixed-bed adsorption removes As(V), TOC, fluoride, and lead without producing liquid brine; performance depends on EBCT, pH, speciation, and NOM competition.",
    ),
    "Ion Exchange": UnitSpec(
        name="Ion Exchange",
        stage="polishing",
        stage_order=62,
        aliases=("ix", "anion exchange", "cation exchange", "strong base anion"),
        mechanisms=("selective ion exchange",),
        target_contaminants=("nitrate", "arsenic", "hardness", "fluoride", "lead"),
        params=(
            ParamSpec("ebct_min", "min", 2.0, 20.0, 6.0, "Resin empty-bed contact time"),
            ParamSpec("regeneration_bv", "BV", 150.0, 650.0, 320.0, "Bed volumes between regenerations"),
        ),
        generates_brine=True,
        operator_complexity=3,
        energy_tier="low",
        base_capex_usd=30_000.0,
        capex_per_m3d_usd=145.0,
        base_footprint_m2=8.0,
        footprint_per_m3d_m2=0.025,
        watertap_supported=True,
        evidence_id="HW-UNIT-IX-01",
        evidence_summary="Selective ion exchange removes nitrate, hardness, or As(V) at low pressure, subject to resin fouling limits and spent regenerant management.",
    ),
    "Advanced Oxidation": UnitSpec(
        name="Advanced Oxidation",
        stage="polishing",
        stage_order=64,
        aliases=("aop", "uv/h2o2", "uv-aop", "ozone-peroxide"),
        mechanisms=("hydroxyl radical oxidation", "micro-pollutant mineralization", "As(III) oxidation"),
        target_contaminants=("toc", "arsenic", "e_coli"),
        params=(
            ParamSpec("uv_dose_mj_cm2", "mJ/cm2", 100.0, 1200.0, 450.0, "UV fluence for radical generation"),
            ParamSpec("h2o2_dose_mg_L", "mg/L", 1.0, 25.0, 6.0, "Hydrogen peroxide dose"),
        ),
        requires_chemical_dosing=True,
        provides_disinfection=True,
        operator_complexity=4,
        energy_tier="high",
        base_capex_usd=48_000.0,
        capex_per_m3d_usd=165.0,
        base_footprint_m2=6.0,
        footprint_per_m3d_m2=0.015,
        watertap_supported=True,
        evidence_id="HW-UNIT-AOP-01",
        evidence_summary="UV/H2O2 AOP degrades refractory organics and oxidizes As(III), requiring high UV transmittance (low turbidity/NOM).",
    ),
    "UV Disinfection": UnitSpec(
        name="UV Disinfection",
        stage="disinfection",
        stage_order=70,
        aliases=("uv", "ultraviolet irradiation", "uv irradiation"),
        mechanisms=("UV nucleic-acid inactivation",),
        target_contaminants=("e_coli",),
        params=(
            ParamSpec("uv_dose_mj_cm2", "mJ/cm2", 20.0, 140.0, 45.0, "Validated UV disinfection fluence"),
        ),
        provides_disinfection=True,
        operator_complexity=2,
        energy_tier="low",
        base_capex_usd=18_000.0,
        capex_per_m3d_usd=55.0,
        base_footprint_m2=4.0,
        footprint_per_m3d_m2=0.008,
        evidence_id="HW-UNIT-UV-01",
        evidence_summary="UV disinfection achieves chemical-free pathogen inactivation without forming chlorinated DBPs, provided water clarity supports adequate UVT.",
    ),
    "Chlorination": UnitSpec(
        name="Chlorination",
        stage="disinfection",
        stage_order=72,
        aliases=("chlorine", "chlorine dosing", "chloramine", "disinfection"),
        mechanisms=("CT pathogen inactivation", "distribution residual"),
        target_contaminants=("e_coli",),
        params=(
            ParamSpec("chlorine_dose_mg_L", "mg/L", 0.5, 8.0, 2.2, "Applied chlorine dose as Cl2"),
            ParamSpec("contact_time_min", "min", 10.0, 90.0, 30.0, "Clearwell baffled contact time"),
        ),
        requires_chemical_dosing=True,
        provides_disinfection=True,
        operator_complexity=1,
        energy_tier="low",
        base_capex_usd=14_000.0,
        capex_per_m3d_usd=42.0,
        base_footprint_m2=6.0,
        footprint_per_m3d_m2=0.02,
        evidence_id="HW-UNIT-CL2-01",
        evidence_summary="Chlorination provides primary CT disinfection and residual protection; excess TOC increases chlorine demand and DBP formation risk.",
    ),
    "Brine Concentrator": UnitSpec(
        name="Brine Concentrator",
        stage="residuals",
        stage_order=80,
        aliases=("mld", "zld", "thermal brine concentrator", "mvc brine concentrator"),
        mechanisms=("concentrate volume minimization", "distillate recovery"),
        target_contaminants=("tds",),
        params=(
            ParamSpec("concentrate_recovery", "-", 0.65, 0.95, 0.85, "Distillate recovery of reject brine"),
        ),
        operator_complexity=5,
        energy_tier="high",
        base_capex_usd=85_000.0,
        capex_per_m3d_usd=420.0,
        base_footprint_m2=15.0,
        footprint_per_m3d_m2=0.035,
        evidence_id="HW-UNIT-BC-01",
        evidence_summary="Brine concentration recovers distillate from RO/NF reject streams to satisfy zero/minimal-liquid-discharge constraints at elevated energy and CAPEX.",
    ),
}


CANONICAL_UNITS: tuple[str, ...] = tuple(UNIT_SPECS.keys())

_UNIT_ALIAS_LOOKUP: dict[str, str] = {}
for _name, _spec in UNIT_SPECS.items():
    _UNIT_ALIAS_LOOKUP[_name.lower()] = _name
    for _alias in _spec.aliases:
        _UNIT_ALIAS_LOOKUP[_alias.lower()] = _name


def normalize_unit_name(raw: str) -> str | None:
    """Resolve a canonical treatment-unit name from a raw label or alias."""
    key = " ".join(str(raw).replace("_", " ").split()).strip().lower()
    if not key:
        return None
    if key in _UNIT_ALIAS_LOOKUP:
        return _UNIT_ALIAS_LOOKUP[key]
    for canonical in UNIT_SPECS:
        if key in canonical.lower():
            return canonical
    return None


@dataclass(frozen=True)
class ContaminantSpec:
    """Canonical contaminant metadata and study reference benchmarks."""

    name: str
    field: str
    unit: str
    aliases: tuple[str, ...]
    reference_limit: float | None
    reference_note: str
    evidence_id: str


CONTAMINANT_SPECS: dict[str, ContaminantSpec] = {
    "tds": ContaminantSpec(
        name="tds",
        field="tds_mg_L",
        unit="mg/L",
        aliases=("total dissolved solids", "salinity", "nacl", "dissolved solids"),
        reference_limit=500.0,
        reference_note="Secondary aesthetic / potable TDS guideline 500 mg/L",
        evidence_id="HW-CONT-TDS",
    ),
    "turbidity": ContaminantSpec(
        name="turbidity",
        field="turbidity_NTU",
        unit="NTU",
        aliases=("tss", "suspended solids", "particles"),
        reference_limit=1.0,
        reference_note="Drinking-water filtration benchmark <= 1.0 NTU (<= 0.3 NTU preferred)",
        evidence_id="HW-CONT-TURB",
    ),
    "toc": ContaminantSpec(
        name="toc",
        field="toc_mg_L",
        unit="mg/L",
        aliases=("nom", "doc", "natural organic matter", "organic carbon", "organics", "dbp precursors"),
        reference_limit=2.0,
        reference_note="DBP precursor / reuse organic benchmark <= 2.0 mg/L",
        evidence_id="HW-CONT-TOC",
    ),
    "arsenic": ContaminantSpec(
        name="arsenic",
        field="arsenic_ug_L",
        unit="µg/L",
        aliases=("as", "as(iii)", "as(v)", "arsenite", "arsenate"),
        reference_limit=10.0,
        reference_note="WHO/EPA arsenic MCL 10 µg/L; As(III) requires pre-oxidation for sorptive/coagulative capture",
        evidence_id="HW-CONT-AS",
    ),
    "nitrate": ContaminantSpec(
        name="nitrate",
        field="nitrate_mg_L",
        unit="mg/L",
        aliases=("no3", "no3-n", "nitrate-n"),
        reference_limit=10.0,
        reference_note="10 mg/L as N (~45–50 mg/L as NO3); preserve reporting basis explicitly",
        evidence_id="HW-CONT-NO3",
    ),
    "fluoride": ContaminantSpec(
        name="fluoride",
        field="fluoride_mg_L",
        unit="mg/L",
        aliases=("f-", "fluorides"),
        reference_limit=1.5,
        reference_note="WHO guideline 1.5 mg/L",
        evidence_id="HW-CONT-F",
    ),
    "hardness": ContaminantSpec(
        name="hardness",
        field="hardness_mg_L",
        unit="mg/L",
        aliases=("calcium", "magnesium", "ca", "mg", "total hardness", "scaling"),
        reference_limit=150.0,
        reference_note="Reported as CaCO3; high hardness drives membrane scaling at high recovery",
        evidence_id="HW-CONT-HARD",
    ),
    "iron": ContaminantSpec(
        name="iron",
        field="iron_mg_L",
        unit="mg/L",
        aliases=("fe", "fe(ii)", "fe(iii)", "dissolved iron"),
        reference_limit=0.3,
        reference_note="Secondary limit 0.3 mg/L; soluble Fe(II) fouls membranes if oxidized inside modules",
        evidence_id="HW-CONT-FE",
    ),
    "lead": ContaminantSpec(
        name="lead",
        field="lead_ug_L",
        unit="µg/L",
        aliases=("pb", "plumbum"),
        reference_limit=10.0,
        reference_note="Reference benchmark 10 µg/L (action levels may be lower)",
        evidence_id="HW-CONT-PB",
    ),
    "e_coli": ContaminantSpec(
        name="e_coli",
        field="e_coli_CFU_100mL",
        unit="CFU/100 mL",
        aliases=("pathogens", "coliform", "bacteria", "microbial", "ecoli"),
        reference_limit=0.0,
        reference_note="Potable microbial target requires >= 4-log disinfection / non-detect",
        evidence_id="HW-CONT-ECOLI",
    ),
    "boron": ContaminantSpec(
        name="boron",
        field="boron_mg_L",
        unit="mg/L",
        aliases=("b", "boric acid"),
        reference_limit=1.0,
        reference_note="Seawater/reuse boron guideline <= 1.0–2.4 mg/L",
        evidence_id="HW-CONT-B",
    ),
    "silica": ContaminantSpec(
        name="silica",
        field="silica_mg_L",
        unit="mg/L",
        aliases=("sio2", "reactive silica"),
        reference_limit=20.0,
        reference_note="Silica polymerization limits RO/NF recovery when brine SiO2 exceeds ~150 mg/L",
        evidence_id="HW-CONT-SI",
    ),
}

_CONTAMINANT_ALIAS_LOOKUP: dict[str, str] = {}
for _cname, _cspec in CONTAMINANT_SPECS.items():
    _CONTAMINANT_ALIAS_LOOKUP[_cname] = _cname
    for _alias in _cspec.aliases:
        _CONTAMINANT_ALIAS_LOOKUP[_alias.lower()] = _cname


def normalize_contaminant_name(raw: str) -> str | None:
    key = " ".join(str(raw).replace("_", " ").split()).strip().lower()
    if not key:
        return None
    if key in _CONTAMINANT_ALIAS_LOOKUP:
        return _CONTAMINANT_ALIAS_LOOKUP[key]
    for cname in CONTAMINANT_SPECS:
        if cname in key:
            return cname
    return None


@dataclass(frozen=True)
class TemplatePrior:
    """Knowledge-informed process-train template prior."""

    template_id: str
    title: str
    source_waters: tuple[str, ...]
    target_contaminants: tuple[str, ...]
    chain: tuple[str, ...]
    rationale: str
    notes: str


TEMPLATE_PRIORS: tuple[TemplatePrior, ...] = (
    TemplatePrior(
        template_id="TPL-AS-GW-ADS",
        title="Groundwater Arsenic Oxidation + Adsorption + Disinfection",
        source_waters=("groundwater",),
        target_contaminants=("arsenic", "iron"),
        chain=("Oxidation", "Media Filtration", "Adsorption", "Chlorination"),
        rationale="Oxidizes As(III)/Fe(II), removes precipitated iron particulates, adsorbs As(V) without liquid brine, and maintains potable CT.",
        notes="Suitable when brine disposal is unavailable and TDS is moderate.",
    ),
    TemplatePrior(
        template_id="TPL-AS-GW-NOPUMP-CHEMFREE",
        title="Low-Maintenance Chemical-Free Arsenic Adsorption + UV",
        source_waters=("groundwater",),
        target_contaminants=("arsenic", "lead", "fluoride"),
        chain=("Media Filtration", "Adsorption", "UV Disinfection"),
        rationale="Avoids chemical dosing and brine generation using physical filtration, adsorptive media, and UV disinfection.",
        notes="Effective when As(V) dominates and chemical dosing is disallowed or operator skill is low.",
    ),
    TemplatePrior(
        template_id="TPL-SW-CONVENTIONAL",
        title="Surface Water Coagulation-Flocculation-Sedimentation-Filtration + Disinfection",
        source_waters=("surface water", "surface_water", "river", "lake"),
        target_contaminants=("turbidity", "toc", "arsenic", "lead", "e_coli"),
        chain=("Coagulation", "Flocculation", "Sedimentation", "Media Filtration", "Chlorination"),
        rationale="Classical multi-barrier clarification for high turbidity and NOM removal with clearwell CT disinfection.",
        notes="Watch DBP formation if residual TOC remains high ahead of chlorination.",
    ),
    TemplatePrior(
        template_id="TPL-SW-UF-ADS-UV",
        title="Surface Water Coagulation + Ultrafiltration + Adsorption + UV",
        source_waters=("surface water", "surface_water", "wastewater"),
        target_contaminants=("turbidity", "toc", "e_coli", "lead"),
        chain=("Coagulation", "Media Filtration", "Ultrafiltration", "Adsorption", "UV Disinfection"),
        rationale="Combines UF particle/pathogen barrier with GAC adsorption for DBP precursor removal and chemical-free UV.",
        notes="Compact footprint compared to conventional sedimentation.",
    ),
    TemplatePrior(
        template_id="TPL-BWRO-ERD",
        title="Brackish Desalination with Pretreatment + Pumping + RO + Energy Recovery",
        source_waters=("groundwater", "brackish", "wastewater", "industrial"),
        target_contaminants=("tds", "nitrate", "arsenic", "fluoride", "hardness"),
        chain=("Media Filtration", "Pumping", "Reverse Osmosis", "Energy Recovery", "Chlorination"),
        rationale="Delivers broad dissolved-ion desalination while cutting pumping SEC via isobaric energy recovery.",
        notes="Requires brine disposal or downstream Brine Concentrator if brine disposal is prohibited.",
    ),
    TemplatePrior(
        template_id="TPL-SOFT-RO-ZLD",
        title="High-Scaling / MLD Brackish Reuse with Lime Softening + UF + RO + Brine Concentrator",
        source_waters=("wastewater", "industrial", "brackish", "groundwater"),
        target_contaminants=("tds", "hardness", "silica", "toc", "nitrate", "e_coli"),
        chain=("Lime Softening", "Ultrafiltration", "Pumping", "Reverse Osmosis", "Energy Recovery", "Brine Concentrator", "UV Disinfection"),
        rationale="Prevents CaCO3/silica scaling ahead of high-recovery RO and minimizes reject volume via brine concentration.",
        notes="Designed for strict recovery and zero/minimal liquid discharge constraints.",
    ),
    TemplatePrior(
        template_id="TPL-SWRO-ERD",
        title="Seawater Desalination with UF Pretreatment + RO + Energy Recovery + Disinfection",
        source_waters=("seawater", "marine"),
        target_contaminants=("tds", "boron", "hardness", "e_coli"),
        chain=("Coagulation", "Media Filtration", "Ultrafiltration", "Pumping", "Reverse Osmosis", "Energy Recovery", "Chlorination"),
        rationale="Protects SWRO membranes against colloidal/biofouling and recovers concentrate pressure energy to meet SEC/LCOW targets.",
        notes="Requires adequate feed pressure >60 bar to overcome seawater osmotic pressure.",
    ),
    TemplatePrior(
        template_id="TPL-NF-NOM-HARD",
        title="Nanofiltration for Hardness & NOM Control",
        source_waters=("surface water", "surface_water", "groundwater"),
        target_contaminants=("hardness", "toc", "fluoride", "arsenic"),
        chain=("Media Filtration", "Pumping", "Nanofiltration", "UV Disinfection"),
        rationale="Selectively removes divalent hardness and organic DBP precursors at lower pressure and energy than RO.",
        notes="Generates reject stream; pair with Energy Recovery or Brine Concentrator if needed.",
    ),
    TemplatePrior(
        template_id="TPL-IX-NITRATE",
        title="Filtration + Selective Ion Exchange + Disinfection",
        source_waters=("groundwater",),
        target_contaminants=("nitrate", "hardness", "arsenic"),
        chain=("Media Filtration", "Ion Exchange", "Chlorination"),
        rationale="Low-energy selective nitrate or hardness removal without high-pressure RO pumping.",
        notes="Produces minor spent regenerant brine; check brine disposal constraint.",
    ),
    TemplatePrior(
        template_id="TPL-AOP-POLISH",
        title="Advanced Oxidation Polishing for Refractory Organics & Trace Contaminants",
        source_waters=("wastewater", "industrial", "surface water"),
        target_contaminants=("toc", "arsenic", "e_coli"),
        chain=("Media Filtration", "Ultrafiltration", "Adsorption", "Advanced Oxidation", "UV Disinfection"),
        rationale="Combines membrane/carbon pretreatment with UV/H2O2 AOP for recalcitrant TOC and pathogen control.",
        notes="Requires low turbidity upstream for UV transmittance.",
    ),
)


MEASUREMENT_UNITS: dict[str, str | None] = {
    "pH": None,
    "temperature_C": "°C",
    "tds_mg_L": "mg/L",
    "salinity_mg_L": "mg/L",
    "turbidity_NTU": "NTU",
    "arsenic_ug_L": "µg/L",
    "nitrate_mg_L": "mg/L",
    "fluoride_mg_L": "mg/L",
    "toc_mg_L": "mg/L",
    "iron_mg_L": "mg/L",
    "hardness_mg_L": "mg/L",
    "e_coli_CFU_100mL": "CFU/100 mL",
    "lead_ug_L": "µg/L",
    "boron_mg_L": "mg/L",
    "silica_mg_L": "mg/L",
}

_TARGET_FIELDS: dict[str, str] = {
    "tds": "tds_mg_L",
    "arsenic": "arsenic_ug_L",
    "nitrate": "nitrate_mg_L",
    "fluoride": "fluoride_mg_L",
    "turbidity": "turbidity_NTU",
    "toc": "toc_mg_L",
    "hardness": "hardness_mg_L",
    "iron": "iron_mg_L",
    "e_coli": "e_coli",
    "lead": "extra.lead_ug_L",
    "boron": "extra.boron_mg_L",
    "silica": "extra.silica_mg_L",
}

_PRIORITY_ORDER = {"critical": 0, "high": 1, "medium": 2}


def _has_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, dict)):
        return bool(value)
    return True


def _is_finite_number(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(float(value))


def _nitrate_basis(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    token = re.sub(r"[\s_-]+", "", value.lower().replace("₃", "3"))
    if token in {"asn", "n", "no3n", "nitraten", "nitrateasn"}:
        return "as_N"
    if token in {"asno3", "no3", "nitrateasno3"}:
        return "as_NO3"
    return None


def _extract_raw_query_hints(raw_query: str) -> dict[str, Any]:
    """Deterministic parser for natural-language queries without requiring remote LLMs."""
    text = raw_query.lower()
    source_water = "unknown"
    for candidate in ("seawater", "groundwater", "surface water", "wastewater", "brackish", "industrial"):
        if candidate in text:
            source_water = candidate
            break
    contaminants: list[str] = []
    for cname, spec in CONTAMINANT_SPECS.items():
        tokens = (cname.replace("_", " "), *spec.aliases)
        if any(re.search(rf"\b{re.escape(tok)}\b", text) for tok in tokens if len(tok) >= 3):
            contaminants.append(cname)
    wq: dict[str, Any] = {}
    tt: dict[str, Any] = {}
    constraints: dict[str, Any] = {}
    if "drinking" in text or "potable" in text:
        constraints["use_for_drinking"] = True
    if "no brine" in text or "zero liquid" in text or "zld" in text:
        constraints["brine_disposal"] = False
    if "no chemical" in text or "chemical-free" in text or "chemical free" in text:
        constraints["chemical_dosing_allowed"] = False
    for label, pattern, scale in (
        ("arsenic_ug_L", r"arsenic[^\d]{0,20}(\d+(?:\.\d+)?)\s*(?:ug/l|µg/l|ppb)", 1.0),
        ("tds_mg_L", r"(?:tds|salinity)[^\d]{0,20}(\d+(?:\.\d+)?)\s*mg/l", 1.0),
        ("tds_mg_L", r"(?:tds|salinity)[^\d]{0,20}(\d+(?:\.\d+)?)\s*g/l", 1000.0),
        ("turbidity_NTU", r"turbidity[^\d]{0,20}(\d+(?:\.\d+)?)\s*ntu", 1.0),
        ("toc_mg_L", r"(?:toc|nom)[^\d]{0,20}(\d+(?:\.\d+)?)\s*mg/l", 1.0),
        ("nitrate_mg_L", r"nitrate[^\d]{0,20}(\d+(?:\.\d+)?)\s*mg/l", 1.0),
        ("hardness_mg_L", r"hardness[^\d]{0,20}(\d+(?:\.\d+)?)\s*mg/l", 1.0),
    ):
        match = re.search(pattern, text)
        if match and label not in wq:
            wq[label] = float(match.group(1)) * scale
    target_match = re.search(r"(?:target|<=|≤|below|under)\s*(\d+(?:\.\d+)?)\s*(?:ug/l|µg/l|ppb)", text)
    if target_match and "arsenic" in contaminants:
        tt["arsenic_ug_L"] = float(target_match.group(1))
    flow_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:m3/d|m3/day|m³/d|m³/day)", text)
    if flow_match:
        constraints.setdefault("extra", {})["design_flow_m3_day"] = float(flow_match.group(1))
    return {
        "source_water": source_water,
        "contaminants": contaminants,
        "water_quality": wq,
        "treatment_targets": tt,
        "constraints": constraints,
    }


def validate_and_normalize_query(raw: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Normalize a HydroWeaver UserQuery without dropping any declared fields."""
    if not isinstance(raw, dict):
        raise ValueError("query must be a JSON object")

    for section in ("water_quality", "treatment_targets"):
        measurements = raw.get(section)
        if isinstance(measurements, dict):
            for field_name, measurement in measurements.items():
                if field_name in MEASUREMENT_UNITS and isinstance(measurement, bool):
                    raise ValueError(f"{section}.{field_name} must be a numeric measurement, not a boolean")
            extra = measurements.get("extra")
            if isinstance(extra, dict):
                for field_name, measurement in extra.items():
                    if field_name in MEASUREMENT_UNITS and isinstance(measurement, bool):
                        raise ValueError(f"{section}.extra.{field_name} must be a numeric measurement, not a boolean")
    constraints_raw = raw.get("constraints")
    if isinstance(constraints_raw, dict) and isinstance(constraints_raw.get("extra"), dict):
        if isinstance(constraints_raw["extra"].get("design_flow_m3_day"), bool):
            raise ValueError("constraints.extra.design_flow_m3_day must be a numeric flow, not a boolean")

    hints = _extract_raw_query_hints(str(raw.get("raw_query") or "")) if raw.get("raw_query") else {}
    notes: list[str] = []
    assumptions: list[str] = list(raw.get("assumptions") or []) if isinstance(raw.get("assumptions"), list) else []

    source_water = str(raw.get("source_water") or hints.get("source_water") or "unknown").strip() or "unknown"
    wq = copy.deepcopy(raw.get("water_quality")) if isinstance(raw.get("water_quality"), dict) else {}
    for k, v in (hints.get("water_quality") or {}).items():
        if k not in wq:
            wq[k] = v
            assumptions.append(f"Extracted {k}={v} from raw_query.")
    wq.setdefault("extra", {})

    tt = copy.deepcopy(raw.get("treatment_targets")) if isinstance(raw.get("treatment_targets"), dict) else {}
    for k, v in (hints.get("treatment_targets") or {}).items():
        if k not in tt:
            tt[k] = v
            assumptions.append(f"Extracted target {k}={v} from raw_query.")
    tt.setdefault("extra", {})

    constraints = copy.deepcopy(raw.get("constraints")) if isinstance(raw.get("constraints"), dict) else {}
    for k, v in (hints.get("constraints") or {}).items():
        if k == "extra" and isinstance(v, dict):
            constraints.setdefault("extra", {})
            for ek, ev in v.items():
                constraints["extra"].setdefault(ek, ev)
        elif k not in constraints:
            constraints[k] = v
            assumptions.append(f"Extracted constraint {k}={v} from raw_query.")
    constraints.setdefault("extra", {})

    raw_contams = raw.get("contaminants")
    contaminants: list[str] = []
    if isinstance(raw_contams, list):
        for item in raw_contams:
            canon = normalize_contaminant_name(str(item))
            if canon and canon not in contaminants:
                contaminants.append(canon)
            elif isinstance(item, str) and item.strip() and item.strip().lower() not in contaminants:
                contaminants.append(item.strip().lower())
    for item in hints.get("contaminants") or []:
        if item not in contaminants:
            contaminants.append(item)

    # Also infer contaminants from explicitly populated water_quality measurements
    for cname, cspec in CONTAMINANT_SPECS.items():
        val = wq.get(cspec.field)
        if _is_finite_number(val) and cname not in contaminants:
            if cname == "hardness" and float(val) < 120:
                continue
            if cname == "iron" and float(val) < 0.3:
                continue
            contaminants.append(cname)

    missing_fields: list[str] = []
    if source_water == "unknown":
        missing_fields.append("source_water")
    if not contaminants:
        missing_fields.append("contaminants")
    if constraints.get("use_for_drinking") is None:
        missing_fields.append("constraints.use_for_drinking")

    query_id = str(raw.get("query_id") or "hydroweaver-case")
    normalized = {
        "query_id": query_id,
        "raw_query": raw.get("raw_query"),
        "source_water": source_water,
        "contaminants": contaminants,
        "water_quality": wq,
        "treatment_targets": tt,
        "constraints": constraints,
        "context": raw.get("context"),
        "missing_fields": missing_fields,
        "assumptions": assumptions,
        "normalization_notes": notes,
    }
    # Preserve any explicit top-level extension keys
    for key, value in raw.items():
        if key not in normalized:
            normalized[key] = value

    retained_fields: list[str] = []
    for section in ("water_quality", "treatment_targets", "constraints"):
        extra = normalized.get(section, {}).get("extra")
        if isinstance(extra, dict):
            retained_fields.extend(f"{section}.extra.{field}" for field in sorted(extra))

    preservation = {
        "retained_fields": retained_fields,
        "scope": "Explicit measurements, reporting bases, and resource/cost constraints are preserved natively by HydroWeaver across simulation, diagnosis, and optimization.",
    }
    return normalized, preservation


def _measurement_records(values: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    extra = values.get("extra") if isinstance(values.get("extra"), dict) else {}
    for field_name, value in values.items():
        if field_name == "extra" or not _has_value(value):
            continue
        record: dict[str, Any] = {
            "field": field_name,
            "value": value,
            "unit": MEASUREMENT_UNITS.get(field_name),
        }
        if field_name in {"nitrate_mg_L", "hardness_mg_L"}:
            record["basis"] = extra.get(field_name.removesuffix("_mg_L") + "_basis")
        records.append(record)
    for field_name, value in sorted(extra.items()):
        if _has_value(value):
            records.append(
                {
                    "field": f"extra.{field_name}",
                    "value": value,
                    "unit": MEASUREMENT_UNITS.get(field_name),
                }
            )
    return records


def _add_info_action(
    actions: list[dict[str, Any]],
    seen: set[str],
    *,
    code: str,
    field: str,
    priority: str,
    action_type: str,
    rationale: str,
    decision_impact: str,
) -> None:
    if field in seen:
        return
    seen.add(field)
    actions.append(
        {
            "code": code,
            "field": field,
            "priority": priority,
            "action_type": action_type,
            "rationale": rationale,
            "decision_impact": decision_impact,
            "basis": "deterministic_screening_rule",
        }
    )


def build_case_assessment(normalized: dict[str, Any]) -> dict[str, Any]:
    """Deterministic case readiness audit over water-quality, resource, and cost specifications."""
    wq = normalized.get("water_quality") if isinstance(normalized.get("water_quality"), dict) else {}
    targets = normalized.get("treatment_targets") if isinstance(normalized.get("treatment_targets"), dict) else {}
    constraints = normalized.get("constraints") if isinstance(normalized.get("constraints"), dict) else {}
    water_extra = wq.get("extra") if isinstance(wq.get("extra"), dict) else {}
    target_extra = targets.get("extra") if isinstance(targets.get("extra"), dict) else {}
    constraint_extra = constraints.get("extra") if isinstance(constraints.get("extra"), dict) else {}

    contaminants = [str(v).strip() for v in normalized.get("contaminants", []) if isinstance(v, str) and v.strip()]
    contaminant_set = {v.lower() for v in contaminants}
    source_water = str(normalized.get("source_water") or "unknown").strip() or "unknown"

    actions: list[dict[str, Any]] = []
    seen: set[str] = set()

    for section, values in (("water_quality", wq), ("treatment_targets", targets)):
        measurements = [(k, v) for k, v in values.items() if k != "extra"]
        extra_map = values.get("extra") if isinstance(values.get("extra"), dict) else {}
        measurements.extend((f"extra.{k}", v) for k, v in extra_map.items())
        for field_name, value in measurements:
            base_name = field_name.removeprefix("extra.")
            if base_name not in MEASUREMENT_UNITS or value is None:
                continue
            if not _is_finite_number(value) or (base_name != "pH" and base_name != "temperature_C" and float(value) < 0):
                _add_info_action(
                    actions,
                    seen,
                    code="CASE-VALUE-001",
                    field=f"{section}.{field_name}",
                    priority="critical",
                    action_type="verify_measurement",
                    rationale="A quantitative value is non-numeric, non-finite, or negative for a nonnegative measurement.",
                    decision_impact="Correct the value and units before simulation or optimization.",
                )
            elif base_name == "pH" and not (0.0 <= float(value) <= 14.0):
                _add_info_action(
                    actions,
                    seen,
                    code="CASE-PH-001",
                    field=f"{section}.{field_name}",
                    priority="high",
                    action_type="verify_measurement",
                    rationale="Reported pH lies outside the conventional 0-14 aqueous range.",
                    decision_impact="Verify sample matrix before equilibrium/speciation modeling.",
                )

    if "nitrate" in contaminant_set or any(_has_value(v.get("nitrate_mg_L")) for v in (wq, targets)):
        bases = {}
        for section, extra in (("water_quality", water_extra), ("treatment_targets", target_extra)):
            bases[section] = _nitrate_basis(extra.get("nitrate_basis"))
            if bases[section] is None:
                _add_info_action(
                    actions,
                    seen,
                    code="CASE-NO3-001",
                    field=f"{section}.extra.nitrate_basis",
                    priority="high",
                    action_type="clarify_units",
                    rationale="The nitrate reporting basis is missing or unrecognized; specify as_N or as_NO3.",
                    decision_impact="Influent and target nitrate values cannot be compared until mass bases match.",
                )
        if all(bases.values()) and bases["water_quality"] != bases["treatment_targets"]:
            _add_info_action(
                actions,
                seen,
                code="CASE-NO3-002",
                field="treatment_targets.extra.nitrate_basis",
                priority="high",
                action_type="clarify_units",
                rationale="Influent and target nitrate concentrations use different mass bases.",
                decision_impact="Supply a documented common basis before simulation.",
            )

    if _has_value(wq.get("hardness_mg_L")) and (
        not isinstance(water_extra.get("hardness_basis"), str)
        or water_extra["hardness_basis"].strip().lower() in {"", "unknown", "unspecified"}
    ):
        _add_info_action(
            actions,
            seen,
            code="CASE-HARDNESS-001",
            field="water_quality.extra.hardness_basis",
            priority="medium",
            action_type="clarify_units",
            rationale="Hardness is reported in mg/L without an explicit reporting basis.",
            decision_impact="State basis (e.g. as CaCO3) for scaling calculations.",
        )

    design_flow = constraint_extra.get("design_flow_m3_day")
    if design_flow is None:
        _add_info_action(
            actions,
            seen,
            code="CASE-FLOW-001",
            field="constraints.extra.design_flow_m3_day",
            priority="medium",
            action_type="clarify_design_basis",
            rationale="A design flow in m³/day was not supplied; nominal 500 m³/day screening basis is assumed.",
            decision_impact="Provide explicit design flow for plant sizing, footprint, and LCOW accuracy.",
        )
    elif not _is_finite_number(design_flow) or float(design_flow) <= 0:
        _add_info_action(
            actions,
            seen,
            code="CASE-FLOW-002",
            field="constraints.extra.design_flow_m3_day",
            priority="critical",
            action_type="verify_measurement",
            rationale="Design flow must be a finite positive number in m³/day.",
            decision_impact="Correct declared flow before simulation.",
        )

    if source_water.lower() == "unknown":
        _add_info_action(
            actions,
            seen,
            code="CASE-001",
            field="source_water",
            priority="critical",
            action_type="clarify_context",
            rationale="The source-water type is not established.",
            decision_impact="Source-water context governs pretreatment selection and fouling risk.",
        )
    if not contaminants:
        _add_info_action(
            actions,
            seen,
            code="CASE-002",
            field="contaminants",
            priority="critical",
            action_type="identify_contaminants",
            rationale="No contaminant was mapped to the controlled taxonomy.",
            decision_impact="Cannot formulate treatment objectives without target constituents.",
        )
    if not any(_is_finite_number(rec["value"]) for rec in _measurement_records(wq)):
        _add_info_action(
            actions,
            seen,
            code="CASE-003",
            field="water_quality",
            priority="critical",
            action_type="provide_measurements",
            rationale="No measured source-water values were supplied.",
            decision_impact="Process simulation requires quantitative influent composition.",
        )

    for cname in contaminants:
        cspec = CONTAMINANT_SPECS.get(cname)
        if cspec is not None and not _has_value(wq.get(cspec.field)):
            _add_info_action(
                actions,
                seen,
                code="CASE-004",
                field=f"water_quality.{cspec.field}",
                priority="high",
                action_type="measure_influent",
                rationale=f"{cname} is listed, but its influent value is missing.",
                decision_impact="Influent concentration determines required log/mass removal and dosing.",
            )
        tfield = _TARGET_FIELDS.get(cname)
        tval = (
            target_extra.get(tfield.removeprefix("extra."))
            if tfield is not None and tfield.startswith("extra.")
            else targets.get(tfield)
        )
        if tfield is not None and not _has_value(tval):
            _add_info_action(
                actions,
                seen,
                code="CASE-005",
                field=f"treatment_targets.{tfield}",
                priority="high",
                action_type="clarify_target",
                rationale=f"No explicit effluent target was supplied for {cname}.",
                decision_impact="Simulation feasibility checks require quantitative effluent constraints.",
            )

    if not any(_has_value(v) for k, v in targets.items() if k != "extra") and not _has_value(target_extra):
        _add_info_action(
            actions,
            seen,
            code="CASE-006",
            field="treatment_targets",
            priority="high",
            action_type="clarify_target",
            rationale="No measurable treatment target or compliance standard was supplied.",
            decision_impact="Cannot certify water-quality feasibility without numeric endpoints.",
        )

    if constraints.get("use_for_drinking") is None:
        _add_info_action(
            actions,
            seen,
            code="CASE-007",
            field="constraints.use_for_drinking",
            priority="high",
            action_type="declare_constraint",
            rationale="The intended end use (drinking vs industrial/reuse) is unknown.",
            decision_impact="Drinking-water use triggers mandatory disinfection barriers.",
        )

    for field_name, code, impact in (
        ("brine_disposal", "CASE-008", "Brine disposal dictates whether unmitigated RO/NF/IX concentrate is admissible."),
        ("energy", "CASE-009", "Energy budget constrains high-pressure membranes and thermal brine concentration."),
        ("operator_skill", "CASE-010", "Operator capacity limits permissible process complexity."),
        ("chemical_dosing_allowed", "CASE-011", "Chemical restrictions govern oxidation, coagulation, softening, and chlorination."),
    ):
        if constraints.get(field_name) is None:
            _add_info_action(
                actions,
                seen,
                code=code,
                field=f"constraints.{field_name}",
                priority="medium",
                action_type="declare_constraint",
                rationale=f"The {field_name.replace('_', ' ')} constraint is not declared.",
                decision_impact=impact,
            )

    if "arsenic" in contaminant_set:
        speciation = water_extra.get("arsenic_speciation")
        if not isinstance(speciation, str) or speciation.strip().lower() in {"", "unknown", "unspecified", "not measured"}:
            _add_info_action(
                actions,
                seen,
                code="CASE-AS-003",
                field="water_quality.extra.arsenic_speciation",
                priority="medium",
                action_type="measure_speciation",
                rationale="Arsenic oxidation-state distribution As(III)/As(V) is unknown.",
                decision_impact="As(III) requires pre-oxidation for efficient adsorption/coagulation/RO removal.",
            )
        if not _has_value(wq.get("pH")):
            _add_info_action(
                actions,
                seen,
                code="CASE-AS-001",
                field="water_quality.pH",
                priority="high",
                action_type="measure_matrix",
                rationale="pH is missing for an arsenic-treatment case.",
                decision_impact="pH strongly governs As(V) sorption capacity and coagulant performance.",
            )
        if not _has_value(wq.get("iron_mg_L")):
            _add_info_action(
                actions,
                seen,
                code="CASE-AS-002",
                field="water_quality.iron_mg_L",
                priority="medium",
                action_type="measure_matrix",
                rationale="Background iron concentration is missing for arsenic treatment.",
                decision_impact="Iron co-precipitates arsenic and can foul membranes.",
            )

    actions.sort(key=lambda item: (_PRIORITY_ORDER[item["priority"]], item["field"]))
    critical_count = sum(a["priority"] == "critical" for a in actions)
    high_count = sum(a["priority"] == "high" for a in actions)
    status = "blocked" if critical_count else "needs_information" if high_count else "ready_for_screening"

    return {
        "case_state": {
            "schema_version": 2,
            "query_id": normalized.get("query_id", "unknown"),
            "source_water": source_water,
            "contaminants": contaminants,
            "measurements": _measurement_records(wq),
            "treatment_targets": _measurement_records(targets),
            "constraints": {k: v for k, v in constraints.items() if v is not None},
            "design_basis": {
                "design_flow_m3_day": design_flow,
                "sizing_ready": bool(_is_finite_number(design_flow) and float(design_flow) > 0),
                "interpretation": "Screening and closed-loop simulation optimize conceptual flowsheet structure and operating setpoints; site treatability validation remains required.",
            },
            "context": normalized.get("context"),
            "missing_fields": normalized.get("missing_fields", []),
            "assumptions": normalized.get("assumptions", []),
            "normalization_notes": normalized.get("normalization_notes", []),
        },
        "decision_readiness": {
            "status": status,
            "critical_blockers": [a for a in actions if a["priority"] == "critical"],
            "information_actions": actions,
            "summary": {
                "critical": critical_count,
                "high": high_count,
                "medium": sum(a["priority"] == "medium" for a in actions),
            },
            "interpretation": "Deterministic case-readiness screening; readiness is not a calibrated probability of compliance or performance.",
        },
    }


def _tokenize(text: str) -> set[str]:
    return {tok for tok in re.findall(r"[a-z0-9_]+", text.lower()) if len(tok) >= 2}


def retrieve_evidence(normalized: dict[str, Any], extra_records: list[dict[str, Any]] | None = None, top_k: int = 8) -> dict[str, Any]:
    """Retrieve relevant unit-level engineering evidence and template priors from HydroWeaver's KB."""
    source_water = str(normalized.get("source_water") or "").lower()
    contaminants = [str(c).lower() for c in normalized.get("contaminants", [])]
    context_text = str(normalized.get("context") or "")
    query_tokens = _tokenize(f"{source_water} {' '.join(contaminants)} {context_text}")

    unit_hits: list[dict[str, Any]] = []
    for unit_name, spec in UNIT_SPECS.items():
        doc_text = f"{unit_name} {' '.join(spec.target_contaminants)} {' '.join(spec.mechanisms)} {spec.evidence_summary}"
        doc_tokens = _tokenize(doc_text)
        contam_overlap = sum(1 for c in contaminants if c in spec.target_contaminants)
        lexical = len(query_tokens & doc_tokens) / max(1, len(query_tokens | doc_tokens))
        score = round(0.65 * (contam_overlap / max(1, len(contaminants))) + 0.35 * lexical, 4)
        if score > 0 or contam_overlap > 0:
            unit_hits.append(
                {
                    "source_id": spec.evidence_id,
                    "chunk_id": f"{spec.evidence_id}:unit",
                    "unit": unit_name,
                    "stage": spec.stage,
                    "target_contaminants": list(spec.target_contaminants),
                    "mechanisms": list(spec.mechanisms),
                    "text": spec.evidence_summary,
                    "relevance_score": score,
                }
            )
    unit_hits.sort(key=lambda item: (-item["relevance_score"], item["unit"]))

    template_hits: list[dict[str, Any]] = []
    for tpl in TEMPLATE_PRIORS:
        src_match = 1.0 if any(s in source_water or source_water in s for s in tpl.source_waters) else 0.0
        contam_match = sum(1 for c in contaminants if c in tpl.target_contaminants) / max(1, len(contaminants))
        score = round(0.4 * src_match + 0.6 * contam_match, 4)
        template_hits.append(
            {
                "source_id": tpl.template_id,
                "chunk_id": f"{tpl.template_id}:template",
                "title": tpl.title,
                "chain": list(tpl.chain),
                "text": f"{tpl.rationale} {tpl.notes}",
                "relevance_score": score,
            }
        )
    if extra_records:
        for idx, rec in enumerate(extra_records, start=1):
            text_val = f"{rec.get('title', '')} {rec.get('text', '')} {rec.get('summary', '')}".strip()
            rec_tokens = _tokenize(text_val)
            score = round(len(query_tokens & rec_tokens) / max(1, len(query_tokens | rec_tokens)), 4)
            target_list = template_hits if rec.get("kb_type") == "kb_case" else unit_hits
            target_list.append(
                {
                    "source_id": str(rec.get("id") or rec.get("case_id") or f"staged-{idx}"),
                    "chunk_id": f"staged-{idx}",
                    "text": text_val or "Staged knowledge entry",
                    "relevance_score": score,
                }
            )
    template_hits.sort(key=lambda item: (-item["relevance_score"], item["source_id"]))

    return {
        "query_id": normalized.get("query_id", "hydroweaver-case"),
        "kb_unit": unit_hits[:top_k],
        "kb_case": template_hits[:top_k],
        "total_retrieved": len(unit_hits[:top_k]) + len(template_hits[:top_k]),
    }


def knowledge_informed_candidates(normalized: dict[str, Any], top_k: int = 3) -> list[dict[str, Any]]:
    """Generate diverse knowledge-informed initial treatment-train configurations."""
    source_water = str(normalized.get("source_water") or "groundwater").lower()
    contaminants = [str(c).lower() for c in normalized.get("contaminants", [])]
    wq = normalized.get("water_quality") if isinstance(normalized.get("water_quality"), dict) else {}
    constraints = normalized.get("constraints") if isinstance(normalized.get("constraints"), dict) else {}

    brine_allowed = constraints.get("brine_disposal") is not False
    chem_allowed = constraints.get("chemical_dosing_allowed") is not False
    use_for_drinking = constraints.get("use_for_drinking") is not False

    scored: list[tuple[float, TemplatePrior]] = []
    for tpl in TEMPLATE_PRIORS:
        score = 0.0
        if any(s in source_water or source_water in s for s in tpl.source_waters):
            score += 2.0
        score += 2.5 * sum(1 for c in contaminants if c in tpl.target_contaminants)
        # Soft penalties so initial trains are plausible (some intentionally start slightly suboptimal or borderline for closed-loop improvement)
        if not chem_allowed and any(UNIT_SPECS[u].requires_chemical_dosing for u in tpl.chain):
            score -= 2.5
        if not brine_allowed and any(UNIT_SPECS[u].generates_brine for u in tpl.chain) and "Brine Concentrator" not in tpl.chain:
            score -= 1.2
        scored.append((score, tpl))
    scored.sort(key=lambda pair: (-pair[0], pair[1].template_id))

    candidates: list[dict[str, Any]] = []
    seen_chains: set[tuple[str, ...]] = set()
    for idx, (score, tpl) in enumerate(scored, start=1):
        chain = list(tpl.chain)
        if tuple(chain) in seen_chains:
            continue
        seen_chains.add(tuple(chain))
        # Ensure high-TDS brackish/seawater scenarios always include a membrane option in top_k
        candidates.append(
            {
                "chain_id": f"hw-init-{len(candidates) + 1}",
                "template_id": tpl.template_id,
                "chain": chain,
                "rationale": tpl.rationale,
                "prior_score": round(score, 3),
                "evidence_ids": [tpl.template_id] + [UNIT_SPECS[u].evidence_id for u in chain if u in UNIT_SPECS],
            }
        )
        if len(candidates) >= top_k:
            break

    # Guarantee structural diversity: if high TDS (>1500 mg/L) or nitrate is present and no RO/IX in shortlist, inject one
    tds = float(wq.get("tds_mg_L") or 0.0)
    if tds > 1500.0 and not any("Reverse Osmosis" in c["chain"] for c in candidates):
        ro_chain = ["Media Filtration", "Pumping", "Reverse Osmosis", "Energy Recovery"]
        if use_for_drinking:
            ro_chain.append("Chlorination" if chem_allowed else "UV Disinfection")
        candidates[-1] = {
            "chain_id": f"hw-init-{len(candidates)}",
            "template_id": "TPL-BWRO-ERD",
            "chain": ro_chain,
            "rationale": "High TDS requires membrane desalination with energy recovery.",
            "prior_score": 1.0,
            "evidence_ids": [UNIT_SPECS[u].evidence_id for u in ro_chain],
        }
    return candidates


def canonicalize_chain(chain: list[str]) -> list[str]:
    """Normalize unit aliases and sort strictly into feasible hydraulic process stage order."""
    normalized: list[str] = []
    for raw in chain:
        canon = normalize_unit_name(raw)
        if canon is None:
            raise ValueError(f"Unknown treatment unit: {raw}")
        if canon not in normalized:
            normalized.append(canon)
    normalized.sort(key=lambda u: UNIT_SPECS[u].stage_order)
    return normalized


def default_parameters_for_chain(chain: list[str], case: dict[str, Any] | None = None) -> dict[str, dict[str, float]]:
    """Build initial default operating parameters for every unit in a chain."""
    wq = (case or {}).get("water_quality") if isinstance((case or {}).get("water_quality"), dict) else {}
    tds = float(wq.get("tds_mg_L") or 500.0)
    params: dict[str, dict[str, float]] = {}
    for unit in chain:
        spec = UNIT_SPECS.get(unit)
        if spec is None:
            continue
        unit_params = {p.name: p.default for p in spec.params}
        # Knowledge-informed pressure initialization based on osmotic pressure
        if unit == "Pumping":
            pi_bar = 0.00078 * tds
            if "Reverse Osmosis" in chain:
                unit_params["feed_pressure_bar"] = min(82.0, max(8.0, round(pi_bar * 2.4 + 7.5, 2)))
            elif "Nanofiltration" in chain:
                unit_params["feed_pressure_bar"] = min(25.0, max(5.0, round(pi_bar * 1.4 + 5.5, 2)))
            else:
                unit_params["feed_pressure_bar"] = 4.0
        elif unit == "Reverse Osmosis":
            pi_bar = 0.00078 * tds
            unit_params["feed_pressure_bar"] = min(82.0, max(8.0, round(pi_bar * 2.4 + 7.5, 2)))
            unit_params["recovery"] = 0.48 if tds > 15000 else 0.72 if tds < 5000 else 0.60
        params[unit] = unit_params
    return params


def kb_corpus_chunks() -> list[dict[str, Any]]:
    """Return all built-in unit and template knowledge chunks for local index building."""
    chunks: list[dict[str, Any]] = []
    for unit_name, spec in UNIT_SPECS.items():
        chunks.append(
            {
                "id": spec.evidence_id,
                "kind": "unit",
                "unit": unit_name,
                "stage": spec.stage,
                "target_contaminants": list(spec.target_contaminants),
                "mechanisms": list(spec.mechanisms),
                "text": spec.evidence_summary,
            }
        )
    for tpl in TEMPLATE_PRIORS:
        chunks.append(
            {
                "id": tpl.template_id,
                "kind": "template",
                "title": tpl.title,
                "chain": list(tpl.chain),
                "target_contaminants": list(tpl.target_contaminants),
                "text": f"{tpl.rationale} {tpl.notes}",
            }
        )
    for cname, cspec in CONTAMINANT_SPECS.items():
        chunks.append(
            {
                "id": cspec.evidence_id,
                "kind": "contaminant",
                "contaminant": cname,
                "unit": cspec.unit,
                "reference_limit": cspec.reference_limit,
                "text": cspec.reference_note,
            }
        )
    return chunks
