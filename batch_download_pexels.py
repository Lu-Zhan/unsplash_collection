#!/usr/bin/env python3
from __future__ import annotations
"""
批量下载脚本 - 读取 keywords.yaml 按 D5 光照类型批量下载 Pexels 图片

跨 query 全局去重：同一 photo_id 只保存一份实体文件，
后续 query 遇到相同图片时创建 symlink，JSON 元数据各自独立写入。

用法:
  python batch_download_pexels.py                         # 下载全部
  python batch_download_pexels.py --d5 golden_hour        # 只下载某 D5 类型
  python batch_download_pexels.py --d5 rim_light,tyndall  # 多个 D5 类型
  python batch_download_pexels.py --dry-run               # 仅打印任务列表
  python batch_download_pexels.py --stats                 # 生成下载统计表
"""

import argparse
import datetime
import json
import math
import os
import time
from pathlib import Path

import requests
import yaml
from tqdm import tqdm

from download import download_image, get_pexels_api_key, load_progress, save_progress

PEXELS_API_BASE = "https://api.pexels.com/v1"
# keywords.yaml 中的 size 值映射到 Pexels src 字段
SIZE_MAP = {
    "raw": "original",
    "full": "original",
    "regular": "large2x",
    "small": "medium",
    "thumb": "small",
}
GLOBAL_REGISTRY_FILE = "global_registry.json"
DEFAULT_OUTPUT = "./download_pexels"


