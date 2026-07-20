"""Workflow data model: WorkflowDef, WorkflowStepDef, ParallelGroupDef.

All workflow YAML loading, validation, migration, and serialization
lives here. Extracted from ``orchestrator.py`` to reduce module size.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

import yaml

from sccsos.core.step_executor import WorkflowError


# ── Exceptions ──────────────────────────────────────────────────────


class WorkflowValidationError(WorkflowError):
    """Workflow YAML is invalid."""
    pass


# ── Data Models ─────────────────────────────────────────────────────


@dataclass
class WorkflowStepDef:
    """Definition of a single workflow step."""
    id: str
    name: str = ""
    agent: str = "architect"
    prompt: str = ""
    input: Optional[str] = None
    output: Optional[str] = None
    depends_on: list[str] = field(default_factory=list)
    timeout: int = 600
    retry: int = 0
    condition: Optional[str] = None  # Jinja2 expression; falsy → skip step


@dataclass
class ParallelGroupDef:
    """A group of steps that can run concurrently."""
    id: str
    steps: list[str] = field(default_factory=list)
    max_concurrent: int = 2


@dataclass
class WorkflowDef:
    """Complete workflow definition loaded from YAML.

    Attributes:
        name: Human-readable workflow name.
        schema_version: Workflow schema version for migration support.
            Current: "1.0" (original), "1.1" (adds schema_version field).
        version: User-facing workflow version (for change tracking).
        description: Description of the workflow's purpose.
        steps: Ordered list of workflow steps.
        parallel_groups: Optional parallel execution groups.
    """
    name: str
    schema_version: str = "1.1"
    version: str = "1.0"
    description: str = ""
    steps: list[WorkflowStepDef] = field(default_factory=list)
    parallel_groups: list[ParallelGroupDef] = field(default_factory=list)

    @classmethod
    def from_yaml(cls, path: str | Path) -> "WorkflowDef":
        """Load a WorkflowDef from a YAML file with schema validation and migration."""
        path = Path(path)
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        if not data or "name" not in data:
            raise WorkflowValidationError(
                f"Workflow YAML must have a 'name' field: {path}"
            )

        # Schema migration
        data = _migrate_workflow_schema(data)

        if not isinstance(data.get("steps"), list) or len(data["steps"]) == 0:
            raise WorkflowValidationError(
                f"Workflow '{data.get('name', '?')}' must have at least one step: {path}"
            )

        # Validate each step definition
        step_ids = set()
        for i, s in enumerate(data["steps"]):
            if not isinstance(s, dict):
                raise WorkflowValidationError(
                    f"Workflow '{data.get('name', '?')}' step[{i}] is not a dict: {path}"
                )
            if "id" not in s or not isinstance(s["id"], str) or not s["id"].strip():
                raise WorkflowValidationError(
                    f"Workflow '{data.get('name', '?')}' step[{i}] missing 'id' field: {path}"
                )
            if s["id"] in step_ids:
                raise WorkflowValidationError(
                    f"Workflow '{data.get('name', '?')}' duplicate step ID '{s['id']}': {path}"
                )
            step_ids.add(s["id"])
            if "agent" not in s:
                raise WorkflowValidationError(
                    f"Workflow '{data.get('name', '?')}' step '{s['id']}' missing 'agent' field: {path}"
                )
            if "prompt" not in s and "condition" not in s and "input" not in s:
                raise WorkflowValidationError(
                    f"Workflow '{data.get('name', '?')}' step '{s['id']}' "
                    f"must have 'prompt', 'input', or 'condition': {path}"
                )
            if "timeout" in s and (not isinstance(s["timeout"], int) or s["timeout"] < 1):
                raise WorkflowValidationError(
                    f"Workflow '{data.get('name', '?')}' step '{s['id']}' "
                    f"invalid 'timeout': must be positive integer: {path}"
                )
            if "retry" in s and (not isinstance(s["retry"], int) or s["retry"] < 0):
                raise WorkflowValidationError(
                    f"Workflow '{data.get('name', '?')}' step '{s['id']}' "
                    f"invalid 'retry': must be non-negative integer: {path}"
                )
            if "depends_on" in s:
                if not isinstance(s["depends_on"], list):
                    raise WorkflowValidationError(
                        f"Workflow '{data.get('name', '?')}' step '{s['id']}' "
                        f"'depends_on' must be a list: {path}"
                    )
                for dep in s["depends_on"]:
                    if not isinstance(dep, str):
                        raise WorkflowValidationError(
                            f"Workflow '{data.get('name', '?')}' step '{s['id']}' "
                            f"dependency '{dep}' is not a string: {path}"
                        )

        # Validate parallel_groups
        for gi, g in enumerate(data.get("parallel_groups", [])):
            if not isinstance(g, dict):
                raise WorkflowValidationError(
                    f"Workflow '{data.get('name', '?')}' parallel_group[{gi}] is not a dict: {path}"
                )
            if "id" not in g:
                raise WorkflowValidationError(
                    f"Workflow '{data.get('name', '?')}' parallel_group[{gi}] missing 'id': {path}"
                )
            if "steps" not in g or not isinstance(g["steps"], list):
                raise WorkflowValidationError(
                    f"Workflow '{data.get('name', '?')}' parallel_group '{g.get('id', '?')}' "
                    f"missing or invalid 'steps' list: {path}"
                )
            for sid in g["steps"]:
                if sid not in step_ids:
                    raise WorkflowValidationError(
                        f"Workflow '{data.get('name', '?')}' parallel_group '{g['id']}' "
                        f"references unknown step '{sid}': {path}"
                    )

        steps = [WorkflowStepDef(**s) for s in data.get("steps", [])]
        parallel_groups = [ParallelGroupDef(**g) for g in data.get("parallel_groups", [])]

        return cls(
            name=data["name"],
            version=data.get("version", "1.0"),
            description=data.get("description", ""),
            steps=steps,
            parallel_groups=parallel_groups,
        )

    def to_yaml(self) -> str:
        """Serialize back to YAML."""
        data = {
            "name": self.name,
            "schema_version": self.schema_version,
            "version": self.version,
            "description": self.description,
            "steps": [asdict(s) for s in self.steps],
        }
        if self.parallel_groups:
            data["parallel_groups"] = [asdict(g) for g in self.parallel_groups]
        return yaml.dump(data, default_flow_style=False, allow_unicode=True,
                         sort_keys=False)

    def to_mermaid(self) -> str:
        """Generate a Mermaid flowchart from the workflow DAG."""
        if not self.steps:
            return "```mermaid\nflowchart TD\n  empty[\"(no steps)\"]\n```"

        step_map = {s.id: s for s in self.steps}
        lines = ["```mermaid", "flowchart TD", ""]

        for s in self.steps:
            label = (s.name or s.id).replace('"', "'")
            label = label.replace("[", "(").replace("]", ")")
            lines.append(f'    {s.id}["{label}"]')

        lines.append("")
        for s in self.steps:
            for dep in s.depends_on:
                if dep in step_map:
                    lines.append(f"    {dep} --> {s.id}")

        for g in self.parallel_groups:
            if len(g.steps) > 1:
                label = (g.id or "parallel").replace('"', "'")
                lines.append("")
                lines.append(f"    subgraph {label} [\"{label}\"]")
                for sid in g.steps:
                    lines.append(f"        {sid}")
                lines.append("    end")

        lines.append("```")
        return "\n".join(lines)


# ── Schema Migration ────────────────────────────────────────────────

_MIGRATIONS: dict[tuple[str, str], callable] = {}


def _register_migration(from_version: str, to_version: str):
    """Decorator to register a schema migration."""
    def decorator(fn):
        _MIGRATIONS[(from_version, to_version)] = fn
        return fn
    return decorator


def _migrate_workflow_schema(data: dict) -> dict:
    """Migrate a workflow's raw YAML dict to the latest schema version."""
    LATEST = "1.1"
    current = data.get("schema_version", "1.0")

    if current == LATEST:
        return data

    versions = ["1.0", "1.1"]
    if current not in versions:
        raise WorkflowValidationError(
            f"Unknown workflow schema_version '{current}'. "
            f"Expected one of: {versions}"
        )

    result = dict(data)
    start_idx = versions.index(current)

    for i in range(start_idx, len(versions) - 1):
        from_v = versions[i]
        to_v = versions[i + 1]
        migrator = _MIGRATIONS.get((from_v, to_v))
        if migrator is not None:
            result = migrator(result)
        result["schema_version"] = to_v

    return result


@_register_migration("1.0", "1.1")
def _migrate_1_0_to_1_1(data: dict) -> dict:
    """1.0 → 1.1: Add schema_version field and normalize step defaults."""
    result = dict(data)
    result["schema_version"] = "1.1"

    steps = []
    for s in result.get("steps", []):
        step = dict(s)
        if "id" in step:
            step.setdefault("name", step["id"])
        step.setdefault("timeout", 600)
        step.setdefault("retry", 0)
        step.setdefault("depends_on", [])
        steps.append(step)
    result["steps"] = steps

    return result
