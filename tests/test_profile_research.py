"""New subsystems: system profile, model registry, research evidence collection."""
import asyncio
import os

from body_mcp import registry, server, sysprofile


def _fixture_url(name: str) -> str:
    path = os.path.join(os.path.dirname(__file__), "fixtures", name)
    return "file:///" + os.path.abspath(path).replace("\\", "/")


def test_system_profile_reports_real_facts():
    profile = sysprofile.collect(refresh=True)
    assert profile["platform"]["system"]
    assert profile["cpu"]["logical_cores"] >= 1
    assert profile["python"]["version"]
    assert "gpu" in profile
    assert profile["gpu"]["available"] in (True, False)
    # the profile is cached locally and non-sensitive
    assert os.path.exists(sysprofile.cache_path())
    assert "available_mb" in profile["memory"]


def test_system_profile_summary_is_compact():
    summary = sysprofile.summary()
    assert "platform" in summary and "optional_modules" in summary


def test_model_registry_lists_installed_backends():
    items = registry.listing()
    names = {i["name"] for i in items}
    assert {"opencode", "claude", "codex", "faster-whisper"} <= names
    for item in items:
        assert "license" in item and "privacy" in item
        assert item["installed"] in (True, False)


def test_recommend_is_a_dry_run():
    result = registry.recommend({"needs": ["tools"], "offline_only": False})
    assert result["dry_run"] is True
    # The registry ranks what is INSTALLED. On a clean CI machine no agent CLI
    # exists, so an empty list is the honest answer - never a fabricated pick.
    if result["ranked"]:
        assert result["recommended"] in {r["name"] for r in result["ranked"]}
    else:
        assert result["recommended"] in (None, ""), result
        assert result.get("installed") is False, result


def test_recommend_prefers_offline_capable_backends():
    offline = registry.recommend({"needs": ["audio"], "offline_only": True})
    ranked = {r["name"]: r["score"] for r in offline["ranked"]}
    if "faster-whisper" in ranked:
        assert ranked["faster-whisper"] > 0


def test_body_profile_and_models_tools():
    profile = asyncio.run(server.body_profile(refresh=True))
    assert profile["success"] is True
    models = asyncio.run(server.body_models())
    assert models["success"] is True and models["data"]["backends"]
    rec = asyncio.run(server.body_recommend(needs=["tools"]))
    assert rec["success"] is True and rec["data"]["dry_run"] is True


def test_research_collect_builds_evidence_records():
    result = asyncio.run(server.research_collect([_fixture_url("test_page.html")]))
    assert result["success"] is True
    item = result["data"]["items"][0]
    assert item["status"] == "COLLECTED"
    assert item["title"]
    assert item["collected_at"] > 0
    assert item["retrieval_method"]
    assert item["content_hash"]
    assert item["verification"] in ("CONFIRMED", "UNCONFIRMED")


def test_research_deduplicates_identical_sources():
    url = _fixture_url("test_page.html")
    result = asyncio.run(server.research_collect([url, url]))
    assert result["data"]["duplicates"] >= 1
    assert result["data"]["collected"] == 1


def test_research_reports_blocked_sources_without_bypassing():
    result = asyncio.run(server.research_collect([_fixture_url("restricted_page.html")]))
    assert result["success"] is False
    assert result["data"]["status"] == "BLOCKED"
    assert result["data"]["blocked"] >= 1
    assert result["data"]["blocked_sources"][0]["limitation"]


def test_research_bounds_the_number_of_items():
    urls = [_fixture_url("test_page.html")] * 8
    result = asyncio.run(server.research_collect(urls, max_items=2))
    assert result["data"]["collected"] <= 2
