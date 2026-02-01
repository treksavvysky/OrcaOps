import pytest
from pydantic import ValidationError
from orcaops.schemas import JobSpec, SandboxSpec, JobCommand


def _make_spec(**overrides):
    defaults = dict(
        job_id="test-job",
        sandbox=SandboxSpec(image="python:3.9-slim"),
        commands=[JobCommand(command="echo hello")],
    )
    defaults.update(overrides)
    return JobSpec(**defaults)


def test_valid_job_id():
    spec = _make_spec(job_id="my-job-123")
    assert spec.job_id == "my-job-123"


def test_valid_job_id_with_underscores():
    spec = _make_spec(job_id="test_job_42")
    assert spec.job_id == "test_job_42"


def test_job_id_rejects_shell_chars():
    with pytest.raises(ValidationError, match="job_id"):
        _make_spec(job_id="job; rm -rf /")


def test_job_id_rejects_spaces():
    with pytest.raises(ValidationError, match="job_id"):
        _make_spec(job_id="job with spaces")


def test_job_id_max_length():
    with pytest.raises(ValidationError, match="job_id"):
        _make_spec(job_id="a" * 129)


def test_job_id_at_max_length():
    spec = _make_spec(job_id="a" * 128)
    assert len(spec.job_id) == 128


def test_image_valid():
    spec = _make_spec(sandbox=SandboxSpec(image="python:3.9-slim"))
    assert spec.sandbox.image == "python:3.9-slim"


def test_image_valid_with_registry():
    spec = _make_spec(sandbox=SandboxSpec(image="ghcr.io/owner/repo:latest"))
    assert spec.sandbox.image == "ghcr.io/owner/repo:latest"


def test_image_valid_with_sha():
    spec = _make_spec(sandbox=SandboxSpec(image="python@sha256:abc123"))
    assert spec.sandbox.image == "python@sha256:abc123"


def test_image_rejects_shell_injection():
    with pytest.raises(ValidationError, match="image"):
        SandboxSpec(image="$(evil)")


def test_image_rejects_empty():
    with pytest.raises(ValidationError, match="image"):
        SandboxSpec(image=" ")


def test_image_max_length():
    with pytest.raises(ValidationError, match="image"):
        SandboxSpec(image="a" * 257)


def test_ttl_valid():
    spec = _make_spec(ttl_seconds=3600)
    assert spec.ttl_seconds == 3600


def test_ttl_minimum():
    spec = _make_spec(ttl_seconds=10)
    assert spec.ttl_seconds == 10


def test_ttl_too_low():
    with pytest.raises(ValidationError, match="ttl_seconds"):
        _make_spec(ttl_seconds=5)


def test_ttl_too_high():
    with pytest.raises(ValidationError, match="ttl_seconds"):
        _make_spec(ttl_seconds=86401)


def test_artifact_allows_absolute_paths():
    spec = _make_spec(artifacts=["/app/output.txt"])
    assert spec.artifacts == ["/app/output.txt"]


def test_artifact_allows_globs():
    spec = _make_spec(artifacts=["/app/*.txt", "/data/report-?.csv"])
    assert len(spec.artifacts) == 2


def test_artifact_rejects_semicolon():
    with pytest.raises(ValidationError, match="artifact"):
        _make_spec(artifacts=["/tmp/foo; rm -rf /"])


def test_artifact_rejects_pipe():
    with pytest.raises(ValidationError, match="artifact"):
        _make_spec(artifacts=["/tmp/foo | cat /etc/passwd"])


def test_artifact_rejects_backtick():
    with pytest.raises(ValidationError, match="artifact"):
        _make_spec(artifacts=["/tmp/`whoami`"])


def test_artifact_rejects_dollar():
    with pytest.raises(ValidationError, match="artifact"):
        _make_spec(artifacts=["/tmp/$HOME/file"])
