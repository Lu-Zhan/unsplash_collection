#!/usr/bin/env bash
# Unsplash Relighting Dataset 下载脚本
# 用法见下方 usage()

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PYTHON="${PYTHON:-python3}"
CONFIG="${CONFIG:-./keywords.yaml}"

usage() {
  cat <<EOF
用法：./run.sh <命令> [选项]

命令：
  all                   下载全部关键词（完整批次）
  d5 <类型[,类型...]>   只下载指定 D5 光照类型，如：./run.sh d5 golden_hour,rim_light
  stats                 生成/刷新下载统计表 downloads/stats.md
  dry                   预览所有任务列表（不下载）
  install               安装 Python 依赖

选项（环境变量）：
  CONFIG=路径           指定 keywords.yaml 路径（默认 ./keywords.yaml）
  PYTHON=路径           指定 Python 解释器（默认 python3）

速率控制：突发模式，自动读取 X-Ratelimit-Remaining 响应头。
  Demo key 50次/小时：可立即用完配额，配额耗尽后自动等待窗口重置。

示例：
  ./run.sh install
  ./run.sh stats
  ./run.sh dry
  ./run.sh d5 golden_hour
  ./run.sh d5 rim_light,tyndall,silhouette
  ./run.sh all
EOF
}

check_env() {
  if ! "$PYTHON" -c "import yaml, requests, tqdm, dotenv" &>/dev/null; then
    echo "⚠️  依赖缺失，请先运行：./run.sh install"
    exit 1
  fi
  if [ ! -f .env ] || ! grep -q "UNSPLASH_ACCESS_KEY" .env; then
    echo "⚠️  未找到 .env 文件或缺少 UNSPLASH_ACCESS_KEY，请参考 .env.example"
    exit 1
  fi
}

cmd_install() {
  echo "安装依赖..."
  "$PYTHON" -m pip install -r requirements.txt
  echo "完成。"
}

cmd_stats() {
  check_env
  "$PYTHON" batch_download_unsplash.py --config "$CONFIG" --stats
  echo "统计表路径：$SCRIPT_DIR/downloads/stats.md"
}

cmd_dry() {
  check_env
  "$PYTHON" batch_download_unsplash.py --config "$CONFIG" --dry-run
}

cmd_all() {
  check_env
  echo "开始全量下载（突发模式，配额耗尽自动等待重置）..."
  "$PYTHON" batch_download_unsplash.py --config "$CONFIG"
}

cmd_d5() {
  local d5_types="$1"
  check_env
  echo "下载 D5 类型：$d5_types（突发模式）..."
  "$PYTHON" batch_download_unsplash.py --config "$CONFIG" --d5 "$d5_types"
}

# ── 入口 ──────────────────────────────────────────
if [ $# -eq 0 ]; then
  usage
  exit 0
fi

case "$1" in
  install)  cmd_install ;;
  stats)    cmd_stats ;;
  dry)      cmd_dry ;;
  all)      cmd_all ;;
  d5)
    if [ $# -lt 2 ]; then
      echo "错误：d5 命令需要指定类型，如：./run.sh d5 golden_hour"
      exit 1
    fi
    cmd_d5 "$2"
    ;;
  -h|--help|help) usage ;;
  *)
    echo "未知命令：$1"
    usage
    exit 1
    ;;
esac
