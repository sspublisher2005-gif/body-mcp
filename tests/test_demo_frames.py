"""Learning from a screen recording: frames in, steps out - without ffmpeg or Tesseract."""
import os

from body_mcp import demo


def _png(path: str, color=(10, 20, 30)) -> None:
    try:
        from PIL import Image
    except Exception:
        with open(path, "wb") as handle:
            handle.write(b"\x89PNG\r\n\x1a\n" + b"0" * 64)
        return
    Image.new("RGB", (40, 20), color).save(path)


def test_a_folder_of_frames_is_accepted_without_a_decoder(tmp_path, monkeypatch):
    """The tool used to suggest 'hand over the frames' without supporting it."""
    monkeypatch.setattr(demo, "_frame_source", lambda: ("", "no decoder"))
    for index in range(3):
        _png(str(tmp_path / f"frame_{index:04d}.png"))
    result = demo.extract_frames(str(tmp_path))
    assert result["ok"] is True, result
    assert len(result["frames"]) == 3
    assert result["tool"] == "handed-over images"
    assert result["frames"][0]["at_s"] == 0.0


def test_an_empty_folder_is_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(demo, "_frame_source", lambda: ("", "no decoder"))
    result = demo.extract_frames(str(tmp_path))
    assert result["ok"] is False
    assert "no images" in result["reason"]


def test_a_frame_can_be_read_by_a_local_vision_model_without_ocr(tmp_path, monkeypatch):
    """No Tesseract: the local vision model reads the frame instead."""
    from body_mcp import eyes, local_worker

    monkeypatch.setattr(eyes, "ocr_text", lambda png, language="eng", provider_name=None: {
        "ok": False, "reason": "no OCR engine is installed", "text": ""})
    monkeypatch.setattr(local_worker, "run", lambda task, text, image=None: {
        "ok": True, "text": "- a code editor\n- a red error banner", "model": "gemma3:270m"})
    frame = tmp_path / "frame.png"
    _png(str(frame))
    result = demo.read_frame_text(str(frame))
    assert result["ok"] is True, result
    assert "code editor" in result["text"]
    assert "gemma3:270m" in result["provider"]


def test_without_ocr_and_without_a_vision_model_it_is_blocked(tmp_path, monkeypatch):
    from body_mcp import eyes, local_worker

    monkeypatch.setattr(eyes, "ocr_text", lambda png, language="eng", provider_name=None: {
        "ok": False, "reason": "no OCR engine is installed", "text": ""})
    monkeypatch.setattr(local_worker, "run", lambda task, text, image=None: {
        "ok": False, "reason": "no local VISION model is installed", "local": False})
    frame = tmp_path / "frame.png"
    _png(str(frame))
    result = demo.read_frame_text(str(frame))
    assert result["ok"] is False
    assert "no OCR engine" in result["reason"]


def test_the_learn_pipeline_runs_on_a_folder_of_frames(tmp_path, monkeypatch):
    from body_mcp import eyes, local_worker

    monkeypatch.setattr(demo, "_frame_source", lambda: ("", "no decoder"))
    monkeypatch.setattr(eyes, "ocr_text", lambda png, language="eng", provider_name=None: {
        "ok": False, "reason": "no OCR engine is installed", "text": ""})
    captions = iter(["- a login form", "- a login form", "- the dashboard"])
    monkeypatch.setattr(local_worker, "run", lambda task, text, image=None: {
        "ok": True, "text": next(captions), "model": "gemma3:270m"})
    for index in range(3):
        _png(str(tmp_path / f"f{index}.png"))
    result = demo.learn(str(tmp_path), name="demo")
    assert result["success"] is True, result
    assert result["data"]["steps"], result
    assert result["data"]["tool"] == "handed-over images"
    assert os.path.isdir(str(tmp_path))
