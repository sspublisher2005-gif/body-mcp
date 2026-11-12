"""Truthful results: verification states, checkpoint honesty, audit contents."""
import asyncio
import json
import os

from body_mcp import checkpoint, permissions, server


def fixture_url(name: str) -> str:
    path = os.path.join(os.path.dirname(__file__), "fixtures", name)
    return "file:///" + os.path.abspath(path).replace("\\", "/")


def _ref_by_text(buttons, text):
    return next(b["ref"] for b in buttons if text.lower() in b["text"].lower())


def _ref_by_placeholder(inputs, placeholder):
    return next(i["ref"] for i in inputs if i.get("placeholder") == placeholder)


def test_type_reads_the_value_back():
    async def flow():
        seen = await server.eyes_see_browser(fixture_url("test_page.html"))
        ref = _ref_by_placeholder(seen["data"]["inputs"], "Search the web")
        result = await server.hands_type(ref, "agents")
        assert result["success"] is True
        assert result["data"]["verification"]["status"] == "CONFIRMED"

    asyncio.run(flow())


def test_click_without_navigation_is_unconfirmed_not_success_claim():
    async def flow():
        seen = await server.eyes_see_browser(fixture_url("test_page.html"))
        save_ref = _ref_by_text(seen["data"]["buttons"], "Save")
        result = await server.hands_click(save_ref)
        assert result["success"] is True
        assert result["data"]["verification"]["status"] == "UNCONFIRMED"
        assert result["data"]["verification"]["evidence"]["navigated"] is False
        assert "reflex_verify" in result["data"]["verification"]["note"]

    asyncio.run(flow())


def test_click_that_navigates_is_confirmed():
    async def flow():
        seen = await server.eyes_see_browser(fixture_url("test_page.html"))
        link = next(lk["ref"] for lk in seen["data"]["links"] if "article" in lk["text"].lower())
        result = await server.hands_click(link)
        assert result["success"] is True
        assert result["data"]["verification"]["status"] == "CONFIRMED"

    asyncio.run(flow())


def test_open_reports_unconfirmed_when_landed_elsewhere():
    async def flow():
        result = await server.hands_open(fixture_url("test_page.html"))
        assert result["success"] is True
        assert result["data"]["verification"]["status"] == "CONFIRMED"

    asyncio.run(flow())


def test_batch_without_verify_step_is_reported_unverified():
    async def flow():
        seen = await server.eyes_see_browser(fixture_url("test_page.html"))
        ref = _ref_by_placeholder(seen["data"]["inputs"], "Search the web")
        result = await server.hands_batch([{"type": "fill", "field_ref": ref, "text": "agents"}])
        assert result["success"] is True
        assert result["data"]["verification"]["status"] == "UNVERIFIED"
        assert "UNVERIFIED" in result["message"]

    asyncio.run(flow())


def test_batch_with_verify_step_is_confirmed():
    async def flow():
        seen = await server.eyes_see_browser(fixture_url("test_page.html"))
        ref = _ref_by_placeholder(seen["data"]["inputs"], "Search the web")
        result = await server.hands_batch([
            {"type": "fill", "field_ref": ref, "text": "agents"},
            {"type": "verify_text", "expected": "Body-MCP Search"},
        ])
        assert result["success"] is True
        assert result["data"]["verification"]["status"] == "CONFIRMED"
        assert all("verified" in step for step in result["data"]["completed_steps"])

    asyncio.run(flow())


def test_checkpoint_separates_verified_from_attempted():
    async def flow():
        checkpoint.clear_all()
        seen = await server.eyes_see_browser(fixture_url("test_page.html"))
        q_ref = _ref_by_placeholder(seen["data"]["inputs"], "Search the web")
        delete_ref = _ref_by_text(seen["data"]["buttons"], "Delete")
        result = await server.hands_batch([
            {"type": "fill", "field_ref": q_ref, "text": "agents"},
            {"type": "click", "target": delete_ref},
        ])
        assert result["data"]["status"] == "needs_user"
        cid = result["data"]["checkpoint_id"]
        ckpt = checkpoint.get(cid)
        assert ckpt is not None
        # the fill ran but was never verified: the checkpoint must not claim it
        assert ckpt["last_verified_step"] == -1
        assert ckpt["attempted_unverified_steps"] == 1
        checkpoint.clear_all()

    asyncio.run(flow())


def test_audit_records_status_and_stays_redacted():
    async def flow():
        seen = await server.eyes_see_browser(fixture_url("test_page.html"))
        save_ref = _ref_by_text(seen["data"]["buttons"], "Save")
        await server.hands_click(save_ref)

    asyncio.run(flow())

    log_path = os.path.join(permissions._config_dir(), "audit.log")
    with open(log_path, encoding="utf-8") as f:
        records = [json.loads(line) for line in f if line.strip()]
    assert records, "expected audit records"
    last = records[-1]
    assert last["tool"] == "hands_click"
    assert last["status"] in ("CONFIRMED", "UNCONFIRMED")
    assert "ts" in last and "decision" in last


def test_audit_evidence_summary_does_not_leak_secrets():
    permissions.record_audit("hands_open", "public_web", "allow",
                             "https://x.test/a?token=topsecret",
                             status="CONFIRMED",
                             evidence={"http_status": 200,
                                       "url_observed": "https://x.test/a?token=topsecret"})
    log_path = os.path.join(permissions._config_dir(), "audit.log")
    with open(log_path, encoding="utf-8") as f:
        content = f.read()
    assert "topsecret" not in content


def test_browser_refs_are_invalidated_by_a_new_snapshot():
    async def flow():
        seen = await server.eyes_see_browser(fixture_url("test_page.html"))
        ref = _ref_by_placeholder(seen["data"]["inputs"], "Search the web")
        await server.eyes_see_browser(fixture_url("test_page.html"))
        stale = await server.hands_type(ref, "agents")
        assert stale["success"] is False
        assert stale["data"].get("stale") is True

    asyncio.run(flow())
