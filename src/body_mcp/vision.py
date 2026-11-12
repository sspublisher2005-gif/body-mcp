"""Optional vision mode: hand the model actual pixels, on request.

Until now Body-MCP only ever returned text and structure - no image ever entered
the model's context. That is the right default (cheap, exact, small), but it means
the agent cannot look at a canvas, a photo, a video frame or a game.

`vision.prepare_image()` prepares one image for transport:
  - downscaled to a maximum width (so a 4K screen does not become a 5 MB blob),
  - compressed to JPEG (or kept as PNG when Pillow is not installed),
  - hard-capped in size, so one call can never flood the context.

The image is produced in memory, transported once, and never stored.
"""
from __future__ import annotations

import base64
import io

MAX_IMAGE_BYTES = 900_000      # binary bytes after compression (~1.2 MB base64)
MAX_WIDTH = 1280
MIN_QUALITY = 35
DEFAULT_QUALITY = 70


def _pillow():
    try:
        from PIL import Image  # noqa: PLC0415

        return Image
    except Exception:
        return None


def prepare_image(png_bytes: bytes, max_bytes: int = MAX_IMAGE_BYTES,
                  max_width: int = MAX_WIDTH) -> dict:
    """Downscale/compress a PNG for transport.

    Returns {data (base64), mime_type, bytes, width, height, downscaled, note}.
    """
    if not png_bytes:
        return {"ok": False, "reason": "no image data"}
    Image = _pillow()
    if Image is None:
        if len(png_bytes) <= max_bytes:
            return {"ok": True, "data": base64.b64encode(png_bytes).decode(),
                    "mime_type": "image/png", "bytes": len(png_bytes),
                    "width": None, "height": None, "downscaled": False,
                    "note": "PNG (install the [desktop] extra for downscaled JPEG)"}
        return {"ok": False,
                "reason": f"the image is {len(png_bytes)} bytes, over the {max_bytes} byte "
                          "cap - install the [desktop] extra (Pillow) for downscaling, or "
                          "capture a smaller region"}

    try:
        image = Image.open(io.BytesIO(png_bytes))
        image = image.convert("RGB")
    except Exception as exc:
        return {"ok": False, "reason": f"could not decode the image: {exc}"}

    width, height = image.size
    downscaled = False
    if width > max_width:
        ratio = max_width / float(width)
        image = image.resize((max_width, max(1, int(height * ratio))))
        downscaled = True

    quality = DEFAULT_QUALITY
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality, optimize=True)
    data = buffer.getvalue()
    while len(data) > max_bytes and quality > MIN_QUALITY:
        quality -= 15
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=quality, optimize=True)
        data = buffer.getvalue()

    if len(data) > max_bytes:
        # still too big: halve the width and try once more
        image = image.resize((max(1, image.size[0] // 2), max(1, image.size[1] // 2)))
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=MIN_QUALITY, optimize=True)
        data = buffer.getvalue()
        downscaled = True
        if len(data) > max_bytes:
            return {"ok": False,
                    "reason": f"the image is still {len(data)} bytes after downscaling - "
                              "capture a smaller region"}

    final_width, final_height = image.size
    return {"ok": True, "data": base64.b64encode(data).decode(), "mime_type": "image/jpeg",
            "bytes": len(data), "width": final_width, "height": final_height,
            "downscaled": downscaled,
            "note": f"downscaled to {final_width}x{final_height}, {len(data)} bytes JPEG"
                    if downscaled else f"{final_width}x{final_height}, {len(data)} bytes JPEG"}


def image_content(prepared: dict):
    """An MCP image content block for a prepared image (None when not usable)."""
    if not prepared.get("ok"):
        return None
    try:
        from mcp_types import ImageContent
    except Exception:
        try:
            from mcp.types import ImageContent
        except Exception:
            return None
    return ImageContent(type="image", data=prepared["data"], mime_type=prepared["mime_type"])


def with_image(payload: dict, prepared: dict | None):
    """Attach an image to a tool result, keeping the structured payload intact.

    Returns the CallToolResult the MCP server should send: the JSON text block (so
    clients without image support still get everything) plus the image block.
    """
    if not prepared or not prepared.get("ok"):
        return payload
    try:
        from mcp_types import CallToolResult, TextContent
    except Exception:
        from mcp.types import CallToolResult, TextContent
    import json

    block = image_content(prepared)
    if block is None:
        return payload
    data = dict(payload.get("data") or {})
    data["image"] = {"bytes": prepared["bytes"], "width": prepared["width"],
                     "height": prepared["height"], "mime_type": prepared["mime_type"],
                     "downscaled": prepared["downscaled"]}
    payload = {**payload, "data": data}
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(payload)),
                                  block],
                          structured_content=payload)
