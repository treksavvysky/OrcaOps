"""
Workflow schema loading, validation, and utilities.

Handles YAML parsing, DAG cycle detection, condition expression parsing,
and matrix expansion.
"""

import itertools
import re
from graphlib import TopologicalSorter, CycleError
from typing import Dict, List, Optional, Set

import yaml

from orcaops.schemas import WorkflowSpec, WorkflowJob, MatrixConfig


class WorkflowValidationError(Exception):
    """Raised when a workflow spec fails validation."""
    pass


def load_workflow_spec(yaml_path: str) -> WorkflowSpec:
    """Load and validate a WorkflowSpec from a YAML file."""
    with open(yaml_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return parse_workflow_spec(data)


def parse_workflow_spec(data: dict) -> WorkflowSpec:
    """Parse raw dict into WorkflowSpec, setting job names from dict keys."""
    if "jobs" in data:
        for job_name, job_data in data["jobs"].items():
            if isinstance(job_data, dict):
                if "name" not in job_data:
                    job_data["name"] = job_name
                # Handle shorthand service syntax: services: ["postgres:15", "redis:7"]
                if "services" in job_data and isinstance(job_data["services"], list):
                    services_dict = {}
                    for svc in job_data["services"]:
                        if isinstance(svc, str):
                            svc_name = svc.split(":")[0].split("/")[-1]
                            services_dict[svc_name] = {"image": svc}
                        elif isinstance(svc, dict):
                            for k, v in svc.items():
                                services_dict[k] = v
                    job_data["services"] = services_dict
                # Handle matrix shorthand: matrix: {python: [...], os: [...]}
                if "matrix" in job_data and isinstance(job_data["matrix"], dict):
                    raw_matrix = job_data["matrix"]
                    if "parameters" not in raw_matrix:
                        exclude = raw_matrix.pop("exclude", [])
                        include = raw_matrix.pop("include", [])
                        job_data["matrix"] = {
                            "parameters": dict(raw_matrix),
                            "exclude": exclude,
                            "include": include,
                        }

    spec = WorkflowSpec.model_validate(data)
    validate_workflow(spec)
    return spec


def validate_workflow(spec: WorkflowSpec) -> None:
    """Validate workflow DAG: no cycles, all references exist."""
    job_names = set(spec.jobs.keys())

    # Check that all requires references point to existing jobs
    for name, job in spec.jobs.items():
        for dep in job.requires:
            if dep not in job_names:
                raise WorkflowValidationError(
                    f"Job '{name}' requires unknown job '{dep}'"
                )

    # Check for cycles using graphlib
    graph: Dict[str, Set[str]] = {}
    for name, job in spec.jobs.items():
        graph[name] = set(job.requires)

    try:
        ts = TopologicalSorter(graph)
        ts.prepare()
    except CycleError as e:
        raise WorkflowValidationError(f"Circular dependency detected: {e}")

    # Validate condition syntax
    for name, job in spec.jobs.items():
        if job.if_condition:
            _validate_condition_syntax(job.if_condition, name)


def _validate_condition_syntax(condition: str, job_name: str) -> None:
    """Validate that a condition expression uses supported syntax."""
    stripped = condition.strip()
    if not (stripped.startswith("${{") and stripped.endswith("}}")):
        raise WorkflowValidationError(
            f"Job '{job_name}' condition must be wrapped in ${{{{ ... }}}}, got: {condition}"
        )
    inner = stripped[3:-2].strip()
    allowed_pattern = (
        r"^(jobs\.\w+\.status|env\.\w+)\s*(==|!=)\s*'[^']*'"
        r"(\s+(and|or)\s+(jobs\.\w+\.status|env\.\w+)\s*(==|!=)\s*'[^']*')*$"
    )
    if not re.match(allowed_pattern, inner):
        raise WorkflowValidationError(
            f"Job '{job_name}' condition has unsupported syntax: {inner}"
        )


def get_execution_order(spec: WorkflowSpec) -> List[List[str]]:
    """
    Return execution levels: list of lists of job names.
    Jobs within a level have no dependencies on each other and can run in parallel.
    """
    graph: Dict[str, Set[str]] = {}
    for name, job in spec.jobs.items():
        graph[name] = set(job.requires)

    ts = TopologicalSorter(graph)
    ts.prepare()

    levels: List[List[str]] = []
    while ts.is_active():
        ready = list(ts.get_ready())
        levels.append(sorted(ready))
        for node in ready:
            ts.done(node)

    return levels


def expand_matrix(matrix: MatrixConfig) -> List[Dict[str, str]]:
    """
    Expand a matrix configuration into a list of parameter combinations.
    Applies exclude/include rules.
    """
    if not matrix.parameters:
        return [{}]

    keys = sorted(matrix.parameters.keys())
    values = [matrix.parameters[k] for k in keys]
    combinations = [dict(zip(keys, combo)) for combo in itertools.product(*values)]

    # Apply excludes
    filtered = []
    for combo in combinations:
        excluded = False
        for exc in matrix.exclude:
            if all(combo.get(k) == v for k, v in exc.items()):
                excluded = True
                break
        if not excluded:
            filtered.append(combo)

    # Apply includes (add additional combinations)
    for inc in matrix.include:
        if inc not in filtered:
            filtered.append(inc)

    return filtered


def matrix_key(params: Dict[str, str]) -> str:
    """Generate a deterministic string key for a matrix combination."""
    return ",".join(f"{k}={v}" for k, v in sorted(params.items()))


class ConditionEvaluator:
    """
    Evaluates ${{ ... }} condition expressions safely.

    Supports:
      - jobs.<name>.status == 'success'
      - env.<name> == 'value'
      - and / or operators
    """

    def __init__(
        self,
        job_statuses: Dict[str, str],
        env: Dict[str, str],
    ):
        self.job_statuses = job_statuses
        self.env = env

    def evaluate(self, condition: str) -> bool:
        """Evaluate a condition expression, return True if job should run."""
        stripped = condition.strip()
        if not (stripped.startswith("${{") and stripped.endswith("}}")):
            return True
        inner = stripped[3:-2].strip()
        return self._eval_expr(inner)

    def _eval_expr(self, expr: str) -> bool:
        """Evaluate a boolean expression with 'and'/'or' operators."""
        # Split on ' or ' first (lower precedence)
        or_parts = re.split(r'\s+or\s+', expr)
        if len(or_parts) > 1:
            return any(self._eval_expr(part) for part in or_parts)

        # Split on ' and '
        and_parts = re.split(r'\s+and\s+', expr)
        if len(and_parts) > 1:
            return all(self._eval_expr(part) for part in and_parts)

        # Single comparison
        match = re.match(r"^([\w.]+)\s*(==|!=)\s*'([^']*)'$", expr.strip())
        if not match:
            return True

        ref, op, value = match.group(1), match.group(2), match.group(3)
        actual = self._resolve_ref(ref)

        if op == "==":
            return actual == value
        elif op == "!=":
            return actual != value
        return True

    def _resolve_ref(self, ref: str) -> str:
        """Resolve jobs.build.status or env.VAR to its value."""
        parts = ref.split(".")
        if len(parts) == 3 and parts[0] == "jobs" and parts[2] == "status":
            return self.job_statuses.get(parts[1], "unknown")
        elif len(parts) == 2 and parts[0] == "env":
            return self.env.get(parts[1], "")
        return ""
