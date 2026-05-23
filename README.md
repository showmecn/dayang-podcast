# 🌊 大洋播客 (Dayang Podcast)

AI-powered podcast recommendation + knowledge extraction for professionals in finance, tech, and law.

## Architecture

```
User → [POST /api/recommend] → Cache check → Vector search (pgvector) top-20
     → LLM re-rank top-3 → Generate summaries → Cache → Response
```

**Key design decisions** (from CTO architecture review):
- **Hybrid recommendation**: embedding recall + LLM re-ranking (no pure LLM)
- **pgvector** on PostgreSQL (not Pinecone — MVP scale is ~10k vectors)
- **No audio transcription** (Phase 2 only — MVP uses show notes / description)
- **Daily batch updates** via cron, user requests processed in real-time
- **Target latency**: < 5s per request; cache hits < 500ms

## Quick Start

### Prerequisites
- Python 3.11+
- Docker (for PostgreSQL with pgvector + Redis)
- DeepSeek API key (set in `.env`)

### 1. Clone and setup

```bash
cd dayang-podcast
cp .env.example .env
# Edit .env — set your DEEPSEEK_API_KEY and PODCAST_INDEX_API_KEY
make install
```

### 2. Start services

```bash
make dev-db   # docker compose up -d postgres redis
```

### 3. Initialize database and seed

```bash
make migrate  # Creates tables + enables pgvector
make seed     # Ingests ~16 curated podcast shows
```

### 4. Run the API

```bash
make dev      # uvicorn app.main:app --reload
```

Open http://localhost:8088/docs for interactive API docs.

## API Endpoints

### `POST /api/recommend`

Main recommendation pipeline. Takes a topic, returns top-3 podcast episodes with AI summaries.

**Request:**
```json
{
  "topic": "AI regulation in Europe",
  "top_k": 3,
  "refresh": false
}
```

**Response:**
```json
{
  "topic": "AI regulation in Europe",
  "recommendations": [
    {
      "episode_id": "uuid",
      "show_title": "The Lawfare Podcast",
      "episode_title": "EU AI Act: What You Need to Know",
      "summary": "~200字中文摘要",
      "reason": "直接讨论欧盟AI法案的关键条款...",
      "timestamps": [
        {"time_str": "12:34", "label": "讨论监管框架"},
        {"time_str": "45:00", "label": "企业合规建议"}
      ],
      "relevance_score": 92,
      "published_at": "2026-05-20T00:00:00Z",
      "audio_url": "https://...",
      "episode_url": "https://..."
    }
  ],
  "cached": false,
  "total_candidates": 20,
  "processing_time_ms": 2840
}
```

### `GET /health`

Health check endpoint.

## Project Structure

```
dayang-podcast/
├── app/
│   ├── main.py                   # FastAPI app entry point
│   ├── config.py                 # Pydantic settings
│   ├── database.py               # SQLAlchemy + pgvector setup
│   ├── models/
│   │   ├── db_models.py          # SQLAlchemy models (Show, Episode, Cache)
│   │   └── schemas.py            # Pydantic request/response schemas
│   ├── data_pipeline/
│   │   ├── podcast_index.py      # Podcast Index API v2.0
│   │   ├── apple_podcasts.py     # Apple Podcasts Search API
│   │   ├── feed_parser.py        # RSS/Atom feed parsing
│   │   └── etl.py                # ETL: parse → dedup → classify → store
│   ├── vector_pipeline/
│   │   ├── embedder.py           # Local sentence-transformers (all-MiniLM-L6-v2)
│   │   └── indexer.py            # Batch embedding + pgvector index
│   ├── recommender/
│   │   ├── router.py             # /api/recommend endpoint
│   │   ├── retriever.py          # pgvector cosine similarity search
│   │   ├── reranker.py           # LLM re-ranking (DeepSeek)
│   │   └── fallback.py           # Cold start fallback strategies
│   ├── summary/
│   │   └── generator.py          # Summary + timestamp extraction
│   ├── cache/
│   │   └── redis_cache.py        # Redis (Upstash) caching layer
│   └── scheduler/
│       └── daily_refresh.py      # Daily data refresh script
├── tests/
│   ├── conftest.py
│   └── test_core.py
├── scripts/
│   └── seed_data.py              # Initial seed with curated shows
├── .github/workflows/
│   └── daily_refresh.yml         # GitHub Actions cron
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── Makefile
└── README.md
```

## Data Pipeline

### Refresh Cycle (daily, UTC+8 02:00)

1. Fetch recent episodes from each tracked show's RSS feed
2. Deduplicate by `source_episode_id`
3. Classify by category keywords
4. Detect language (Chinese / English)
5. Insert into PostgreSQL
6. Generate embeddings via local `all-MiniLM-L6-v2` (sentence-transformers)
7. Update pgvector index

### Seed Sources (MVP ~16 shows)

| Category | Examples |
|----------|----------|
| Tech | Lex Fridman, a16z, TechCrunch, Acquired, 硅谷101, 科技聚变 |
| Finance | Bloomberg Businessweek, Planet Money |
| Business | Tim Ferriss, HBR IdeaCast, 声动早咖啡 |
| Law/Policy | Lawfare, Rational Security |
| Science/AI | Practical AI |
| Culture | 忽左忽右, Hardcore History |

## Cost Estimates (100 DAU)

| Item | Cost/mo |
|------|---------|
| Frontend (Vercel/Cloudflare) | $0 |
| Backend (Render, 1 vCPU) | $7 |
| PostgreSQL (Render, 1GB) | $7 |
| Redis (Upstash free) | $0 |
| AI API (DeepSeek) | $10-40 |
| **Total** | **$24-54/mo** |

## Configuration

| Env Var | Default | Description |
|---------|---------|-------------|
| `DATABASE_URL` | `postgresql+asyncpg://dayang:dayang@localhost:5432/dayang` | PostgreSQL connection string |
| `DEEPSEEK_API_KEY` | — | DeepSeek API key |
| `LLM_MODEL` | `deepseek-chat` | DeepSeek model for re-ranking + summary |
| `LLM_PROVIDER` | `deepseek` | Always `deepseek` per company policy |
| `PODCAST_INDEX_API_KEY` | — | Podcast Index API key |
| `PODCAST_INDEX_API_SECRET` | — | Podcast Index API secret |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection string |
| `CORS_ORIGINS` | `http://localhost:5173,http://localhost:3000` | Allowed CORS origins |

## Running Tests

```bash
make test        # pytest with coverage
make test-cov    # HTML coverage report
```

## Architecture Constraints

- **Hybrid recommendation**: embedding recall + LLM re-ranking (no pure LLM)
- **No audio transcription** in MVP (Phase 2)
- **pgvector** on PostgreSQL (not Pinecone — MVP scale is ~10k vectors)
- **Daily batch updates**, user requests in real-time
- **Target latency**: < 5s per request
- **Sources**: Podcast Index primary + Apple Podcasts secondary + manual curation
