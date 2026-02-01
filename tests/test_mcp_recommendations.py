"""Tests for recommendation MCP tools."""

import json
from unittest.mock import patch, MagicMock

from orcaops.schemas import (
    Recommendation,
    RecommendationPriority,
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


class TestGetRecommendations:
    @patch("orcaops.mcp_server._recommendation_store")
    def test_list_recommendations(self, mock_store):
        from orcaops.mcp_server import orcaops_get_recommendations
        mock_store.return_value.list_recommendations.return_value = [_make_rec()]
        result = json.loads(orcaops_get_recommendations())
        assert result["success"] is True
        assert result["count"] == 1

    @patch("orcaops.mcp_server._recommendation_store")
    def test_list_empty(self, mock_store):
        from orcaops.mcp_server import orcaops_get_recommendations
        mock_store.return_value.list_recommendations.return_value = []
        result = json.loads(orcaops_get_recommendations())
        assert result["success"] is True
        assert result["count"] == 0


class TestGenerateRecommendations:
    @patch("orcaops.mcp_server._recommendation_store")
    @patch("orcaops.mcp_server._recommendation_engine")
    def test_generate(self, mock_engine, mock_store):
        from orcaops.mcp_server import orcaops_generate_recommendations
        mock_engine.return_value.generate_recommendations.return_value = [_make_rec()]
        result = json.loads(orcaops_generate_recommendations())
        assert result["success"] is True
        assert result["count"] == 1
