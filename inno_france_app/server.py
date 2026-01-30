from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from .api import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="Run InnoFrance Pipeline API server.")
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind host.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Bind port.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to config JSON.",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload for development.",
    )
    args = parser.parse_args()
    app = create_app(args.config)
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
