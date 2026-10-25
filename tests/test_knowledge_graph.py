"""
Unit tests for Jobdec Knowledge Graph & Graph-RAG Engine.
Verifies network traversal, referral warmth ranking, canonical entity resolution,
and grounded evidence extraction.
"""
import pytest
from brain.knowledge_graph import JobdecKnowledgeGraph, get_kg


@pytest.fixture(scope="module")
def kg():
    return get_kg()


def test_knowledge_graph_build(kg):
    assert kg.graph.number_of_nodes() > 50
    assert kg.graph.number_of_edges() > 50
    stats = kg.get_summary_stats()
    assert stats["total_nodes"] == kg.graph.number_of_nodes()
    assert stats["companies_count"] > 10
    assert stats["contacts_count"] > 10


def test_canonical_company_aliases(kg):
    assert kg.canonical_company("amex") == "American Express"
    assert kg.canonical_company("GS") == "Goldman Sachs"
    assert kg.canonical_company("jpm") == "JPMorgan Chase"
    assert kg.canonical_company("home depot") == "The Home Depot"
    assert kg.canonical_company("delta") == "Delta Air Lines"
    assert kg.canonical_company("RandomUnknownFirm") == "RandomUnknownFirm"


def test_find_referral_paths_warmth_ranking(kg):
    paths = kg.find_referral_paths("American Express")
    assert len(paths) > 0
    # Warmth scores should be sorted descending
    scores = [p["warmth_score"] for p in paths]
    assert scores == sorted(scores, reverse=True)
    # Check top path contains expected structure
    top = paths[0]
    assert "name" in top
    assert "role" in top
    assert "company" in top
    assert "warmth_score" in top
    assert "reasons" in top
    assert top["warmth_score"] >= 20


def test_graph_rag_evidence_extraction(kg):
    evidence = kg.graph_rag_evidence("automation workflow scheduling Python")
    assert len(evidence) > 0
    top = evidence[0]
    assert "score" in top
    assert top["score"] > 0
    text_or_role = top.get("text") or top.get("role")
    assert text_or_role is not None


def test_company_context_aggregation(kg):
    ctx = kg.get_company_context("American Express")
    assert ctx["company"] == "American Express"
    assert "referral_paths" in ctx
    assert "requisitions" in ctx
    assert "evidence" in ctx


def test_export_telemetry_d3_format(kg):
    d3_data = kg.export_telemetry_d3()
    assert "nodes" in d3_data
    assert "links" in d3_data
    assert "stats" in d3_data
    assert len(d3_data["nodes"]) == kg.graph.number_of_nodes()
    assert len(d3_data["links"]) == kg.graph.number_of_edges()
    for n in d3_data["nodes"][:5]:
        assert "id" in n
        assert "label" in n
        assert "type" in n


def test_ai_responder_referral_integration():
    import ai_responder
    ans = ai_responder.generate_response("Who referred you to this role?", company="American Express")
    assert ans != ""
    assert ans != "N/A"
    # For a company with no contacts, should cleanly fallback to N/A
    fallback_ans = ai_responder.generate_response("Who referred you to this role?", company="FakeUnknownCorpXYZ")
    assert fallback_ans == "N/A"
