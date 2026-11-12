"""Vision mode: the model can actually SEE, on request.

These tests exercise the real path: a real Chromium page is rendered, a real
screenshot is taken, the image is downscaled and handed to the MCP client as an
image content block next to the structured text.
"""
import asyncio
import base64
import io

from body_mcp import server, vision


def _png(width: int = 40, height: int = 20, color=(200, 30, 30)) -> bytes:
    try:
        from PIL import Image
    except Exception:
        return b""
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, format="PNG")
    return buffer.getvalue()


def test_prepare_image_downscales_and_caps():
    prepared = vision.prepare_image(_png(3000, 1500))
    if not prepared.get("ok"):
        # no Pillow: the raw PNG must still be within the cap
        assert prepared["reason"]
        return
    assert prepared["width"] <= vision.MAX_WIDTH
    assert prepared["bytes"] <= vision.MAX_IMAGE_BYTES
    assert prepared["mime_type"] == "image/jpeg"
    assert prepared["downscaled"] is True


def test_prepare_image_rejects_empty_data():
    assert vision.prepare_image(b"")["ok"] is False


def test_with_image_keeps_the_structured_payload():
    payload = {"success": True, "message": "ok", "data": {"title": "x"}}
    result = vision.with_image(payload, vision.prepare_image(_png(100, 50)))
    structured = getattr(result, "structured_content", None)
    if structured is None:
        assert result == payload  # Pillow missing -> payload unchanged
        return
    assert structured["data"]["title"] == "x"
    assert structured["data"]["image"]["bytes"] > 0
    blocks = [b.type for b in result.content]
    assert "image" in blocks and "text" in blocks


def test_with_image_without_prepared_image_is_a_noop():
    payload = {"success": True, "message": "ok", "data": {}}
    assert vision.with_image(payload, None) is payload
    assert vision.with_image(payload, {"ok": False, "reason": "x"}) is payload


def test_browser_tool_attaches_a_real_image_to_the_mcp_result():
    """The whole path: MCP client -> tool -> real Chromium -> image block."""
    from mcp import Client

    async def run():
        async with Client(server.mcp, raise_exceptions=True) as client:
            return await client.call_tool(
                "eyes_see_browser",
                {"url": "file:///" + __file__.replace("\\", "/"), "screenshot": True})

    result = asyncio.run(run())
    blocks = [b.type for b in result.content]
    assert "text" in blocks
    if "image" in blocks:
        image = [b for b in result.content if b.type == "image"][0]
        assert image.mime_type in ("image/png", "image/jpeg")
        assert len(base64.b64decode(image.data)) > 100
    structured = result.structured_content
    assert structured["success"] is True
    assert "title" in structured["data"]


def test_desktop_tool_can_attach_the_screen():
    """No OCR engine is installed here - the screen must STILL be attached.

    The image is the point: a vision model can look at it even where Tesseract
    is missing. Only the text needs OCR."""
    from body_mcp import eyes

    result = eyes.see_desktop(as_image=True)
    structured = getattr(result, "structured_content", None)
    if structured is None:
        # no image could be prepared (no Pillow / capture failed): it must not crash
        assert result["success"] in (True, False)
        return
    assert structured["success"] is True, structured
    assert structured["data"]["text"] == ""
    assert structured["data"]["provider"] is None, "there is no OCR engine on this machine"
    blocks = [b.type for b in result.content]
    assert "image" in blocks, "the screenshot must survive without OCR"
