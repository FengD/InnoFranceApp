from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

import click

from .config import load_app_config
from .pipeline import InnoFrancePipeline


@click.command()
@click.option("--youtube-url", default=None, help="YouTube video URL.")
@click.option("--audio-url", default=None, help="Direct audio URL (.mp3 or .wav).")
@click.option("--audio-path", default=None, help="Local audio path (.mp3 or .wav).")
@click.option("--provider", default="openai", show_default=True, help="LLM provider.")
@click.option("--model-name", default=None, help="Override model name.")
@click.option("--language", default="fr", show_default=True, help="ASR language code.")
@click.option("--chunk-length", default=30, show_default=True, type=int, help="ASR chunk length.")
@click.option("--speed", default=1.0, show_default=True, type=float, help="TTS speed.")
@click.option("--yt-cookies-file", default=None, help="Path to a YouTube cookies.txt file.")
@click.option(
    "--yt-cookies-from-browser",
    default=None,
    help="Browser name for yt-dlp cookiesfrombrowser (e.g. chrome).",
)
@click.option("--yt-user-agent", default=None, help="Custom YouTube User-Agent.")
@click.option("--yt-proxy", default=None, help="Proxy URL for YouTube extraction.")
@click.option("--config", "config_path", default=None, help="Path to config JSON.")
def main(
    youtube_url: Optional[str],
    audio_url: Optional[str],
    audio_path: Optional[str],
    provider: str,
    model_name: Optional[str],
    language: str,
    chunk_length: int,
    speed: float,
    yt_cookies_file: Optional[str],
    yt_cookies_from_browser: Optional[str],
    yt_user_agent: Optional[str],
    yt_proxy: Optional[str],
    config_path: Optional[str],
) -> None:
    sources = [value for value in (youtube_url, audio_url, audio_path) if value]
    if len(sources) != 1:
        raise click.UsageError(
            "Provide exactly one of --youtube-url, --audio-url, or --audio-path."
        )

    config = load_app_config(Path(config_path) if config_path else None)
    pipeline = InnoFrancePipeline(config)
    result = asyncio.run(
        pipeline.run(
            youtube_url=youtube_url,
            audio_url=audio_url,
            audio_path=audio_path,
            provider=provider,
            model_name=model_name,
            language=language,
            chunk_length=chunk_length,
            speed=speed,
            yt_cookies_file=yt_cookies_file,
            yt_cookies_from_browser=yt_cookies_from_browser,
            yt_user_agent=yt_user_agent,
            yt_proxy=yt_proxy,
        )
    )

    click.echo("Completed.")
    click.echo(f"Summary: {result.summary_path}")
    click.echo(f"Audio:   {result.audio_path}")
    click.echo(f"Run dir: {result.run_dir}")


if __name__ == "__main__":
    main()
