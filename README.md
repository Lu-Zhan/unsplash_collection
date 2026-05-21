# Unsplash / Pexels 批量图像下载工具

按 D5 光照类型和 D2 主体类型批量下载图片，用于构建 Relighting 数据集。

## 快速开始

**1. 安装依赖**

```bash
./run_unsplash.sh install
```

**2. 配置 API Key**

复制 `.env.example` 为 `.env`，填入对应平台的 API Key：

```
UNSPLASH_ACCESS_KEY=your_unsplash_access_key
PEXELS_API_KEY=your_pexels_api_key
```

- Unsplash Key：[unsplash.com/developers](https://unsplash.com/developers)（Demo key 免费，50 次/小时）
- Pexels Key：[pexels.com/api](https://www.pexels.com/api/)（免费，200 次/小时）

**3. 下载图片**

```bash
# Unsplash
./run_unsplash.sh all          # 下载全部
./run_unsplash.sh d5 golden_hour          # 只下载指定 D5 类型
./run_unsplash.sh d5 rim_light,tyndall    # 多个 D5 类型（逗号分隔）

# Pexels
./run_pexels.sh all
./run_pexels.sh d5 golden_hour
```

## 命令说明

| 命令 | 说明 |
|------|------|
| `all` | 下载全部关键词 |
| `d5 <类型>` | 只下载指定 D5 光照类型 |
| `dry` | 预览任务列表，不实际下载 |
| `stats` | 生成/刷新下载进度统计表 |
| `install` | 安装 Python 依赖 |

## 输出结构

```
downloads/                        # Unsplash 输出
  {d5_type}/
    {query_slug}/
      {photo_id}/
        {photo_id}.jpg            # 图片文件
        {photo_id}.json           # 元数据（含 d5_lighting、d2_subject 标签）
  global_registry.json            # 跨 query 去重注册表
  stats.md                        # 下载进度统计表

download_pexels/                  # Pexels 输出（结构相同）
```

元数据 JSON 示例：

```json
{
  "id": "abc123",
  "description": "...",
  "width": 3000,
  "height": 2000,
  "urls": { "regular": "...", "full": "..." },
  "labels": {
    "d5_lighting": "golden_hour",
    "d2_subject": "landscape"
  }
}
```

## 关键词配置

下载任务由 `keywords.yaml` 定义，按 D5 光照类型组织：

```yaml
meta:
  default_size: "regular"   # 图片分辨率
  default_count: 50         # 每个 query 默认下载数量

portrait_lighting:
  golden_hour:
    d5: golden_hour
    d2: landscape
    jobs:
      - query: "sunset golden hour"
        count: 50
```

目前支持的 D5 类型：`rembrandt`、`butterfly`、`split`、`flat`、`rim_light`、`tyndall`、`window_pattern`、`silhouette`、`cyberpunk_neon`、`teal_orange`、`moonlight_cool_mono`、`golden_hour`、`blue_hour`、`harsh_midday`、`overcast` 等共 23 种。

## 限流处理

两个平台的脚本均采用突发模式：配额耗尽时自动等待窗口重置，无需手动干预。

| 平台 | 免费限额 | 触发条件 | 等待依据 |
|------|----------|---------|---------|
| Unsplash | 50 次/小时 | HTTP 403 | `X-Ratelimit-Reset` 头 |
| Pexels | 200 次/小时 | HTTP 429 | `X-Ratelimit-Reset` 头 |
