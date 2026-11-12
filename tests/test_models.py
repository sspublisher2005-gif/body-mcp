"""The local-model catalogue: measured sizes, checksums, per-machine recommendations."""

from body_mcp import models


def test_catalogue_entries_are_complete_and_measured():
    catalogue = models.catalogue()
    assert len(catalogue) >= 8
    for entry in catalogue:
        assert entry["id"] and entry["name"]
        assert entry["bytes"] > 0
        assert len(entry["sha256"]) == 64
        assert entry["licence"]
        assert entry["ram_mb"] >= 500
        assert entry["install"], "every model says how to get it"
        assert entry["roles"]
        if entry["runtime"] == "ollama":
            assert entry["install"] == f"ollama pull {entry['tag']}"
            assert entry["download_url"] is None
        else:
            assert entry["download_url"].startswith("https://huggingface.co/")
            assert entry["file"] in entry["download_url"]


def test_both_runtimes_are_covered():
    runtimes = {entry["runtime"] for entry in models.catalogue()}
    assert runtimes == {"ollama", "llama.cpp"}


def test_the_size_is_the_whole_download_projector_included():
    vl = models.find("qwen3-vl-2b-q8")
    assert vl is not None
    files = models.files(vl)
    assert len(files) == 2, "the vision projector is a second file"
    assert models.total_bytes(vl) == sum(entry["bytes"] for entry in files)
    assert all(len(entry["sha256"]) == 64 for entry in files)


def test_the_smallest_worker_fits_the_500mb_budget():
    workers = [m for m in models.MODELS if "worker" in m["roles"]]
    smallest = min(workers, key=lambda m: m["bytes"])
    assert smallest["bytes"] <= 500 * 1024 * 1024, smallest["name"]


def test_recommendation_never_suggests_something_that_does_not_fit():
    ranked = models.recommend(free_ram_mb=450, role="worker")
    assert ranked, "there must be a candidate"
    best = ranked[0]
    assert best["fits"] is False, "nothing fits 450 MB - the report must say so"
    assert any("short" in reason for reason in best["reasons"])
    # with enough RAM the top pick must fit
    roomy = models.recommend(free_ram_mb=8000, role="worker")
    assert roomy[0]["fits"] is True


def test_recommendation_marks_what_does_not_fit():
    ranked = models.recommend(free_ram_mb=600, role="worker")
    reasons = " ".join(r for item in ranked for r in item["reasons"])
    assert "RAM" in reasons


def test_uncensored_preference_only_returns_uncensored_models():
    ranked = models.recommend(free_ram_mb=6000, role="reasoner", uncensored=True)
    assert ranked
    assert all(item["name"].lower().startswith("dolphin") for item in ranked)


def test_the_uncensored_floor_is_above_one_gigabyte():
    """Nobody ships a notable uncensored model under 1 GB - the catalogue must not lie."""
    uncensored = [m for m in models.MODELS if m["uncensored"]]
    assert uncensored
    assert min(m["bytes"] for m in uncensored) > 1024 * 1024 * 1024


def test_worker_role_excludes_the_reasoner_tier():
    ranked = models.recommend(free_ram_mb=8000, role="worker")
    assert all("Dolphin" not in item["name"] for item in ranked)


def test_the_one_model_pick_has_vision_and_tools():
    picks = [m for m in models.MODELS if m["vision"] and m["tools"]]
    assert picks, "there must be a model that sees and calls tools"
    assert any("reasoner" in m["roles"] for m in picks)


def test_verify_detects_a_wrong_file(tmp_path):
    file = tmp_path / "model.gguf"
    file.write_bytes(b"not a model")
    result = models.verify(str(file), sha256="0" * 64, expected_bytes=10)
    assert result["ok"] is False
    assert "mismatch" in result["reason"]


def test_verify_accepts_the_right_bytes_and_hash(tmp_path):
    import hashlib

    file = tmp_path / "model.gguf"
    file.write_bytes(b"GGUF")
    digest = hashlib.sha256(b"GGUF").hexdigest()
    result = models.verify(str(file), sha256=digest, expected_bytes=4)
    assert result["ok"] is True
    assert result["verified"] is True


def test_configured_model_is_reported(monkeypatch):
    monkeypatch.delenv("BODY_MCP_LOCAL_MODEL", raising=False)
    assert models.configured_model()["configured"] is False
    monkeypatch.setenv("BODY_MCP_LOCAL_MODEL", "/does/not/exist.gguf")
    info = models.configured_model()
    assert info["configured"] is True
    assert info["exists"] is False
