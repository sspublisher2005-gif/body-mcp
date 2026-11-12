"""Checkpoint redaction and lifecycle — memory only, never secrets."""

from body_mcp import checkpoint


def _steps():
    return [
        {"type": "goto", "url": "https://x.test/page?token=supersecret123&q=agents"},
        {"type": "fill", "field_ref": "input_1", "text": "my password is hunter2"},
        {"type": "click", "target": "Search"},
    ]


def test_checkpoint_redacts_query_and_fill_text():
    cid = checkpoint.create("task_test", 0, _steps(),
                            "https://x.test/page?token=supersecret123",
                            reason="test", resume_condition="test")
    ck = checkpoint.get(cid)
    assert "supersecret123" not in ck["url"]
    assert "supersecret123" not in str(ck["remaining_steps"])
    assert ck["remaining_steps"][1]["text"] == "<redacted>"
    assert ck["remaining_steps"][0]["url"] == "https://x.test/page"
    checkpoint.clear(cid)
    assert checkpoint.get(cid) is None


def test_checkpoint_list_omits_step_payloads():
    cid = checkpoint.create("task_list", 0, _steps(),
                            "https://x.test/", reason="r", resume_condition="c")
    listed = checkpoint.list_checkpoints()
    entry = next(c for c in listed if c["checkpoint_id"] == cid)
    assert "remaining_steps" not in entry
    assert "supersecret" not in str(entry)
    checkpoint.clear(cid)


def test_checkpoint_eviction_capacity():
    ids = [checkpoint.create(f"task_{i}", 0, [{"type": "goto", "url": "https://x.test/"}],
                             "https://x.test/", reason="r", resume_condition="c")
           for i in range(30)]
    listed = checkpoint.list_checkpoints()
    assert len(listed) <= checkpoint.MAX_CHECKPOINTS
    remaining = {c["checkpoint_id"] for c in listed}
    assert ids[-1] in remaining
    checkpoint.clear_all()
