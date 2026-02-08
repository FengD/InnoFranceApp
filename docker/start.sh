#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
APP_DIR="$ROOT_DIR/InnoFranceApp"
DOCKER_DIR="$APP_DIR/docker"

if ! command -v docker &> /dev/null; then
  echo "❌ Docker 未安装，请先安装 Docker"
  exit 1
fi

if docker compose version &> /dev/null; then
  COMPOSE_CMD="docker compose"
elif command -v docker-compose &> /dev/null; then
  COMPOSE_CMD="docker-compose"
else
  echo "❌ 未检测到 docker compose，请先安装"
  exit 1
fi

mkdir -p "$APP_DIR/runs"
mkdir -p "$APP_DIR/models"

if [ ! -f "$APP_DIR/.env" ]; then
  cp "$APP_DIR/env.example" "$APP_DIR/.env"
  echo "⚠️  已复制 .env 模板到 $APP_DIR/.env，请按需修改"
fi

cd "$DOCKER_DIR"

echo "📦 构建镜像..."
$COMPOSE_CMD build

echo "🚀 启动服务..."
$COMPOSE_CMD up -d

echo "✅ 启动完成"
echo "后端: http://localhost:8000"
echo "前端: http://localhost:8003"
