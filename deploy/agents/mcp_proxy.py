"""Agent-side MCP transport; contains no simulator or verifier code."""

import json
import os
from typing import Any, cast

import httpx
from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, TextContent, Tool

server = MCPServer("envforge")
url = os.environ["ENVFORGE_SESSION_URL"]
headers = {"Authorization": f"Bearer {os.environ['ENVFORGE_SESSION_TOKEN']}"}


async def list_tools() -> list[Tool]:
    async with httpx.AsyncClient(trust_env=False, timeout=10) as client:
        response = await client.get(f"{url}/tools", headers=headers)
        response.raise_for_status()
        return [
            Tool(
                name=item["name"],
                description=f"{item['name']} in the EnvForge incident simulation",
                input_schema=item["parameters"],
            )
            for item in response.json()
        ]


async def call_tool(
    name: str, arguments: dict[str, Any], context=None
) -> CallToolResult:
    async with httpx.AsyncClient(trust_env=False, timeout=660) as client:
        response = await client.post(
            f"{url}/call", headers=headers, json={"name": name, "arguments": arguments}
        )
        if response.is_error:
            return CallToolResult(
                content=[
                    TextContent(
                        type="text",
                        text="EnvForge rejected the tool call; check the tool arguments or session status.",
                    )
                ],
                is_error=True,
            )
        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps(response.json()))]
        )


# Same public MCPServer forwarding interface used by the v1 Harbor toolset.
cast(Any, server).list_tools = list_tools
cast(Any, server).call_tool = call_tool

if __name__ == "__main__":
    server.run(transport="stdio")
