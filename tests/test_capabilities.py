"""body_capabilities: the auto-use manifest an agent reads first."""
import asyncio

from body_mcp import server


def test_capabilities_derives_from_body_status():
    caps = asyncio.run(server.body_capabilities())
    status = asyncio.run(server.body_status())
    assert caps["success"] is True
    data = caps["data"]
    assert data["identity"]
    assert len(data["work_loop"]) == 6
    assert "EYES" in data["work_loop"][0]
    assert "VERIFY" in data["work_loop"][3]
    assert data["use_instead_of_web_tools"]["why"]
    assert "eyes_see_browser" in data["use_instead_of_web_tools"]["tools"]
    assert data["available_here"] + data["blocked_here"]
    assert set(data["verification_states"]) >= {"CONFIRMED", "UNCONFIRMED", "BLOCKED"}
    assert "UNCONFIRMED is not done" in data["truth_rule"]
    # derived, never a second source of truth
    assert set(data["available_here"]).isdisjoint(data["blocked_here"])
    assert status["data"]["version"] == "0.4.0"


def test_capabilities_reports_the_truth_about_this_machine():
    data = asyncio.run(server.body_capabilities())["data"]
    available, blocked = data["available_here"], data["blocked_here"]
    # On this machine the browser and the image path work; OCR and the local
    # worker do not. The exact facts can change, but they must never all be
    # "available" (that would be a claim of everything working, which is false).
    assert blocked, "at least one capability must be reported as blocked"
    assert "browser" in available, "the managed browser is proven here"
    assert "local_worker" in blocked, "no local model is installed on this machine"
