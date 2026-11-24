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
    """One supported WaterTAP unit model."""

    model: str  # dotted import path of the WaterTAP unit model
    kind: str  # pump | membrane | dosing
    canonical: str  # canonical HydroWeaver unit name


# kind values: "pump", "membrane", "dosing"
SUPPORTED_UNITS: dict[str, UnitSpec] = {
    "Pumping": UnitSpec("watertap.unit_models.pressure_changer.Pump", "pump", "Pumping"),
    "Reverse Osmosis": UnitSpec("watertap.unit_models.reverse_osmosis_0D.ReverseOsmosis0D", "membrane", "Reverse Osmosis"),
    "Nanofiltration": UnitSpec("watertap.unit_models.reverse_osmosis_0D.ReverseOsmosis0D", "membrane", "Nanofiltration"),
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
