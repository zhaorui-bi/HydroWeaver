"""Unit mapping between HydroWeaver canonical unit names and WaterTAP unit models.

The mapping is data, not code: adding a unit model means adding one entry and a
test. A unit with no entry is flagged as unsupported in the WaterTAP flowsheet
(while remaining covered by HydroWeaver's built-in multi-constituent process
simulator); the WaterTAP runner never silently substitutes a different unit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class UnitSpec:
    """One supported WaterTAP unit or flowsheet model."""

    model: str  # dotted import path of the WaterTAP unit or flowsheet model
    kind: str  # pump | membrane | dosing | asm1_flowsheet | bsm2_flowsheet | bio_*
    canonical: str  # canonical HydroWeaver unit name
    family: str = "nacl"  # nacl | asm1 | bsm2


SUPPORTED_FLOWSHEETS: tuple[str, ...] = ("NaCl", "ASM1", "BSM2")

# kind values: "pump", "membrane", "dosing", "asm1_flowsheet", "bsm2_flowsheet", "bio_*"
SUPPORTED_UNITS: dict[str, UnitSpec] = {
    "Pumping": UnitSpec("watertap.unit_models.pressure_changer.Pump", "pump", "Pumping", "nacl"),
    "Reverse Osmosis": UnitSpec("watertap.unit_models.reverse_osmosis_0D.ReverseOsmosis0D", "membrane", "Reverse Osmosis", "nacl"),
    "Nanofiltration": UnitSpec("watertap.unit_models.reverse_osmosis_0D.ReverseOsmosis0D", "membrane", "Nanofiltration", "nacl"),
    "Activated Sludge (ASM1)": UnitSpec(
        "watertap.flowsheets.activated_sludge.ASM1_flowsheet",
        "asm1_flowsheet",
        "Activated Sludge (ASM1)",
        "asm1",
    ),
    "Anoxic Reactor": UnitSpec("watertap.unit_models.cstr.CSTR", "bio_anoxic", "Anoxic Reactor", "asm1"),
    "Aerobic Reactor": UnitSpec(
        "watertap.unit_models.aeration_tank.AerationTank",
        "bio_aerobic",
        "Aerobic Reactor",
        "asm1",
    ),
    "Secondary Clarifier": UnitSpec(
        "watertap.unit_models.clarifier.Clarifier",
        "bio_secondary_clarifier",
        "Secondary Clarifier",
        "asm1",
    ),
    "BSM2 Full Plant": UnitSpec(
        "watertap.flowsheets.full_water_resource_recovery_facility.BSM2",
        "bsm2_flowsheet",
        "BSM2 Full Plant",
        "bsm2",
    ),
    "Primary Clarifier": UnitSpec(
        "watertap.unit_models.clarifier.Clarifier",
        "bio_primary_clarifier",
        "Primary Clarifier",
        "bsm2",
    ),
    "Sludge Thickener": UnitSpec(
        "watertap.unit_models.thickener.Thickener",
        "bio_thickener",
        "Sludge Thickener",
        "bsm2",
    ),
    "Anaerobic Digester": UnitSpec(
        "watertap.unit_models.anaerobic_digester.AD",
        "bio_adm1",
        "Anaerobic Digester",
        "bsm2",
    ),
    "Sludge Dewatering": UnitSpec(
        "watertap.unit_models.dewatering.DewateringUnit",
        "bio_dewatering",
        "Sludge Dewatering",
        "bsm2",
    ),
}

# Case-insensitive aliases seen in taxonomy data and caller-supplied chains.
ALIASES: dict[str, str] = {
    "pump": "Pumping",
    "feed pump": "Pumping",
    "booster pump": "Pumping",
    "high pressure pump": "Pumping",
    "ro": "Reverse Osmosis",
    "reverse osmosis": "Reverse Osmosis",
    "membrane separation": "Reverse Osmosis",
    "brackish ro": "Reverse Osmosis",
    "seawater ro": "Reverse Osmosis",
    "nf": "Nanofiltration",
    "nanofiltration": "Nanofiltration",
    "asm1": "Activated Sludge (ASM1)",
    "asm1 flowsheet": "Activated Sludge (ASM1)",
    "activated sludge": "Activated Sludge (ASM1)",
    "activated sludge asm1": "Activated Sludge (ASM1)",
    "mle": "Activated Sludge (ASM1)",
    "anoxic reactor": "Anoxic Reactor",
    "anoxic cstr": "Anoxic Reactor",
    "anoxic tank": "Anoxic Reactor",
    "denitrification reactor": "Anoxic Reactor",
    "aerobic reactor": "Aerobic Reactor",
    "aeration tank": "Aerobic Reactor",
    "aerobic cstr": "Aerobic Reactor",
    "nitrification reactor": "Aerobic Reactor",
    "secondary clarifier": "Secondary Clarifier",
    "final clarifier": "Secondary Clarifier",
    "bsm2": "BSM2 Full Plant",
    "bsm2 plant": "BSM2 Full Plant",
    "bsm2 full plant": "BSM2 Full Plant",
    "wrrf": "BSM2 Full Plant",
    "asm1-adm1": "BSM2 Full Plant",
    "asm1 adm1": "BSM2 Full Plant",
    "primary clarifier": "Primary Clarifier",
    "primary settling": "Primary Clarifier",
    "sludge thickener": "Sludge Thickener",
    "thickener": "Sludge Thickener",
    "gravity thickener": "Sludge Thickener",
    "anaerobic digester": "Anaerobic Digester",
    "adm1": "Anaerobic Digester",
    "anaerobic digestion": "Anaerobic Digester",
    "sludge digester": "Anaerobic Digester",
    "sludge dewatering": "Sludge Dewatering",
    "dewatering": "Sludge Dewatering",
    "centrifuge dewatering": "Sludge Dewatering",
}

UNSUPPORTED_EXAMPLES = (
    "Adsorption",
    "Coagulation",
    "Sedimentation",
    "Media Filtration",
    "Ion Exchange",
    "Advanced Oxidation",
    "Ultrafiltration",
    "Microfiltration",
    "Chlorination",
)


def normalize_unit(name: str) -> str | None:
    """Return the canonical supported WaterTAP unit name, or None when unsupported."""
    key = " ".join(str(name).replace("_", " ").split()).strip().lower()
    if key == "":
        return None
    if key in ALIASES:
        return ALIASES[key]
    for canonical in SUPPORTED_UNITS:
        if canonical.lower() == key:
            return canonical
    return None


def classify(chain: list[str]) -> dict[str, Any]:
    """Split a candidate chain into WaterTAP-modeled and unsupported units."""
    modeled: list[str] = []
    unsupported: list[str] = []
    for unit in chain:
        canonical = normalize_unit(unit)
        if canonical is None or canonical not in SUPPORTED_UNITS:
            unsupported.append(str(unit))
        else:
            modeled.append(canonical)
    return {
        "modeled": modeled,
        "unsupported": unsupported,
        "specs": [SUPPORTED_UNITS[name] for name in modeled],
    }


def select_flowsheet_family(specs: list[UnitSpec], options: dict[str, Any] | None = None) -> str:
    """Select the WaterTAP flowsheet family ('nacl', 'asm1', or 'bsm2')."""
    opts = options if isinstance(options, dict) else {}
    for key in ("flowsheet_model", "property_package"):
        raw = str(opts.get(key) or "").strip().lower()
        if raw in {"asm1", "bsm2", "nacl"}:
            return raw
    families = {spec.family for spec in specs}
    if "bsm2" in families:
        return "bsm2"
    if "asm1" in families:
        return "asm1"
    return "nacl"
