from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .mcp_clients import MCPServerConfig
from .settings import AppSettings, load_settings


@dataclass(frozen=True)
class AppConfig:
    settings: AppSettings
    output_dir: Path
    runs_dir: Path
    services: dict[str, MCPServerConfig]


def load_app_config(config_path: Optional[Path] = None) -> AppConfig:
    settings = load_settings()
    default_config_path = settings.project_root / "InnoFranceApp" / "config.json"
    final_path = (config_path or default_config_path).expanduser().resolve()

    default_services = _default_services(settings)
    output_dir = settings.output_dir
    runs_dir = settings.runs_dir

    if final_path.exists():
        data = _read_json(final_path)
        output_dir = _resolve_path(data.get("output_dir"), settings, fallback=output_dir)
        runs_dir = _resolve_path(data.get("runs_dir"), settings, fallback=runs_dir)
        service_overrides = data.get("services", {})
        services = _merge_services(default_services, service_overrides, settings)
    else:
        services = default_services

    return AppConfig(
        settings=settings,
        output_dir=output_dir,
        runs_dir=runs_dir,
        services=services,
    )


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve_path(value: Optional[str], settings: AppSettings, fallback: Path) -> Path:
    if not value:
        return fallback
    path = Path(value)
    if not path.is_absolute():
        path = settings.project_root / path
    return path.expanduser().resolve()


def _default_services(settings: AppSettings) -> dict[str, MCPServerConfig]:
    return {
        "youtube_audio": MCPServerConfig(
            name="youtube-audio-extractor",
            transport="stdio",
            command=settings.python_cmd,
            args=["-m", "app.mcp_server"],
            cwd=settings.yt_extractor_dir,
        ),
        "asr": MCPServerConfig(
            name="asr-service",
            transport="stdio",
            command=settings.python_cmd,
            args=["-m", "app.mcp_server"],
            cwd=settings.asr_dir,
        ),
        "translate": MCPServerConfig(
            name="translation-agent",
            transport="stdio",
            command=settings.python_cmd,
            args=["-m", "app.mcp_server"],
            cwd=settings.translate_dir,
        ),
        "tts": MCPServerConfig(
            name="voice-generate",
            transport="stdio",
            command=settings.python_cmd,
            args=["-m", "app.mcp_server"],
            cwd=settings.tts_dir,
        ),
    }


def _merge_services(
    defaults: dict[str, MCPServerConfig],
    overrides: dict[str, Any],
    settings: AppSettings,
) -> dict[str, MCPServerConfig]:
    merged = dict(defaults)
    for key, value in overrides.items():
        if not isinstance(value, dict):
            continue
        base = defaults.get(key)
        merged[key] = _override_service(base, value, settings)
    return merged


def _override_service(
    base: Optional[MCPServerConfig],
    override: dict[str, Any],
    settings: AppSettings,
) -> MCPServerConfig:
    name = override.get("name") or (base.name if base else "mcp-service")
    transport = override.get("transport") or (base.transport if base else "stdio")
    command = override.get("command") or (base.command if base else settings.python_cmd)
    args = override.get("args") or (base.args if base else ["-m", "app.mcp_server"])
    cwd_value = override.get("cwd") or (str(base.cwd) if base and base.cwd else None)
    cwd = _resolve_path(cwd_value, settings, fallback=settings.project_root) if cwd_value else None
    url = override.get("url") or (base.url if base else None)
    headers = override.get("headers") or (base.headers if base else None)
    env = override.get("env") or (base.env if base else None)

    return MCPServerConfig(
        name=name,
        transport=transport,
        command=command,
        args=args,
        cwd=cwd,
        url=url,
        headers=headers,
        env=env,
    )
