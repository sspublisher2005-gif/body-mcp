"""Real-component proofs for the capabilities the local machine cannot verify.

Each subcommand needs software that is installed ONLY on a disposable CI runner:
    ocr      Tesseract + pytesseract
    worker   Ollama + a pulled text model
    describe Ollama + a pulled VISION model
    video    ffmpeg + Tesseract (or a folder of frames)

Prints one PROOF line per claim. Exits non-zero if the claim is not proven.
Never installs anything itself - the CI workflow does that, on its own VM.
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))


def proof(name: str, ok: bool, detail: str) -> None:
    print(f"{'PROOF' if ok else 'FAIL'} {name}: {detail}", flush=True)
    if not ok:
        raise SystemExit(1)


def image_with_text(text: str = "BODY MCP OCR PROOF 12345") -> bytes:
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (640, 160), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 640, 160), outline="black", width=3)
    draw.text((20, 60), text, fill="black")
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


async def ocr() -> None:
    from body_mcp import eyes

    png = image_with_text()
    result = eyes.ocr_text(png)
    text = result.get("text", "")
    print(json.dumps(result, indent=2)[:800], flush=True)
    proof("ocr", result.get("ok", False) and "BODY MCP" in text.upper(),
          f"provider={result.get('provider')} text={text!r}")


async def worker() -> None:
    from body_mcp import local_worker

    status = local_worker.status()
    print(json.dumps(status, indent=2)[:800], flush=True)
    result = local_worker.run("summarise", "Body-MCP gives coding agents eyes, ears and hands. "
                                           "It is free and local-first. It never downloads a model.")
    print(json.dumps(result, indent=2)[:800], flush=True)
    proof("local-worker", result.get("ok", False) and result.get("local") is True,
          f"model={result.get('model')} output={result.get('text', '')[:120]!r}")


async def describe() -> None:
    from body_mcp import local_worker

    status = local_worker.status()
    print(json.dumps(status, indent=2)[:800], flush=True)
    image = base64.b64encode(image_with_text("ERROR 42 CHECK THE LOGS")).decode()
    result = local_worker.run("describe", "", image=image)
    print(json.dumps(result, indent=2)[:800], flush=True)
    proof("describe", result.get("ok", False) and bool(result.get("text", "").strip()),
          f"model={result.get('model')} caption={result.get('text', '')[:160]!r}")


async def video() -> None:
    from body_mcp import demo

    folder = os.path.join(ROOT, "reports", "validation", "ci_frames")
    os.makedirs(folder, exist_ok=True)
    for i in range(4):
        with open(os.path.join(folder, f"frame_{i:04d}.png"), "wb") as handle:
            handle.write(image_with_text(f"STEP {i} - STATE CHANGED"))
    result = demo.learn(folder, name="ci-demo", max_frames=4)
    print(json.dumps(result, indent=2)[:1200], flush=True)
    proof("video", result.get("success", False),
          f"frames={result.get('data', {}).get('frames')} steps={len(result.get('data', {}).get('steps', []))}")


COMMANDS = {"ocr": ocr, "worker": worker, "describe": describe, "video": video}


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in COMMANDS:
        print(f"usage: {os.path.basename(__file__)} <{'|'.join(COMMANDS)}>")
        return 2
    asyncio.run(COMMANDS[sys.argv[1]]())
    return 0


if __name__ == "__main__":
    sys.exit(main())
