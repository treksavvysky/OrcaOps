"""Tests for workflow schema loading, validation, and utilities."""

import os
import tempfile

import pytest
import yaml

from orcaops.schemas import WorkflowSpec, MatrixConfig
from orcaops.workflow_schema import (
    WorkflowValidationError,
    load_workflow_spec,
    parse_workflow_spec,
    validate_workflow,
    get_execution_order,
    expand_matrix,
    matrix_key,
    ConditionEvaluator,
)


def _minimal_spec(jobs=None):
    """Return a minimal valid workflow spec dict."""
    if jobs is None:
        jobs = {
            "build": {
                "image": "python:3.11",
                "commands": ["echo hello"],
            }
        }
    return {"name": "test-workflow", "jobs": jobs}


class TestParseWorkflowSpec:
    def test_minimal_valid_spec(self):
        spec = parse_workflow_spec(_minimal_spec())
        assert spec.name == "test-workflow"
        assert "build" in spec.jobs
        assert spec.jobs["build"].name == "build"
        assert spec.jobs["build"].image == "python:3.11"

    def test_full_spec_with_env_and_description(self):
        data = _minimal_spec()
        data["description"] = "A test workflow"
        data["env"] = {"APP_VERSION": "1.0.0"}
        data["timeout"] = 1800
        spec = parse_workflow_spec(data)
        assert spec.description == "A test workflow"
        assert spec.env["APP_VERSION"] == "1.0.0"
        assert spec.timeout == 1800

    def test_service_shorthand_list(self):
        data = _minimal_spec({
            "test": {
                "image": "python:3.11",
                "commands": ["pytest"],
                "services": ["postgres:15", "redis:7"],
            }
        })
        spec = parse_workflow_spec(data)
        assert "postgres" in spec.jobs["test"].services
        assert spec.jobs["test"].services["postgres"].image == "postgres:15"
        assert "redis" in spec.jobs["test"].services
        assert spec.jobs["test"].services["redis"].image == "redis:7"

    def test_matrix_shorthand(self):
        data = _minimal_spec({
            "test": {
                "image": "python:3.11",
                "commands": ["pytest"],
                "matrix": {
                    "python": ["3.9", "3.10", "3.11"],
                    "os": ["ubuntu", "alpine"],
                },
            }
        })
        spec = parse_workflow_spec(data)
        matrix = spec.jobs["test"].matrix
        assert matrix is not None
        assert matrix.parameters["python"] == ["3.9", "3.10", "3.11"]
        assert matrix.parameters["os"] == ["ubuntu", "alpine"]

    def test_matrix_shorthand_with_exclude(self):
        data = _minimal_spec({
            "test": {
                "image": "python:3.11",
                "commands": ["pytest"],
                "matrix": {
                    "python": ["3.9", "3.10"],
                    "exclude": [{"python": "3.9"}],
                },
            }
        })
        spec = parse_workflow_spec(data)
        assert spec.jobs["test"].matrix.exclude == [{"python": "3.9"}]

    def test_job_with_requires(self):
        data = _minimal_spec({
            "build": {"image": "python:3.11", "commands": ["make build"]},
            "test": {
                "image": "python:3.11",
                "commands": ["pytest"],
                "requires": ["build"],
            },
        })
        spec = parse_workflow_spec(data)
        assert spec.jobs["test"].requires == ["build"]

    def test_job_with_if_condition(self):
        data = _minimal_spec({
            "build": {"image": "python:3.11", "commands": ["make build"]},
            "deploy": {
                "image": "python:3.11",
                "commands": ["deploy"],
                "requires": ["build"],
                "if": "${{ jobs.build.status == 'success' }}",
            },
        })
        spec = parse_workflow_spec(data)
        assert spec.jobs["deploy"].if_condition == "${{ jobs.build.status == 'success' }}"

    def test_on_complete_always(self):
        data = _minimal_spec({
            "notify": {
                "image": "alpine:latest",
                "commands": ["echo done"],
                "on_complete": "always",
            }
        })
        spec = parse_workflow_spec(data)
        assert spec.jobs["notify"].on_complete == "always"


