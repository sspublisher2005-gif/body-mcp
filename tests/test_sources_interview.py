"""Research adapters + the interview: unit level, with the network stubbed."""
import asyncio

from body_mcp import interview, server, sources


def _stub(monkeypatch, payload, error=""):
    def fake(url, source, *args, **kwargs):
        if error:
            return None, error
        return payload, ""

    monkeypatch.setattr(sources, "_get_json", fake)


def test_hackernews_adapter_returns_evidence(monkeypatch):
    _stub(monkeypatch, {"hits": [{"objectID": "1", "title": "A story", "url": "https://x.test",
                                   "author": "someone", "created_at": "2026-01-01T00:00:00Z",
                                   "points": 42, "num_comments": 7, "story_text": "body"}]})
    result = sources.search("hackernews", "agents", limit=3)
    assert result["success"] is True
    item = result["items"][0]
    assert item["title"] == "A story"
    assert item["score"] == 42
    assert item["comments"] == 7
    assert item["retrieval_method"].startswith("public API")


def test_reddit_blocked_is_reported_not_hidden(monkeypatch):
    _stub(monkeypatch, None, error="HTTP 403 from reddit")
    result = sources.search("reddit", "agents", limit=3)
    assert result["success"] is False
    assert "403" in result["reason"]


def test_blocked_sources_have_no_substitute(monkeypatch):
    for name in ("x", "instagram", "private_groups"):
        result = sources.search(name, "agents")
        assert result["success"] is False
        assert result["reason"]
        assert result["items"] == []


def test_unknown_source_is_refused():
    result = sources.search("myspace", "agents")
    assert result["success"] is False
    assert "unknown source" in result["reason"]


def test_source_matrix_lists_what_is_readable_and_what_is_not():
    matrix = sources.matrix()
    readable = {entry["source"] for entry in matrix if entry["available"]}
    blocked = {entry["source"] for entry in matrix if not entry["available"]}
    assert {"hackernews", "reddit", "github_issues", "stackoverflow", "wikipedia",
            "youtube"} <= readable
    assert {"x", "instagram"} <= blocked
    for entry in matrix:
        assert entry["notes"]


def test_github_issues_adapter(monkeypatch):
    _stub(monkeypatch, {"items": [{"number": 12, "title": "Bug: crash",
                                   "html_url": "https://github.com/x/y/issues/12",
                                   "user": {"login": "dev"}, "created_at": "2026-02-02",
                                   "comments": 4, "body": "it crashes"}]})
    result = sources.search("github_issues", "crash", limit=2)
    assert result["success"] is True
    assert result["items"][0]["url"].endswith("/issues/12")


def test_interview_uses_the_standard_question_set():
    questions = interview.question_set()
    assert len(questions) >= 8
    blob = " ".join(questions).lower()
    for topic in ("budget", "category", "wrong", "lightweight", "must never", "machine"):
        assert topic in blob, topic


def test_interview_returns_answers(monkeypatch):
    async def fake_form(questions, ctx, title):
        return {questions[0]: "50 EUR/month"}

    monkeypatch.setattr(interview, "_ask_via_form", fake_form)

    async def run():
        return await interview.interview(["budget?", "hardware?"], ctx=object())

    result = asyncio.run(run())
    assert result["success"] is True
    assert result["data"]["answers"]["budget?"] == "50 EUR/month"


def test_interview_without_questions_is_refused():
    result = asyncio.run(interview.interview([]))
    assert result["success"] is False


def test_new_tools_are_exposed():
    async def names():
        tools = await server.mcp.list_tools()
        return [tool.name for tool in tools]

    listed = asyncio.run(names())
    for tool in ("research_sources", "research_source", "reflex_interview"):
        assert tool in listed, tool
