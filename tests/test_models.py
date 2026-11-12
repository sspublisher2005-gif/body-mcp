"""The local-model catalogue: measured sizes, checksums, per-machine recommendations."""

from body_mcp import models


def test_catalogue_entries_are_complete_and_measured():
    catalogue = models.catalogue()
    assert len(catalogue) >= 5
    for entry in catalogue:
        assert entry["id"] and entry["name"]
        assert entry["bytes"] > 0
        assert len(entry["sha256"]) == 64
        assert entry["licence"]
        assert entry["ram_mb"] >= 500
        assert entry["download_url"].startswith("https://huggingface.co/")
        assert entry["file"] in entry["download_url"]


def test_the_smallest_worker_fits_the_500mb_budget():
    workers = [m for m in models.MODELS if m["role"] == "worker"]
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


def test_worker_role_excludes_the_reasoner_tier():
    ranked = models.recommend(free_ram_mb=8000, role="worker")
    assert all("Dolphin" not in item["name"] for item in ranked)


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
