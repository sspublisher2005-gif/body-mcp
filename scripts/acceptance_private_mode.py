"""Show the new private-mode tools working (or refusing honestly) on this machine."""
import asyncio
import sys

sys.path.insert(0, "src")
from body_mcp import privacy, server


async def main():
    print("=" * 72)
    print("1. body_local_models()  - what THIS machine can run")
    print("=" * 72)
    result = await server.body_local_models()
    print(result["message"])
    data = result["data"]
    print(f"   free RAM: {data['free_ram_mb']} MB")
    for item in data["recommended_for_this_machine"][:5]:
        flag = "FITS" if item["fits"] else "DOES NOT FIT"
        print(f"   {item['name']:<36} {item['size_mb']:>5} MB  ram~{item['ram_mb']:>5} MB  {flag}")
        print(f"      install: {item['install']}")
    worker = data["worker"]
    print(f"   worker available: {worker['available']}  "
          f"(ollama installed: {worker['ollama_installed']}, "
          f"ollama models: {len(worker['ollama_models'])})")

    print()
    print("=" * 72)
    print("2. body_local_worker() - the honest refusal (no model on this machine)")
    print("=" * 72)
    result = await server.body_local_worker(task="summarise", text="Page text that must not leave.")
    print(f"   success: {result['success']}")
    print(f"   message: {result['message']}")

    print()
    print("=" * 72)
    print("3. body_privacy_preflight() - the content policy")
    print("=" * 72)
    result = await server.body_privacy_preflight()
    policy = result["data"]["content_policy"]
    print(f"   browsing: {policy['browsing']}")
    print(f"   content can stay local: {policy['content_local_possible']}")
    for warning in result["data"]["warnings"]:
        print(f"   ! {warning}")

    print()
    print("=" * 72)
    print("4. privacy_vpn_connect() - denied by default (fail-closed)")
    print("=" * 72)
    result = await server.privacy_vpn_connect()
    print(f"   success: {result['success']}")
    print(f"   message: {result['message']}")

    print()
    print("=" * 72)
    print("5. privacy state reader (unit level)")
    print("=" * 72)
    for text in ("Proton VPN - Connected", "Disconnected", "Proton VPN"):
        print(f"   {text!r:<26} -> {privacy.vpn_state(text)}")


asyncio.run(main())
