"""Unit mapping between OpenAqua taxonomy names and WaterTAP unit models.

The mapping is data, not code: adding a unit model means adding one entry and a
test. A unit with no entry is unsupported; the runner never silently
substitutes a different unit. See docs/SIMULATION.md for the design and the
scientific scope limits.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class UnitSpec:
    """One supported unit model."""

    model: str  # dotted import path of the WaterTAP unit model
    kind: str  # pump | membrane | dosing
    canonical: str  # canonical OpenAqua-side unit name


# kind values: "pump", "membrane", "dosing"
SUPPORTED_UNITS: dict[str, UnitSpec] = {
    'Pumping': UnitSpec('watertap.unit_models.pressure_changer.Pump', 'pump', 'Pumping'),
    'Reverse Osmosis': UnitSpec('watertap.unit_models.reverse_osmosis_0D.ReverseOsmosis0D', 'membrane', 'Reverse Osmosis'),
    'Nanofiltration': UnitSpec('watertap.unit_models.reverse_osmosis_0D.ReverseOsmosis0D', 'membrane', 'Nanofiltration'),
}

# Case-insensitive aliases seen in taxonomy data and caller-supplied chains.
ALIASES: dict[str, str] = {
    'pump': 'Pumping',
    'feed pump': 'Pumping',
    'booster pump': 'Pumping',
    'ro': 'Reverse Osmosis',
    'reverse osmosis': 'Reverse Osmosis',
    'membrane separation': 'Reverse Osmosis',
    'nf': 'Nanofiltration',
    'nanofiltration': 'Nanofiltration',
}
UNSUPPORTED_EXAMPLES = (
    'Adsorption',
    'Coagulation',
    'Sedimentation',
    'Media Filtration',
    'Ion Exchange',
    'Advanced Oxidation',
    'Ultrafiltration',
    'Microfiltration',
    'Chlorination',
)


def normalize_unit(name: str) -> str | None:
    """Return the canonical supported unit name, or None when unsupported."""
    key = ' '.join(str(name).replace('_', ' ').split()).strip().lower()
    if key == '':
        return None
    if key in ALIASES:
        return ALIASES[key]
    for canonical in SUPPORTED_UNITS:
        if canonical.lower() == key:
            return canonical
    return None

def classify(chain: list[str]) -> dict[str, Any]:
    """Split a candidate chain into modeled and unsupported units.

    Every input unit appears exactly once in exactly one list; the order of the
    original chain is preserved inside each list so the flowsheet keeps the
    declared sequence.
    """
    modeled: list[str] = []
    unsupported: list[str] = []
    for unit in chain:
        canonical = normalize_unit(unit)
        if canonical is None or canonical not in SUPPORTED_UNITS:
            unsupported.append(str(unit))
        else:
            modeled.append(canonical)
    return {
        'modeled': modeled,
        'unsupported': unsupported,
        'specs': [SUPPORTED_UNITS[name] for name in modeled],
    }