class TestLoadWorkflowSpec:
    def test_load_from_yaml_file(self, tmp_path):
        data = _minimal_spec()
        yaml_path = os.path.join(str(tmp_path), "workflow.yaml")
        with open(yaml_path, "w") as f:
            yaml.dump(data, f)
        spec = load_workflow_spec(yaml_path)
        assert spec.name == "test-workflow"

    def test_load_nonexistent_file(self):
        with pytest.raises(FileNotFoundError):
            load_workflow_spec("/nonexistent/path.yaml")


class TestValidateWorkflow:
    def test_valid_linear_chain(self):
        data = _minimal_spec({
            "a": {"image": "alpine", "commands": ["echo a"]},
            "b": {"image": "alpine", "commands": ["echo b"], "requires": ["a"]},
            "c": {"image": "alpine", "commands": ["echo c"], "requires": ["b"]},
        })
        spec = parse_workflow_spec(data)
        # Should not raise
        validate_workflow(spec)

    def test_cycle_detection(self):
        data = {
            "name": "cyclic",
            "jobs": {
                "a": {"name": "a", "image": "alpine", "commands": ["echo"], "requires": ["b"]},
                "b": {"name": "b", "image": "alpine", "commands": ["echo"], "requires": ["a"]},
            },
        }
        spec = WorkflowSpec.model_validate(data)
        with pytest.raises(WorkflowValidationError, match="Circular dependency"):
            validate_workflow(spec)

    def test_missing_dependency_reference(self):
        data = {
            "name": "bad-ref",
            "jobs": {
                "a": {"name": "a", "image": "alpine", "commands": ["echo"], "requires": ["nonexistent"]},
            },
        }
        spec = WorkflowSpec.model_validate(data)
        with pytest.raises(WorkflowValidationError, match="unknown job 'nonexistent'"):
            validate_workflow(spec)

    def test_invalid_condition_syntax(self):
        data = {
            "name": "bad-cond",
            "jobs": {
                "a": {"name": "a", "image": "alpine", "commands": ["echo"],
                       "if_condition": "invalid expression"},
            },
        }
        spec = WorkflowSpec.model_validate(data)
        with pytest.raises(WorkflowValidationError, match="must be wrapped"):
            validate_workflow(spec)

    def test_invalid_condition_inner_syntax(self):
        data = {
            "name": "bad-inner",
            "jobs": {
                "a": {"name": "a", "image": "alpine", "commands": ["echo"],
                       "if_condition": "${{ eval(something) }}"},
            },
        }
        spec = WorkflowSpec.model_validate(data)
        with pytest.raises(WorkflowValidationError, match="unsupported syntax"):
            validate_workflow(spec)

    def test_valid_condition_passes(self):
        data = _minimal_spec({
            "build": {"image": "alpine", "commands": ["echo"]},
            "deploy": {
                "image": "alpine", "commands": ["echo"],
                "requires": ["build"],
                "if": "${{ jobs.build.status == 'success' }}",
            },
        })
        # Should not raise
        parse_workflow_spec(data)


class TestGetExecutionOrder:
    def test_linear_chain(self):
        data = _minimal_spec({
            "a": {"image": "alpine", "commands": ["echo a"]},
            "b": {"image": "alpine", "commands": ["echo b"], "requires": ["a"]},
            "c": {"image": "alpine", "commands": ["echo c"], "requires": ["b"]},
        })
        spec = parse_workflow_spec(data)
        levels = get_execution_order(spec)
        assert levels == [["a"], ["b"], ["c"]]

    def test_diamond_pattern(self):
        data = _minimal_spec({
            "a": {"image": "alpine", "commands": ["echo"]},
            "b": {"image": "alpine", "commands": ["echo"], "requires": ["a"]},
            "c": {"image": "alpine", "commands": ["echo"], "requires": ["a"]},
            "d": {"image": "alpine", "commands": ["echo"], "requires": ["b", "c"]},
        })
        spec = parse_workflow_spec(data)
        levels = get_execution_order(spec)
        assert levels[0] == ["a"]
        assert sorted(levels[1]) == ["b", "c"]
        assert levels[2] == ["d"]

    def test_fully_parallel(self):
        data = _minimal_spec({
            "a": {"image": "alpine", "commands": ["echo"]},
            "b": {"image": "alpine", "commands": ["echo"]},
            "c": {"image": "alpine", "commands": ["echo"]},
        })
        spec = parse_workflow_spec(data)
        levels = get_execution_order(spec)
        assert len(levels) == 1
        assert sorted(levels[0]) == ["a", "b", "c"]

    def test_single_job(self):
        spec = parse_workflow_spec(_minimal_spec())
        levels = get_execution_order(spec)
        assert levels == [["build"]]


