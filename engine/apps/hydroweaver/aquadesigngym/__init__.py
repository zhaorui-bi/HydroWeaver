"""AquaDesignGym: Interactive benchmarking environment for water-treatment train design.

Couples standardized design tasks and admissible structural/parametric actions with
a matched-budget process-simulation oracle for evaluating agentic frameworks,
conventional optimizers, component ablations, and robustness under varying influent conditions.
"""

from __future__ import annotations

from .baselines import METHOD_REGISTRY, run_method
from .env import AquaDesignGymEnv
from .evaluate import evaluate_benchmark
from .tasks import BENCHMARK_TASKS, apply_influent_perturbation, get_task, list_tasks

__all__ = [
    "AquaDesignGymEnv",
    "BENCHMARK_TASKS",
    "METHOD_REGISTRY",
    "apply_influent_perturbation",
    "evaluate_benchmark",
    "get_task",
    "list_tasks",
    "run_method",
]
