# 大洋播客 — API 契约文档

> 版本: v0.1.0 | 更新: 2026-05-22 | 状态: ✅ 定稿

---

## 1. 概述

Base URL: `https://api.dayang-podcast.com` (生产) | `http://localhost:8088` (本地)

认证方式: 无（MVP 开放访问，Phase 2 引入 API Key）

---

## 2. 核心推荐 API

### `POST /api/recommend`

**主推荐管线。** 输入话题 → 输出 3 个精选播客集 + AI 摘要 + 推荐理由 + 时间戳。

#### Request

```json
{
  "topic": "AI regulation in Europe",
  "top_k": 3,
  "refresh": false
}
```

| 字段 | 类型 | 必填 | 默认 | 说明 |
|------|------|------|------|------|
| `topic` | string | ✅ | — | 用户输入话题，1-500 字符 |
| `top_k` | integer | ❌ | 3 | 返回结果数，1-10 |
| `refresh` | boolean | ❌ | false | 跳过缓存，强制重新生成 |

#### Response (200)

```json
{
  "topic": "AI regulation in Europe",
  "recommendations": [
    {
      "episode_id": "550e8400-e29b-41d4-a716-446655440000",
      "show_id": "550e8400-e29b-41d4-a716-446655440001",
      "episode_title": "EU AI Act: What You Need to Know",
      "show_title": "The Lawfare Podcast",
      "show_artwork_url": "https://...",
      "published_at": "2026-05-20T00:00:00Z",
      "duration_sec": 2700,
      "audio_url": "https://...",
      "episode_url": "https://...",
      "summary": "本节讨论了欧盟AI法案的核...",
      "reason": "直接讨论欧盟AI法案的关键条款和合规要求",
      "timestamps": [
        {"time_str": "12:34", "label": "讨论监管框架"},
        {"time_str": "45:00", "label": "企业合规建议"}
      ],
      "relevance_score": 92
    }
  ],
  "cached": false,
  "total_candidates": 20,
  "processing_time_ms": 2840,
  "disclaimer": "AI-generated recommendations and summaries. Verify with original content."
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `recommendations[]` | array | 推荐结果列表，默认 3 项 |
| `.summary` | string | ~200 字中文 AI 摘要 |
| `.reason` | string | 推荐理由（1-2 句） |
| `.timestamps[]` | array | 关键时间戳（从 show notes 提取） |
| `.relevance_score` | integer | 相关度评分 0-100 |
| `.episode_url` | string | 播客原文链接（外链） |
| `cached` | boolean | 是否来自缓存 |
| `total_candidates` | integer | 向量召回阶段总候选数 |
| `processing_time_ms` | integer | 总处理时间（毫秒） |

#### Error Response (4xx/5xx)

```json
{
  "error": "Bad Request",
  "detail": "topic must be between 1 and 500 characters"
}
```

---

## 3. 健康检查

### `GET /health`

```json
{
  "status": "ok",
  "version": "0.1.0",
  "db_connected": true,
  "cache_connected": true,
  "uptime_sec": 3600.5
}
```

---

## 4. 管线流程（后端内部）

```
用户输入 "AI regulation"
        │
        ▼
┌─────────────────────────────┐
│  Step 1: 缓存检查            │
│  SHA256(topic.lower) → Redis│
│  命中 → 直接返回 (＜500ms)   │
│  未命中 → 进入 Step 2       │
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│  Step 2: 向量召回 (top-20)   │
│  query → all-MiniLM-L6-v2    │
│  → pgvector cosine search   │
│  相似度阈值: 0.5             │
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│  Step 3: LLM 重排序 (→3)    │
│  DeepSeek v4 Flash           │
│  输入: query + 20集元数据   │
│  输出: 最相关 top-3 + 理由   │
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│  Step 4: 摘要生成            │
│  每集: show_notes/desc      │
│  → 200字中文摘要            │
│  → 关键时间戳提取            │
└─────────────┬───────────────┘
              │
              ▼
┌─────────────────────────────┐
│  Step 5: 缓存               │
│  topic_hash → result       │
│  TTL: 24h                  │
└─────────────┬───────────────┘
              │
              ▼
          返回响应
```

## 5. 降级策略

| 场景 | 行为 | 响应时间 |
|------|------|----------|
| 向量搜索命中 ≥ 3 集 | LLM 重排 top-3 | ~3s |
| 向量搜索命中 1-2 集 | 直接返回 + 默认理由 | ~1s |
| 向量搜索 0 命中 | 关键词全文搜索 fallback | ~500ms |
| 全文搜索也 0 命中 | 返回最新 3 集 | ~50ms |
| LLM 不可用 (API down) | 按向量相似度返回 top-3 | ~200ms |
| 缓存命中 | 直接返回 | < 50ms |

## 6. 数据模型

### Shows 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| title | TEXT | 播客节目名 |
| language | VARCHAR(10) | en/zh/unknown |
| category | TEXT[] | ['tech', 'finance', ...] |
| feed_url | TEXT UNIQUE | RSS Feed URL |
| artwork_url | TEXT | 封面图 |
| author | TEXT | 作者 |
| source | TEXT | podcast_index/apple/manual |

### Episodes 表

| 字段 | 类型 | 说明 |
|------|------|------|
| id | UUID | 主键 |
| show_id | UUID FK | 关联 shows |
| title | TEXT | 集标题 |
| description | TEXT | 短描述 |
| show_notes | TEXT | 长 show notes |
| published_at | TIMESTAMPTZ | 发布日期 |
| duration_sec | INTEGER | 时长 (秒) |
|| embedding | VECTOR(384) | all-MiniLM-L6-v2 向量 (本地模型) |
| source_episode_id | TEXT | 源平台 ID |
| audio_url | TEXT | 音频链接 |
| episode_url | TEXT | 原始链接 |
