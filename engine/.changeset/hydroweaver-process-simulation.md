---
"hydroweaver": minor
---

Add optional WaterTAP/IDAES/IPOPT process simulation: point HYDROWEAVER_SIM_PYTHON at a Python 3.10 environment with WaterTAP, then ask for `hydroweaver_simulate_train` to build a candidate train as a flowsheet and solve it with IPOPT, reporting recovery, pressure, power, membrane area, solver status, and unit coverage.