class RateLimiter:
    """突发模式：请求自由发出，仅当配额耗尽时等待窗口重置。"""

    def __init__(self):
        self.remaining = 200  # Pexels 免费账户 200 次/小时
        self.reset_ts = 0

    def update(self, resp_headers: dict):
        raw = resp_headers.get("X-Ratelimit-Remaining")
        if raw is not None:
            self.remaining = int(raw)
        raw_reset = resp_headers.get("X-Ratelimit-Reset")
        if raw_reset is not None:
            self.reset_ts = int(raw_reset)

    def seconds_until_reset(self) -> int:
        now = int(time.time())
        if self.reset_ts > now:
            return self.reset_ts - now + 5
        next_hour = (now // 3600 + 1) * 3600
        return next_hour - now + 5

    def wait_if_exhausted(self):
        if self.remaining <= 1:
            wait_sec = self.seconds_until_reset()
            mins, secs = divmod(wait_sec, 60)
            print(f"\n[配额耗尽] 剩余 {self.remaining} 次，等待 {mins}分{secs}秒 直到窗口重置...")
            time.sleep(wait_sec)
            self.remaining = 200


def load_global_registry(output_root: Path) -> dict:
    registry_path = output_root / GLOBAL_REGISTRY_FILE
    if registry_path.exists():
        with open(registry_path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_global_registry(output_root: Path, registry: dict):
    registry_path = output_root / GLOBAL_REGISTRY_FILE
    tmp_path = registry_path.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(registry, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, registry_path)


def load_config(config_path: Path) -> dict:
    with open(config_path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def extract_jobs(config: dict, filter_d5: list | None = None) -> list:
    default_size = config.get("meta", {}).get("default_size", "regular")
    default_count = config.get("meta", {}).get("default_count", 50)

    jobs = []
    for group_name, group in config.items():
        if group_name == "meta" or not isinstance(group, dict):
            continue
        for category_name, category in group.items():
            if not isinstance(category, dict):
                continue
            d5 = category.get("d5", category_name)
            if filter_d5 and d5 not in filter_d5:
                continue
            category_d2 = category.get("d2", "unknown")
            for raw_job in category.get("jobs", []):
                query = raw_job["query"]
                count = raw_job.get("count", default_count)
                d2 = raw_job.get("d2", category_d2)
                size = raw_job.get("size", default_size)
                query_slug = query.replace(" ", "_")
                jobs.append({
                    "d5": d5,
                    "d2": d2,
                    "query": query,
                    "count": count,
                    "size": size,
                    "output_dir": str(Path(DEFAULT_OUTPUT) / d5 / query_slug),
                })
    return jobs


def collect_stats(jobs: list, output_root: Path) -> dict:
    registry = load_global_registry(output_root)
    unique_total = len(registry)
    global_target = sum(j["count"] for j in jobs)

    groups: dict = {}
    for job in jobs:
        d5 = job["d5"]
        progress_file = Path(job["output_dir"]) / "progress.json"
        downloaded = len(load_progress(progress_file))

        if d5 not in groups:
            groups[d5] = {"target": 0, "downloaded": 0, "jobs": []}
        groups[d5]["target"] += job["count"]
        groups[d5]["downloaded"] += downloaded
        groups[d5]["jobs"].append({
            "query": job["query"],
            "downloaded": downloaded,
            "target": job["count"],
        })

    return {
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "unique_total": unique_total,
        "global_target": global_target,
        "groups": groups,
    }


def _progress_bar(downloaded: int, target: int, width: int = 10) -> str:
    pct = downloaded / target if target > 0 else 0
    filled = round(pct * width)
    bar = "█" * filled + "░" * (width - filled)
    return f"{bar} {pct*100:5.1f}%"


def write_stats_md(stats: dict, output_path: Path):
    lines = []
    lines.append("# Pexels 下载统计")
    lines.append(
        f"更新时间：{stats['generated_at']} | "
        f"唯一图片（实体）：{stats['unique_total']} 张 | "
        f"全局目标：{stats['global_target']} 张"
    )
    lines.append("")

    total_downloaded = sum(g["downloaded"] for g in stats["groups"].values())
    overall_bar = _progress_bar(total_downloaded, stats["global_target"])
    lines.append(f"**总进度：{total_downloaded} / {stats['global_target']} 张  {overall_bar}**")
    lines.append("")
    lines.append("---")
    lines.append("")

    for d5, group in stats["groups"].items():
        g_bar = _progress_bar(group["downloaded"], group["target"])
        lines.append(f"### {d5} — {group['downloaded']} / {group['target']} 张  {g_bar}")
        lines.append("")
        lines.append("| 查询关键词 | 已下载 | 目标 | 进度 |")
        lines.append("|---|---|---|---|")
        for job in group["jobs"]:
            bar = _progress_bar(job["downloaded"], job["target"])
            lines.append(
                f"| {job['query']} | {job['downloaded']} | {job['target']} | {bar} |"
            )
        lines.append("")

    n_jobs = sum(len(g["jobs"]) for g in stats["groups"].values())
    n_d5 = len(stats["groups"])
    lines.append("---")
    lines.append(f"*共 {n_jobs} 个 job，{n_d5} 种 D5 光照类型*")

    tmp = output_path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    os.replace(tmp, output_path)


def save_metadata_pexels(photo: dict, dest: Path, labels: dict | None = None):
    meta = {
        "id": str(photo.get("id")),
        "description": photo.get("alt"),
        "width": photo.get("width"),
        "height": photo.get("height"),
        "color": photo.get("avg_color"),
        "url": photo.get("url"),
        "urls": photo.get("src", {}),
        "user": {
            "name": photo.get("photographer"),
            "url": photo.get("photographer_url"),
            "id": photo.get("photographer_id"),
        },
        "source": "pexels",
    }
    if labels:
        meta["labels"] = labels
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def search_photos_pexels(
    query: str,
    count: int,
    api_key: str,
    rate_limiter: RateLimiter,
) -> list:
    photos = []
    page = 1
    per_page = min(80, count)
    headers = {"Authorization": api_key}

    while len(photos) < count:
        rate_limiter.wait_if_exhausted()
        resp = requests.get(
            f"{PEXELS_API_BASE}/search",
            params={"query": query, "per_page": per_page, "page": page},
            headers=headers,
            timeout=30,
        )
        rate_limiter.update(resp.headers)
        reset_time = (
            datetime.datetime.fromtimestamp(rate_limiter.reset_ts).strftime("%H:%M:%S")
            if rate_limiter.reset_ts else "unknown"
        )
        print(f"  [配额] 剩余 {rate_limiter.remaining}/200，窗口重置于 {reset_time}")

        if resp.status_code == 429:
            wait_sec = rate_limiter.seconds_until_reset()
            mins, secs = divmod(wait_sec, 60)
            wake_time = datetime.datetime.fromtimestamp(int(time.time()) + wait_sec).strftime("%H:%M:%S")
            print(f"\n[429 限流] 配额已用尽，等待 {mins}分{secs}秒（至 {wake_time}）后重试...")
            time.sleep(wait_sec)
            rate_limiter.remaining = 200
            continue

        resp.raise_for_status()
        results = resp.json().get("photos", [])
        if not results:
            break
        photos.extend(results)
        if len(results) < per_page:
            break
        page += 1

    return photos[:count]


def run_job(
    job: dict,
    api_key: str,
    rate_limiter: RateLimiter,
    global_registry: dict,
    output_root: Path,
) -> int:
    query = job["query"]
    count = job["count"]
    size = job["size"]
    d5 = job["d5"]
    d2 = job["d2"]
    output_dir = Path(job["output_dir"])

    output_dir.mkdir(parents=True, exist_ok=True)
    progress_file = output_dir / "progress.json"
    downloaded = load_progress(progress_file)

    need = count - len(downloaded)
    if need <= 0:
        print(f"  [跳过] '{query}' 已完成 ({len(downloaded)}/{count})")
        return 0

    photos = search_photos_pexels(query, count, api_key, rate_limiter)
    new_photos = [p for p in photos if str(p["id"]) not in downloaded]
    print(f"  搜索到 {len(photos)} 张，新图 {len(new_photos)} 张")

    pexels_size = SIZE_MAP.get(size, "large")
    success = 0
    linked = 0
    for photo in tqdm(new_photos, desc=f"  '{query}'", unit="张", leave=False):
        photo_id = str(photo["id"])
        image_url = photo.get("src", {}).get(pexels_size)
        if not image_url:
            continue

        photo_dir = output_dir / photo_id
        photo_dir.mkdir(exist_ok=True)

        # JSON 元数据始终独立写入（各 query 的 labels 不同）
        save_metadata_pexels(
            photo,
            photo_dir / f"{photo_id}.json",
            labels={"d5_lighting": d5, "d2_subject": d2},
        )

        jpg_path = photo_dir / f"{photo_id}.jpg"

        if photo_id in global_registry:
            existing = Path(global_registry[photo_id])
            if existing.exists() and not jpg_path.exists():
                rel = os.path.relpath(existing, jpg_path.parent)
                jpg_path.symlink_to(rel)
                linked += 1
            downloaded.add(photo_id)
            save_progress(progress_file, downloaded)
            success += 1
        else:
            if download_image(image_url, jpg_path):
                global_registry[photo_id] = str(jpg_path.resolve())
                save_global_registry(output_root, global_registry)
                downloaded.add(photo_id)
                save_progress(progress_file, downloaded)
                success += 1

    if linked:
        print(f"  其中 {linked} 张为 symlink（已有实体，跳过重复下载）")

    return success


def main():
    parser = argparse.ArgumentParser(
        description="批量下载 Pexels 图片（按 keywords.yaml）"
    )
    parser.add_argument("--config", default="./keywords.yaml", help="关键词配置文件路径")
    parser.add_argument(
        "--d5",
        default=None,
        help="只下载指定 D5 类型（逗号分隔），如 golden_hour,rim_light",
    )
    parser.add_argument("--dry-run", action="store_true", help="只打印任务列表，不实际下载")
    parser.add_argument(
        "--stats",
        action="store_true",
        help=f"生成下载统计表到 {DEFAULT_OUTPUT}/stats.md",
    )
    args = parser.parse_args()

    config = load_config(Path(args.config))
    filter_d5 = [x.strip() for x in args.d5.split(",")] if args.d5 else None

    stats_jobs = extract_jobs(config)
    jobs = extract_jobs(config, filter_d5)

    output_root = Path(DEFAULT_OUTPUT)
    output_root.mkdir(parents=True, exist_ok=True)
    stats_path = output_root / "stats.md"

    if not jobs:
        print("没有匹配的任务，请检查 --d5 参数或 YAML 配置。")
        return

    if args.stats:
        stats = collect_stats(stats_jobs, output_root)
        write_stats_md(stats, stats_path)
        print(f"统计表已生成：{stats_path.resolve()}")
        total_dl = sum(g["downloaded"] for g in stats["groups"].values())
        print(f"总进度：{total_dl} / {stats['global_target']} 张，唯一图片：{stats['unique_total']} 张")
        return

    total_target = sum(j["count"] for j in jobs)
    total_search_req = sum(math.ceil(j["count"] / 80) for j in jobs)

    print(f"共 {len(jobs)} 个下载任务，目标图片总数：{total_target} 张")
    print(f"估算 search 请求：{total_search_req} 次（Pexels 200次/小时，突发模式）")

    if args.dry_run:
        print("\n[Dry Run] 任务列表：")
        for i, job in enumerate(jobs, 1):
            print(
                f"  {i:3d}. D5={job['d5']:20s} D2={job['d2']:22s} "
                f"count={job['count']:3d}  '{job['query']}'"
            )
        return

    global_registry = load_global_registry(output_root)
    print(f"全局注册表已加载，已记录 {len(global_registry)} 张图片")

    api_key = get_pexels_api_key()
    rate_limiter = RateLimiter()

    total_downloaded = 0
    skipped = 0
    for i, job in enumerate(jobs, 1):
        print(f"\n[{i}/{len(jobs)}] D5={job['d5']} | '{job['query']}'")
        n = run_job(job, api_key, rate_limiter, global_registry, output_root)
        if n == 0 and (job["count"] - len(load_progress(
            Path(job["output_dir"]) / "progress.json"
        ))) <= 0:
            skipped += 1
        total_downloaded += n
        write_stats_md(collect_stats(stats_jobs, output_root), stats_path)

    print(f"\n{'='*50}")
    print(f"全部完成！本次处理 {total_downloaded} 张，跳过已完成任务 {skipped} 个")
    print(f"全局注册表共记录 {len(global_registry)} 张唯一图片")
    print(f"统计表：{stats_path.resolve()}")


if __name__ == "__main__":
    main()
