"""Agent-side MCP transport; contains no simulator or verifier code."""

import asyncio
import json
import os
from typing import Any

import httpx
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

server = Server("envforge")
url = os.environ["ENVFORGE_SESSION_URL"]
headers = {"Authorization": f"Bearer {os.environ['ENVFORGE_SESSION_TOKEN']}"}


@server.list_tools()
async def list_tools() -> list[Tool]:
    async with httpx.AsyncClient(trust_env=False, timeout=10) as client:
        response = await client.get(f"{url}/tools", headers=headers)
        response.raise_for_status()
        definitions = response.json()
        # kubectl-ai's schema converter treats anyOf as an object. Advertise
        # optional scalar fields using their concrete type; omit instead of null.
        # The bridge remains authoritative for argument validation and defaults.
        for item in definitions:
            for prop in item["parameters"].get("properties", {}).values():
                variants = prop.get("anyOf", [])
                concrete = [v for v in variants if v.get("type") != "null"]
                if len(variants) == 2 and len(concrete) == 1:
                    prop.pop("anyOf")
                    prop.pop("default", None)
                    prop.update(concrete[0])
        return [
            Tool(
                name=item["name"],
                description=f"{item['name']} in the EnvForge incident simulation",
                inputSchema=item["parameters"],
            )
            for item in definitions
        ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    async with httpx.AsyncClient(trust_env=False, timeout=660) as client:
        response = await client.post(
            f"{url}/call", headers=headers, json={"name": name, "arguments": arguments}
        )
        if response.is_error:
            raise ValueError(
                "EnvForge rejected the tool call; check the tool arguments or session status."
            )
        return [TextContent(type="text", text=json.dumps(response.json()))]


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream, write_stream, server.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())
