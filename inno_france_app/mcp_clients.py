from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json
import os
from typing import Any, Optional

from mcp.client.session import ClientSession
from mcp.client.sse import sse_client
from mcp.client.stdio import StdioServerParameters, stdio_client


@dataclass(frozen=True)
class MCPServerConfig:
    name: str
    transport: str
    command: Optional[str] = None
    args: Optional[list[str]] = None
    cwd: Optional[Path] = None
    url: Optional[str] = None
    headers: Optional[dict[str, Any]] = None
    env: Optional[dict[str, str]] = None


class MCPToolClient:
    def __init__(self, config: MCPServerConfig) -> None:
        self.config = config

    async def call_tool(self, tool_name: str, tool_args: dict[str, Any]) -> dict[str, Any]:
        transport = (self.config.transport or "stdio").lower()
        if transport == "stdio":
            if not self.config.command or not self.config.cwd:
                raise ValueError(f"Invalid stdio config for {self.config.name}")
            params = _build_stdio_params(
                command=self.config.command,
                args=self.config.args or [],
                cwd=str(self.config.cwd),
                env=self.config.env,
            )
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(tool_name, tool_args)
                    return _coerce_result(result, tool_name, self.config.name)

        if transport == "sse":
            if not self.config.url:
                raise ValueError(f"Missing SSE url for {self.config.name}")
            async with sse_client(
                self.config.url,
                headers=self.config.headers,
            ) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(tool_name, tool_args)
                    return _coerce_result(result, tool_name, self.config.name)

        raise ValueError(f"Unsupported MCP transport: {transport}")


def _build_stdio_params(
    command: str,
    args: list[str],
    cwd: str,
    env: Optional[dict[str, str]],
):
    merged_env = dict(os.environ)
    if env:
        merged_env.update(env)
    try:
        return StdioServerParameters(
            command=command,
            args=args,
            cwd=cwd,
            env=merged_env,
        )
    except TypeError:
        return StdioServerParameters(
            command=command,
            args=args,
            cwd=cwd,
        )


def _coerce_result(result: Any, tool_name: str, server_name: str) -> dict[str, Any]:
    if isinstance(result, dict):
        return result

    content = getattr(result, "content", None)
    if isinstance(content, list):
        for item in content:
            if isinstance(item, dict) and "json" in item:
                payload = item.get("json")
                if isinstance(payload, dict):
                    return payload
            payload = getattr(item, "json", None)
            if isinstance(payload, dict):
                return payload
            text_payload = getattr(item, "text", None)
            if isinstance(text_payload, str):
                parsed = _try_parse_json(text_payload)
                if isinstance(parsed, dict):
                    return parsed

    structured = getattr(result, "structured_content", None)
    if isinstance(structured, dict):
        return structured
    if isinstance(structured, str):
        parsed = _try_parse_json(structured)
        if isinstance(parsed, dict):
            return parsed

    raise RuntimeError(
        f"Unsupported MCP response from {server_name}.{tool_name}: {type(result)}"
    )


def _try_parse_json(value: str) -> Optional[dict[str, Any]]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict):
        return parsed
    return None