class TestExpandMatrix:
    def test_basic_expansion(self):
        matrix = MatrixConfig(parameters={"python": ["3.9", "3.10"], "os": ["ubuntu", "alpine"]})
        result = expand_matrix(matrix)
        assert len(result) == 4
        assert {"os": "ubuntu", "python": "3.9"} in result
        assert {"os": "alpine", "python": "3.10"} in result

    def test_empty_parameters(self):
        matrix = MatrixConfig(parameters={})
        result = expand_matrix(matrix)
        assert result == [{}]

    def test_exclude_rule(self):
        matrix = MatrixConfig(
            parameters={"python": ["3.9", "3.10"], "os": ["ubuntu", "alpine"]},
            exclude=[{"python": "3.9", "os": "alpine"}],
        )
        result = expand_matrix(matrix)
        assert len(result) == 3
        assert {"python": "3.9", "os": "alpine"} not in result

    def test_include_rule(self):
        matrix = MatrixConfig(
            parameters={"python": ["3.9"]},
            include=[{"python": "3.12"}],
        )
        result = expand_matrix(matrix)
        assert len(result) == 2
        assert {"python": "3.9"} in result
        assert {"python": "3.12"} in result

    def test_single_parameter(self):
        matrix = MatrixConfig(parameters={"python": ["3.9", "3.10", "3.11"]})
        result = expand_matrix(matrix)
        assert len(result) == 3


class TestMatrixKey:
    def test_deterministic_key(self):
        assert matrix_key({"python": "3.9", "os": "ubuntu"}) == "os=ubuntu,python=3.9"

    def test_empty_params(self):
        assert matrix_key({}) == ""

    def test_single_param(self):
        assert matrix_key({"python": "3.11"}) == "python=3.11"


class TestConditionEvaluator:
    def test_job_status_equals_success(self):
        evaluator = ConditionEvaluator({"build": "success"}, {})
        assert evaluator.evaluate("${{ jobs.build.status == 'success' }}") is True

    def test_job_status_equals_failure(self):
        evaluator = ConditionEvaluator({"build": "failed"}, {})
        assert evaluator.evaluate("${{ jobs.build.status == 'success' }}") is False

    def test_job_status_not_equals(self):
        evaluator = ConditionEvaluator({"build": "success"}, {})
        assert evaluator.evaluate("${{ jobs.build.status != 'failed' }}") is True

    def test_env_variable_check(self):
        evaluator = ConditionEvaluator({}, {"DEPLOY_ENV": "production"})
        assert evaluator.evaluate("${{ env.DEPLOY_ENV == 'production' }}") is True
        assert evaluator.evaluate("${{ env.DEPLOY_ENV == 'staging' }}") is False

    def test_and_operator(self):
        evaluator = ConditionEvaluator(
            {"build": "success", "test": "success"}, {}
        )
        condition = "${{ jobs.build.status == 'success' and jobs.test.status == 'success' }}"
        assert evaluator.evaluate(condition) is True

    def test_or_operator(self):
        evaluator = ConditionEvaluator(
            {"build": "failed", "test": "success"}, {}
        )
        condition = "${{ jobs.build.status == 'success' or jobs.test.status == 'success' }}"
        assert evaluator.evaluate(condition) is True

    def test_and_operator_one_false(self):
        evaluator = ConditionEvaluator(
            {"build": "success", "test": "failed"}, {}
        )
        condition = "${{ jobs.build.status == 'success' and jobs.test.status == 'success' }}"
        assert evaluator.evaluate(condition) is False

    def test_malformed_condition_returns_true(self):
        evaluator = ConditionEvaluator({}, {})
        assert evaluator.evaluate("not a condition") is True

    def test_unknown_job_defaults_to_unknown(self):
        evaluator = ConditionEvaluator({}, {})
        assert evaluator.evaluate("${{ jobs.nonexistent.status == 'unknown' }}") is True

    def test_missing_env_defaults_to_empty(self):
        evaluator = ConditionEvaluator({}, {})
        assert evaluator.evaluate("${{ env.MISSING == '' }}") is True
