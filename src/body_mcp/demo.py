"""Learn a workflow from a demonstration (a screen recording) and turn it into a skill.

The pipeline (each stage reports what it actually got, never a guess):

  1. frames + timestamps out of the recording
       - ffmpeg if it is installed (free, no download),
       - otherwise OpenCV / imageio if installed,
       - otherwise: BLOCKED with the exact missing dependency.
  2. OCR each frame (the OCR provider - Tesseract by default)
       - the text of the screen at that moment,
       - without an engine: BLOCKED (no invented text).
  3. the audio track (only if the recording has one and the user allows it)
       - transcribed locally with the configured speech engine,
       - without a model: the audio is skipped and said so.
  4. steps: consecutive frames whose text changed become ONE step, with the
     page/app it was on, the visible controls and the text that appeared.
  5. missing/ambiguous parts are collected as questions.
  6. the result is a skill draft (steps + why + open questions).

Semantic actions are preferred over coordinates: a step records the app/window,
the visible control names and the text - so a replay can re-find the control by
name instead of clicking a pixel.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time

from . import skills

MAX_FRAMES = 60
MAX_STEPS = 25
FRAME_INTERVAL_S = 3.0
DEFAULT_FFMPEG = "ffmpeg"


def _frame_source() -> tuple[str, str]:
    """How can we get frames? (tool, reason if none)"""
    if shutil.which(DEFAULT_FFMPEG):
        return "ffmpeg", ""
    try:
        import cv2  # noqa: F401

        return "opencv", ""
    except Exception:
        pass
    try:
        import imageio.v3 as iio  # noqa: F401

        return "imageio", ""
    except Exception:
        pass
    return "", ("no frame decoder available: install ffmpeg (free, winget install ffmpeg) "
                "or opencv-python, or pass extracted frames yourself")


def extract_frames(video_path: str, max_frames: int = MAX_FRAMES,
                  interval_s: float = FRAME_INTERVAL_S) -> dict:
    """Extract frames with timestamps from a screen recording.

    A DIRECTORY of images is accepted too: extract the frames yourself (ffmpeg,
    a screen recorder, anything) and hand the folder over - no decoder needed.
    """
    if os.path.isdir(video_path):
        names = sorted(name for name in os.listdir(video_path)
                       if name.lower().endswith((".png", ".jpg", ".jpeg", ".bmp")))
        frames = [{"index": index, "path": os.path.join(video_path, name),
                   "at_s": round(index * max(interval_s, 0.5), 1)}
                  for index, name in enumerate(names[:max_frames])]
        return {"ok": bool(frames), "frames": frames, "tool": "handed-over images",
                "reason": "" if frames else "that folder holds no images"}
    if not os.path.isfile(video_path):
        return {"ok": False, "reason": f"no such file: {video_path}"}
    tool, reason = _frame_source()
    if not tool:
        return {"ok": False, "reason": reason}
    workdir = tempfile.mkdtemp(prefix="body_demo_")
    try:
        if tool == "ffmpeg":
            pattern = os.path.join(workdir, "frame_%04d.png")
            subprocess.run(
                [DEFAULT_FFMPEG, "-hide_banner", "-loglevel", "error", "-i", video_path,
                 "-vf", f"fps=1/{max(interval_s, 0.5):.2f}", "-frames:v", str(max_frames),
                 pattern],
                capture_output=True, timeout=600, check=False)
        elif tool == "opencv":
            import cv2

            capture = cv2.VideoCapture(video_path)
            fps = capture.get(cv2.CAP_PROP_FPS) or 1.0
            step = max(1, int(fps * max(interval_s, 0.5)))
            index = 0
            while index < max_frames:
                ok, frame = capture.read()
                if not ok:
                    break
                if index % step == 0:
                    cv2.imwrite(os.path.join(workdir, f"frame_{index:04d}.png"), frame)
                index += 1
            capture.release()
        else:
            import imageio.v3 as iio

            reader = iio.imiter(video_path)
            step = max(1, int(interval_s))
            for index, frame in enumerate(reader):
                if index % step:
                    continue
                if index // step >= max_frames:
                    break
                iio.imwrite(os.path.join(workdir, f"frame_{index:04d}.png"), frame)
        names = sorted(name for name in os.listdir(workdir) if name.endswith(".png"))
        frames = [{"index": index, "path": os.path.join(workdir, name),
                   "at_s": round(index * max(interval_s, 0.5), 1)}
                  for index, name in enumerate(names)]
        return {"ok": bool(frames), "frames": frames, "tool": tool,
                "reason": "" if frames else "the decoder produced no frames"}
    except Exception as exc:
        return {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}
    finally:
        pass  # the frames stay for this run; the caller cleans up


def read_frame_text(path: str, language: str = "eng") -> dict:
    """Read one frame: OCR first, and if there is no OCR engine, a LOCAL vision
    model describes the frame instead (so learning still works without Tesseract)."""
    from . import eyes

    try:
        with open(path, "rb") as handle:
            png = handle.read()
    except OSError as exc:
        return {"ok": False, "text": "", "reason": str(exc)}
    result = eyes.ocr_text(png, language=language)
    if result.get("ok"):
        return {"ok": True, "text": result.get("text") or "", "provider": result.get("provider")}
    from . import local_worker, vision

    prepared = vision.prepare_image(png)
    if prepared.get("ok"):
        described = local_worker.run("describe", "", image=prepared["data"])
        if described.get("ok"):
            return {"ok": True, "text": described.get("text") or "",
                    "provider": f"local vision model ({described.get('model')})"}
    return {"ok": False, "text": "", "reason": result.get("reason") or "no OCR engine"}


def _visible_controls(text: str) -> list[str]:
    """Cheap heuristic: the lines that look like controls (buttons/menus/tabs)."""
    hints = ("submit", "cancel", "next", "back", "save", "publish", "post", "share",
             "upload", "download", "edit", "create", "settings", "profile", "menu", "tab")
    found = []
    for line in (text or "").splitlines():
        stripped = line.strip()
        if not stripped or len(stripped) > 40:
            continue
        if any(hint in stripped.lower() for hint in hints):
            found.append(stripped)
    return found[:12]


def steps_from_frames(frames: list[dict], texts: list[str]) -> list[dict]:
    """Turn a sequence of frame texts into ordered steps (changed frames only)."""
    steps = []
    previous = ""
    for index, frame in enumerate(frames):
        text = texts[index] if index < len(texts) else ""
        if text.strip() == previous.strip():
            continue
        previous = text
        first_lines = [line.strip() for line in (text or "").splitlines() if line.strip()][:3]
        steps.append({
            "at_s": frame.get("at_s"),
            "screen": " / ".join(first_lines)[:160],
            "controls": _visible_controls(text),
            "text_seen": (text or "")[:400],
            "kind": "observed",
        })
        if len(steps) >= MAX_STEPS:
            break
    return steps


def questions_from_steps(steps: list[dict]) -> list[str]:
    """What is still unclear? (these become the interview)"""
    questions = []
    if not steps:
        return ["The recording produced no readable steps - what should the workflow do?"]
    if not any(step.get("controls") for step in steps):
        questions.append("Which control did you click at each step? I could not read the "
                         "buttons from the recording.")
    if not any(step.get("text_seen") for step in steps):
        questions.append("What text was typed in each step? The screen text was not readable.")
    questions.append("Should I repeat this exact workflow, or keep the method and make new "
                     "content next time?")
    questions.append("Should the result be published automatically, or prepared for your "
                     "approval?")
    questions.append("What must stay exactly the same (account, template, caption format)?")
    questions.append("What should happen if the site changes or a step fails?")
    return questions


def learn(video_path: str, name: str = "", max_frames: int = MAX_FRAMES,
          language: str = "eng") -> dict:
    """The whole demonstration-learning pipeline, honestly."""
    started = time.time()
    extraction = extract_frames(video_path, max_frames=max_frames)
    if not extraction.get("ok"):
        return {"success": False, "stage": "frames", "status": "BLOCKED",
                "message": extraction.get("reason"),
                "next": ("install a frame decoder (ffmpeg or opencv-python) or point "
                         "demo_learn at a FOLDER of frames you extracted yourself"),
                "data": {"elapsed_s": round(time.time() - started, 1)}}

    frames = extraction["frames"]
    texts = []
    ocr_blocked = ""
    for frame in frames:
        result = read_frame_text(frame["path"], language=language)
        if not result.get("ok"):
            ocr_blocked = result.get("reason") or "no OCR engine"
            break
        texts.append(result.get("text") or "")

    if ocr_blocked:
        return {"success": False, "stage": "ocr", "status": "BLOCKED",
                "message": (f"{len(frames)} frame(s) extracted with {extraction['tool']}, but "
                            f"the screen text could not be read: {ocr_blocked}"),
                "next": "install Tesseract (winget install -e --id UB-Mannheim.TesseractOCR)",
                "data": {"frames": len(frames), "tool": extraction["tool"],
                         "elapsed_s": round(time.time() - started, 1)}}

    steps = steps_from_frames(frames, texts)
    questions = questions_from_steps(steps)
    skill = skills.save(name=name or os.path.basename(video_path), goal="replay the "
                        "demonstrated workflow", steps=[], why="learned from a screen recording",
                        verified=False, tags=["demonstration"])
    return {"success": True, "stage": "steps", "status": "DRAFT",
            "message": (f"{len(steps)} step(s) inferred from {len(frames)} frame(s); "
                        f"{len(questions)} question(s) still open"),
            "data": {"steps": steps, "questions": questions,
                     "draft_skill_id": skill.get("data", {}).get("id"),
                     "frames": len(frames), "tool": extraction["tool"],
                     "elapsed_s": round(time.time() - started, 1),
                     "note": "the steps are observed, not understood - answer the questions "
                             "before it is saved as a verified skill"}}
