#!/usr/bin/env python3
"""Run basic security probes against a running PyWire server."""
import argparse
import asyncio
import json
from typing import Any, Dict, Optional, Tuple

import httpx
import msgpack
import websockets


def pack_msg(data: Dict[str, Any]) -> bytes:
    return msgpack.packb(data, use_bin_type=True)


def unpack_msg(data: bytes) -> Dict[str, Any]:
    return msgpack.unpackb(data, raw=False)


def create_http_session(client: httpx.Client, path: str = "/") -> Optional[str]:
    payload = pack_msg({"path": path})
    resp = client.post(
        "/_pywire/session",
        content=payload,
        headers={"Content-Type": "application/x-msgpack", "Accept": "application/x-msgpack"},
    )
    if resp.status_code != 200:
        return None
    data = unpack_msg(resp.content)
    return data.get("sessionId")


def http_event(
    client: httpx.Client,
    handler: str,
    data: Dict[str, Any],
    session_id: Optional[str],
) -> Tuple[int, Optional[Dict[str, Any]]]:
    headers = {
        "Content-Type": "application/x-msgpack",
        "Accept": "application/x-msgpack",
    }
    if session_id:
        headers["X-PyWire-Session"] = session_id
    payload = pack_msg({"handler": handler, "data": data})
    resp = client.post("/_pywire/event", content=payload, headers=headers)
    if resp.status_code != 200:
        return resp.status_code, None
    return resp.status_code, unpack_msg(resp.content)


def extract_html(payload: Optional[Dict[str, Any]]) -> str:
    if not payload:
        return ""
    html = payload.get("html")
    if isinstance(html, str):
        return html
    return ""


def run_http_tests(base_url: str, insecure: bool) -> Dict[str, Any]:
    results: Dict[str, Any] = {"http": {}}
    client = httpx.Client(base_url=base_url, timeout=10, verify=not insecure)

    session_id = create_http_session(client)
    results["http"]["session_created"] = bool(session_id)
    if not session_id:
        return results

    xss_payload = '<img src="x" onerror="window.__xss=1">'
    status, payload = http_event(
        client,
        "set_user_input",
        {"value": xss_payload},
        session_id,
    )
    html = extract_html(payload)
    results["http"]["xss_text_status"] = status
    results["http"]["xss_text_reflected"] = xss_payload in html

    status, payload = http_event(client, "store_value", {}, session_id)
    html = extract_html(payload)
    results["http"]["xss_stored_status"] = status
    results["http"]["xss_stored_reflected"] = xss_payload in html

    link_payload = "javascript:alert(1)"
    status, payload = http_event(
        client,
        "set_link_input",
        {"value": link_payload},
        session_id,
    )
    html = extract_html(payload)
    results["http"]["attr_injection_status"] = status
    results["http"]["attr_injection_reflected"] = (
        f'href="{link_payload}"' in html
    )

    status, payload = http_event(client, "secret_action", {}, session_id)
    html = extract_html(payload)
    results["http"]["handler_abuse_status"] = status
    results["http"]["handler_abuse_unlocked"] = "unlocked" in html

    status, _ = http_event(client, "secret_action", {}, None)
    results["http"]["missing_session_status"] = status

    debug_resp = client.get("/_pywire/source", params={"path": "/etc/hosts"})
    results["http"]["debug_source_status"] = debug_resp.status_code

    client.close()
    return results


async def run_ws_tests(base_url: str, insecure: bool) -> Dict[str, Any]:
    results: Dict[str, Any] = {"ws": {}}
    ws_url = base_url.replace("http://", "ws://").replace("https://", "wss://")
    ws_url = f"{ws_url}/_pywire/ws"

    try:
        ssl_ctx = None
        if insecure and ws_url.startswith("wss://"):
            import ssl

            ssl_ctx = ssl._create_unverified_context()

        async with websockets.connect(ws_url, ssl=ssl_ctx) as ws:
            payload = pack_msg(
                {
                    "type": "event",
                    "handler": "secret_action",
                    "path": "/",
                    "data": {},
                }
            )
            await ws.send(payload)
            raw = await ws.recv()
            if not isinstance(raw, (bytes, bytearray)):
                results["ws"]["handler_abuse_unlocked"] = False
                return results
            msg = unpack_msg(raw)
            html = msg.get("html", "")
            results["ws"]["handler_abuse_unlocked"] = "unlocked" in html
    except Exception as exc:
        results["ws"]["error"] = str(exc)
        return results

    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--insecure", action="store_true")
    args = parser.parse_args()

    http_results = run_http_tests(args.base_url, args.insecure)
    ws_results = asyncio.run(run_ws_tests(args.base_url, args.insecure))

    output = {
        "base_url": args.base_url,
        "results": {**http_results, **ws_results},
    }
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
