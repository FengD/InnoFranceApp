#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DOCKER_DIR="$APP_DIR/docker"

if docker compose version &> /dev/null; then
  COMPOSE_CMD="docker compose"
elif command -v docker-compose &> /dev/null; then
  COMPOSE_CMD="docker-compose"
else
  echo "❌ 未检测到 docker compose，请先安装"
  exit 1
fi

cd "$DOCKER_DIR"
$COMPOSE_CMD down
echo "🛑 已停止并清理容器"
