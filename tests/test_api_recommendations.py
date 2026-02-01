"""Tests for recommendation API endpoints."""

from unittest.mock import patch, MagicMock

from fastapi.testclient import TestClient

from orcaops.schemas import (
    Recommendation,
    RecommendationPriority,
    RecommendationStatus,
    RecommendationType,
)


def _make_rec(rec_id="rec_test1"):
    return Recommendation(
        recommendation_id=rec_id,
        rec_type=RecommendationType.PERFORMANCE,
        priority=RecommendationPriority.MEDIUM,
        title="Test rec",
        description="Test description",
        impact="Test impact",
        action="Test action",
    )


@patch("orcaops.api.recommendation_store")
@patch("orcaops.api.docker_manager")
def test_list_recommendations(mock_dm, mock_store):
    from main import app
    client = TestClient(app)
    mock_store.list_recommendations.return_value = [_make_rec()]
    resp = client.get("/orcaops/recommendations")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1


@patch("orcaops.api.recommendation_engine")
@patch("orcaops.api.recommendation_store")
@patch("orcaops.api.docker_manager")
def test_generate_recommendations(mock_dm, mock_store, mock_engine):
    from main import app
    client = TestClient(app)
    mock_engine.generate_recommendations.return_value = [_make_rec()]
    resp = client.post("/orcaops/recommendations/generate")
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1


@patch("orcaops.api.recommendation_store")
@patch("orcaops.api.docker_manager")
def test_dismiss_recommendation(mock_dm, mock_store):
    from main import app
    client = TestClient(app)
    mock_store.dismiss.return_value = True
    resp = client.post("/orcaops/recommendations/rec_test1/dismiss")
    assert resp.status_code == 200


@patch("orcaops.api.recommendation_store")
@patch("orcaops.api.docker_manager")
def test_dismiss_not_found(mock_dm, mock_store):
    from main import app
    client = TestClient(app)
    mock_store.dismiss.return_value = False
    resp = client.post("/orcaops/recommendations/nonexistent/dismiss")
    assert resp.status_code == 404


@patch("orcaops.api.recommendation_store")
@patch("orcaops.api.docker_manager")
def test_apply_recommendation(mock_dm, mock_store):
    from main import app
    client = TestClient(app)
    mock_store.mark_applied.return_value = True
    resp = client.post("/orcaops/recommendations/rec_test1/apply")
    assert resp.status_code == 200
