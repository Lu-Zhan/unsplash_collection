#!/usr/bin/env python3
from __future__ import annotations
import argparse
import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv
from tqdm import tqdm

load_dotenv()

UNSPLASH_API_BASE = "https://api.unsplash.com"
VALID_SIZES = ("raw", "full", "regular", "small", "thumb")


def get_access_key():
    key = os.getenv("UNSPLASH_ACCESS_KEY")
    if not key or key == "your_access_key_here":
        sys.exit("错误：请在 .env 文件中设置 UNSPLASH_ACCESS_KEY")
    return key


def load_progress(progress_file: Path) -> set:
    if progress_file.exists():
        with open(progress_file) as f:
            return set(json.load(f))
    return set()


def save_progress(progress_file: Path, downloaded: set):
    with open(progress_file, "w") as f:
        json.dump(list(downloaded), f)


def search_photos(query: str, count: int, access_key: str) -> list:
    photos = []
    page = 1
    per_page = min(30, count)
    headers = {"Authorization": f"Client-ID {access_key}"}

    with tqdm(total=count, desc="搜索图片", unit="张") as pbar:
        while len(photos) < count:
            resp = requests.get(
                f"{UNSPLASH_API_BASE}/search/photos",
                params={"query": query, "per_page": per_page, "page": page},
                headers=headers,
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])
            if not results:
                break
            photos.extend(results)
            pbar.update(len(results))
            if len(data.get("results", [])) < per_page:
                break
            page += 1

    return photos[:count]


def trigger_download_event(photo_id: str, access_key: str):
    """按 Unsplash API 规范触发下载统计"""
    try:
        requests.get(
            f"{UNSPLASH_API_BASE}/photos/{photo_id}/download",
            headers={"Authorization": f"Client-ID {access_key}"},
            timeout=10,
        )
    except Exception:
        pass


def download_image(url: str, dest: Path) -> bool:
    try:
        resp = requests.get(url, stream=True, timeout=60)
        resp.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        return True
    except Exception as e:
        print(f"\n下载失败 {dest.name}: {e}")
        return False


def fetch_photo_detail(photo_id: str, access_key: str) -> dict:
    resp = requests.get(
        f"{UNSPLASH_API_BASE}/photos/{photo_id}",
        headers={"Authorization": f"Client-ID {access_key}"},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def save_metadata(
    photo: dict,
    dest: Path,
    labels: dict | None = None,
    detail: dict | None = None,
):
    meta = {
        "id": photo.get("id"),
        "description": photo.get("description"),
        "alt_description": photo.get("alt_description"),
        "width": photo.get("width"),
        "height": photo.get("height"),
        "created_at": photo.get("created_at"),
        "color": photo.get("color"),
        "likes": photo.get("likes"),
        "tags": [t.get("title") for t in photo.get("tags", [])],
        "urls": photo.get("urls"),
        "user": {
            "name": photo.get("user", {}).get("name"),
            "username": photo.get("user", {}).get("username"),
            "portfolio_url": photo.get("user", {}).get("portfolio_url"),
        },
        "links": photo.get("links"),
    }
    if detail:
        meta["exif"] = detail.get("exif")
        meta["location"] = detail.get("location")
    if labels:
        meta["labels"] = labels
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def get_pexels_api_key() -> str:
    key = os.getenv("PEXELS_API_KEY")
    if not key or key == "your_pexels_api_key_here":
        sys.exit("错误：请在 .env 文件中设置 PEXELS_API_KEY")
    return key


def main():
    parser = argparse.ArgumentParser(description="Unsplash 图片批量下载工具")
    parser.add_argument("-q", "--query", required=True, help="搜索关键词")
    parser.add_argument("-n", "--count", type=int, default=20, help="下载数量（默认 20）")
    parser.add_argument(
        "-s",
        "--size",
        choices=VALID_SIZES,
        default="regular",
        help="图片分辨率：raw/full/regular/small/thumb（默认 regular）",
    )
    parser.add_argument("-o", "--output", default="./downloads", help="输出目录（默认 ./downloads）")
    parser.add_argument(
        "--fetch-exif",
        action="store_true",
        help="额外调用 /photos/{id} 获取 EXIF 和地理位置信息（每张多 1 次 API 请求）",
    )
    args = parser.parse_args()

    access_key = get_access_key()

    keyword_dir = Path(args.output) / args.query.replace(" ", "_")
    progress_file = keyword_dir / "progress.json"

    keyword_dir.mkdir(parents=True, exist_ok=True)

    downloaded = load_progress(progress_file)
    print(f"关键词：{args.query} | 目标数量：{args.count} | 分辨率：{args.size}")
    print(f"已有记录：{len(downloaded)} 张，将自动跳过重复")

    photos = search_photos(args.query, args.count, access_key)
    new_photos = [p for p in photos if p["id"] not in downloaded]
    print(f"搜索到 {len(photos)} 张，其中新图片 {len(new_photos)} 张")

    if not new_photos:
        print("没有需要下载的新图片。")
        return

    success = 0
    for photo in tqdm(new_photos, desc="下载中", unit="张"):
        photo_id = photo["id"]
        image_url = photo.get("urls", {}).get(args.size)
        if not image_url:
            continue

        photo_dir = keyword_dir / photo_id
        photo_dir.mkdir(exist_ok=True)
        detail = fetch_photo_detail(photo_id, access_key) if args.fetch_exif else None
        save_metadata(photo, photo_dir / f"{photo_id}.json", detail=detail)
        trigger_download_event(photo_id, access_key)

        if download_image(image_url, photo_dir / f"{photo_id}.jpg"):
            downloaded.add(photo_id)
            save_progress(progress_file, downloaded)
            success += 1

    print(f"\n完成！本次成功下载 {success} 张，输出目录：{keyword_dir.resolve()}")


if __name__ == "__main__":
    main()
