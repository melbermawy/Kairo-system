# Kairo Deployment Strategy

> **Last Updated:** January 2026
> **Status:** Pre-deployment planning
> **Author:** System analysis

---

## Table of Contents

1. [System Profile](#system-profile)
2. [Services Required](#services-required)
3. [External Dependencies](#external-dependencies)
4. [Platform Comparison](#platform-comparison)
5. [Recommendation](#recommendation)
6. [Pre-Deployment Checklist](#pre-deployment-checklist)
7. [Cost Estimates](#cost-estimates)
8. [Configuration Reference](#configuration-reference)

---

## System Profile

### Tech Stack

| Component | Technology | Version |
|-----------|------------|---------|
| Framework | Django | 5.0 |
| Language | Python | 3.11 |
| Database | PostgreSQL | 16 |
| Container | Docker | Multi-stage |
| Background Jobs | Celery (planned) | - |
| Cache/Queue | Redis (planned) | - |

### Complexity Assessment

| Factor | Level | Notes |
|--------|-------|-------|
| **API Surface** | Medium | REST endpoints for hero loop, ingestion, decisions |
| **Database Schema** | Medium-High | 15+ models, multi-tenant by Brand |
| **External API Calls** | High | OpenAI (LLM), Apify (scraping), future social APIs |
| **Background Processing** | Required | Ingestion pipeline, learning events, scheduled jobs |
| **Real-time Requirements** | Low | No WebSockets currently, polling-based |
| **Data Volume** | Medium | Trend ingestion can grow, but scoped per brand |

---

## Services Required

### Core Services

```
┌─────────────────────────────────────────────────────────────────┐
│                        PRODUCTION ARCHITECTURE                   │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌────────────────┐         ┌────────────────┐                  │
│  │   Web Server   │         │   Background   │                  │
│  │   (Gunicorn)   │         │    Worker      │                  │
│  │                │         │   (Celery)     │                  │
│  │  - API routes  │         │                │                  │
│  │  - Admin       │         │  - Ingestion   │                  │
│  │  - Health      │         │  - Learning    │                  │
│  └───────┬────────┘         │  - Scoring     │                  │
│          │                  └───────┬────────┘                  │
│          │                          │                            │
│          └──────────┬───────────────┘                           │
│                     │                                            │
│          ┌──────────▼──────────┐                                │
│          │     PostgreSQL      │                                │
│          │   (Managed/Hosted)  │                                │
│          └──────────┬──────────┘                                │
│                     │                                            │
│          ┌──────────▼──────────┐                                │
│          │       Redis         │                                │
│          │  (Queue + Cache)    │                                │
│          └─────────────────────┘                                │
│                                                                  │
│  ┌────────────────┐                                             │
│  │  Cron/Scheduler│  (Platform-native or Celery Beat)          │
│  │  - Capture     │                                             │
│  │  - Aggregate   │                                             │
│  │  - Score       │                                             │
│  └────────────────┘                                             │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Service Breakdown

| Service | Purpose | Scaling Notes |
|---------|---------|---------------|
| **Web** | HTTP API, serves frontend requests | Horizontal (2-4 instances for prod) |
| **Worker** | Background task processing | Horizontal (queue-based) |
| **Scheduler** | Cron jobs for ingestion pipeline | Single instance |
| **PostgreSQL** | Primary data store | Vertical (managed service handles this) |
| **Redis** | Task queue + caching | Single instance for MVP |

### Scheduled Jobs Needed

| Job | Frequency | Purpose |
|-----|-----------|---------|
| `ingest_capture` | Every 30-60 min | Pull from Apify/external sources |
| `ingest_normalize` | After capture | Process raw → normalized |
| `ingest_aggregate` | Hourly | Build time-windowed buckets |
| `ingest_score` | Hourly | Score trends, lifecycle transitions |
| `process_learning_events` | Every 15 min | Process user decisions → learning signals |

---

## External Dependencies

### Required APIs

| Service | Purpose | Auth Method | Cost Model |
|---------|---------|-------------|------------|
| **OpenAI** | LLM for content generation, scoring | API Key (Bearer) | Per-token |
| **Apify** | Web scraping (TikTok, Instagram, LinkedIn, etc.) | API Token | Per-actor-run |

### Future APIs (Prepared, Not Implemented)

| Service | Purpose | Status |
|---------|---------|--------|
| Google Search API | Web mentions, search trends | Env vars ready |
| X/Twitter API | Social signals | Env vars ready |
| LinkedIn API | Direct integration (vs Apify) | OAuth prepared |

### API Reliability Considerations

| API | Reliability | Mitigation |
|-----|-------------|------------|
| OpenAI | Generally stable, occasional rate limits | Retry with exponential backoff, circuit breaker |
| Apify | Actor-dependent, can timeout | Hard caps on items, resume mode, TTL caching |

---

## Platform Comparison

### Evaluation Criteria

1. **Django/Python support** - Native or Docker-based
2. **PostgreSQL** - Managed offering included
3. **Redis** - Available as addon
4. **Background workers** - Supported pattern
5. **Cron/Scheduled jobs** - Built-in or via addon
6. **Developer experience** - Deploy speed, logs, debugging
7. **Pricing** - MVP-friendly, scales reasonably
8. **Reliability** - Uptime, support

### Platform Deep Dive

#### Railway

| Aspect | Rating | Notes |
|--------|--------|-------|
| **Django Support** | ⭐⭐⭐⭐⭐ | Native Nixpacks detection, or Docker |
| **PostgreSQL** | ⭐⭐⭐⭐⭐ | One-click addon, automatic backups |
| **Redis** | ⭐⭐⭐⭐⭐ | One-click addon |
| **Workers** | ⭐⭐⭐⭐⭐ | Separate service, same repo |
| **Cron Jobs** | ⭐⭐⭐⭐ | Built-in, cron syntax |
| **DX** | ⭐⭐⭐⭐⭐ | Excellent logs, instant deploys, GitHub integration |
| **Pricing** | ⭐⭐⭐⭐ | $5/mo base, usage-based after |
| **Reliability** | ⭐⭐⭐⭐ | Good uptime, responsive support |

**Pros:**
- Fastest time-to-deploy for Django
- All services (web, worker, db, redis) in one project
- Great observability out of the box
- Easy env var management
- PR preview environments

**Cons:**
- Can get expensive at scale (usage-based)
- Less control than IaaS
- No free tier (trial credits only)

---

#### Render

| Aspect | Rating | Notes |
|--------|--------|-------|
| **Django Support** | ⭐⭐⭐⭐⭐ | Native or Docker |
| **PostgreSQL** | ⭐⭐⭐⭐⭐ | Managed, 1GB free tier |
| **Redis** | ⭐⭐⭐⭐ | Available, no free tier |
| **Workers** | ⭐⭐⭐⭐ | Background workers supported |
| **Cron Jobs** | ⭐⭐⭐⭐⭐ | Native cron jobs feature |
| **DX** | ⭐⭐⭐⭐ | Good, slightly slower deploys |
| **Pricing** | ⭐⭐⭐⭐⭐ | Generous free tier, predictable paid |
| **Reliability** | ⭐⭐⭐⭐ | Solid uptime |

**Pros:**
- Free tier for validation
- Predictable pricing (not usage-based)
- Native cron job support
- Good documentation
- `render.yaml` infrastructure-as-code

**Cons:**
- Deploys slower than Railway (~2-5 min)
- Free tier has cold starts
- Redis costs extra ($10/mo minimum)

---

#### Fly.io

| Aspect | Rating | Notes |
|--------|--------|-------|
| **Django Support** | ⭐⭐⭐⭐ | Docker-based, fly launch wizard |
| **PostgreSQL** | ⭐⭐⭐⭐ | Fly Postgres (managed) |
| **Redis** | ⭐⭐⭐⭐ | Upstash Redis addon |
| **Workers** | ⭐⭐⭐⭐ | Via process groups |
| **Cron Jobs** | ⭐⭐⭐ | Via machines API or external |
| **DX** | ⭐⭐⭐ | Powerful but steeper learning curve |
| **Pricing** | ⭐⭐⭐⭐⭐ | Very cheap, generous free tier |
| **Reliability** | ⭐⭐⭐⭐ | Good, global edge network |

**Pros:**
- Cheapest at scale
- Global edge deployment
- Great for latency-sensitive apps
- Generous free allowances

**Cons:**
- More configuration complexity
- Fly Postgres has had reliability issues
- Cron jobs require extra setup
- Learning curve for `fly.toml`

---

#### Heroku

| Aspect | Rating | Notes |
|--------|--------|-------|
| **Django Support** | ⭐⭐⭐⭐⭐ | Battle-tested, native buildpack |
| **PostgreSQL** | ⭐⭐⭐⭐⭐ | Heroku Postgres, excellent |
| **Redis** | ⭐⭐⭐⭐⭐ | Heroku Redis addon |
| **Workers** | ⭐⭐⭐⭐⭐ | Procfile-based, mature |
| **Cron Jobs** | ⭐⭐⭐⭐ | Heroku Scheduler addon |
| **DX** | ⭐⭐⭐⭐ | Mature, well-documented |
| **Pricing** | ⭐⭐⭐ | Expensive ($7/dyno minimum, adds up) |
| **Reliability** | ⭐⭐⭐⭐⭐ | Very reliable, enterprise-grade |

**Pros:**
- Most mature platform
- Excellent PostgreSQL offering
- Battle-tested for Django
- Great addon ecosystem

**Cons:**
- Expensive (no free tier anymore)
- $7/mo per dyno adds up fast
- Feels dated compared to newer platforms
- Slower innovation

---

#### Supabase + Vercel/Other

| Aspect | Rating | Notes |
|--------|--------|-------|
| **Django Support** | ⭐⭐⭐ | Database only, need separate compute |
| **PostgreSQL** | ⭐⭐⭐⭐⭐ | Excellent, with realtime, auth, storage |
| **Redis** | ⭐⭐ | Not included, need external |
| **Workers** | ⭐⭐ | Need separate service |
| **Cron Jobs** | ⭐⭐⭐ | Via Vercel cron or external |
| **DX** | ⭐⭐⭐⭐ | Great for DB, fragmented for full stack |
| **Pricing** | ⭐⭐⭐⭐ | Generous free tier |
| **Reliability** | ⭐⭐⭐⭐ | Good |

**Pros:**
- Excellent PostgreSQL with extras (auth, realtime, storage)
- Great free tier for database
- Good if you want to use Supabase features

**Cons:**
- Need to combine with another platform for compute
- Fragmented infrastructure
- More moving parts to manage

---

#### AWS / GCP / Azure (IaaS)

| Aspect | Rating | Notes |
|--------|--------|-------|
| **Django Support** | ⭐⭐⭐⭐⭐ | Full control |
| **PostgreSQL** | ⭐⭐⭐⭐⭐ | RDS / Cloud SQL / Azure DB |
| **Redis** | ⭐⭐⭐⭐⭐ | ElastiCache / Memorystore / Azure Cache |
| **Workers** | ⭐⭐⭐⭐⭐ | ECS, Cloud Run, Lambda, etc. |
| **Cron Jobs** | ⭐⭐⭐⭐⭐ | CloudWatch Events, Cloud Scheduler |
| **DX** | ⭐⭐ | Complex, requires DevOps expertise |
| **Pricing** | ⭐⭐⭐ | Can be cheap, can be expensive, hard to predict |
| **Reliability** | ⭐⭐⭐⭐⭐ | Enterprise-grade |

**Pros:**
- Full control
- Enterprise-grade everything
- Scales infinitely
- Compliance options (HIPAA, SOC2, etc.)

**Cons:**
- Requires DevOps expertise
- Complex setup (VPCs, IAM, etc.)
- Overkill for MVP
- Easy to overspend

---

### Comparison Matrix

| Platform | Django | Postgres | Redis | Workers | Cron | DX | Price | Best For |
|----------|--------|----------|-------|---------|------|-----|-------|----------|
| **Railway** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | $$ | Fast iteration, small teams |
| **Render** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | $ | Budget-conscious, free tier |
| **Fly.io** | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐ | $ | Global latency, cheap scale |
| **Heroku** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | $$$ | Enterprise, mature needs |
| **AWS/GCP** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐ | $$$ | Full control, compliance |

---

## Recommendation

### Primary: Railway

**Why Railway for Kairo:**

1. **Perfect Django fit** - Native detection, zero config needed
2. **All-in-one project** - Web, worker, Postgres, Redis in single project
3. **Fastest iteration** - Deploy in seconds, great logs
4. **Cron support** - Built-in for ingestion pipeline
5. **Scales with you** - Start small, add resources as needed
6. **Team-friendly** - Easy collaboration, PR previews

### Alternative: Render

**Choose Render if:**
- You want a free tier to validate before paying
- Predictable pricing is more important than speed
- You prefer infrastructure-as-code (`render.yaml`)

### When to Consider Others

| Scenario | Platform |
|----------|----------|
| Need free tier for extended validation | Render |
| Global users, latency matters | Fly.io |
| Enterprise compliance requirements | AWS/GCP with proper setup |
| Already have AWS/GCP infrastructure | Stay there, use their PaaS options |
| Want Supabase features (auth, realtime) | Supabase + Railway/Render for compute |

---

## Pre-Deployment Checklist

### Code Changes Required

#### 1. Add Gunicorn (Production Server)

```toml
# pyproject.toml - add to dependencies
gunicorn = ">=21.0"
```

```dockerfile
# Dockerfile - change CMD
CMD ["gunicorn", "kairo.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "4", "--threads", "2"]
```

#### 2. Add Missing Dependencies

```toml
# pyproject.toml - add these (currently used but not declared)
pydantic = ">=2.0"
requests = ">=2.31"
openai = ">=1.0"
```

#### 3. Add Health Check Endpoint

```python
# kairo/core/views.py
from django.http import JsonResponse
from django.db import connection

def health_check(request):
    """Health check endpoint for platform monitoring."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return JsonResponse({"status": "healthy", "database": "connected"})
    except Exception as e:
        return JsonResponse({"status": "unhealthy", "error": str(e)}, status=500)
```

```python
# kairo/urls.py - add route
path("health/", health_check, name="health_check"),
```

#### 4. Add LLM Retry Logic

```python
# kairo/hero/llm_client.py - wrap API calls
import time
from functools import wraps

def retry_with_backoff(max_retries=3, base_delay=1):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_retries - 1:
                        raise
                    delay = base_delay * (2 ** attempt)
                    time.sleep(delay)
            return None
        return wrapper
    return decorator
```

#### 5. Configure Allowed Hosts

```python
# kairo/settings.py - ensure this is set
ALLOWED_HOSTS = os.getenv("ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
```

### Platform Configuration Files

#### Railway (`railway.toml`)

```toml
[build]
builder = "dockerfile"

[deploy]
healthcheckPath = "/health/"
healthcheckTimeout = 30
restartPolicyType = "on_failure"
restartPolicyMaxRetries = 3
```

#### Render (`render.yaml`)

```yaml
services:
  - type: web
    name: kairo-web
    runtime: docker
    healthCheckPath: /health/
    envVars:
      - key: DATABASE_URL
        fromDatabase:
          name: kairo-db
          property: connectionString
      - key: DJANGO_SECRET_KEY
        generateValue: true
      - key: DJANGO_DEBUG
        value: "False"

  - type: worker
    name: kairo-worker
    runtime: docker
    dockerCommand: celery -A kairo worker --loglevel=info

databases:
  - name: kairo-db
    plan: starter
```

---

## Cost Estimates

### MVP Stage (Single User / Demo)

| Component | Railway | Render | Fly.io |
|-----------|---------|--------|--------|
| Web (1 instance) | $5/mo | Free / $7 | $3/mo |
| PostgreSQL | $5/mo | Free (1GB) | $5/mo |
| Redis | $5/mo | $10/mo | $5/mo |
| **Subtotal** | **$15/mo** | **$10-17/mo** | **$13/mo** |

### Production Stage (10-50 Users)

| Component | Railway | Render | Heroku |
|-----------|---------|--------|--------|
| Web (2 instances) | $20/mo | $14/mo | $50/mo |
| Worker (1 instance) | $10/mo | $7/mo | $25/mo |
| PostgreSQL | $15/mo | $15/mo | $50/mo |
| Redis | $10/mo | $10/mo | $15/mo |
| **Subtotal** | **$55/mo** | **$46/mo** | **$140/mo** |

### External API Costs (Variable)

| API | Low Usage | Medium Usage | High Usage |
|-----|-----------|--------------|------------|
| OpenAI | $10/mo | $30/mo | $100+/mo |
| Apify | $5/mo | $20/mo | $50+/mo |

---

## Configuration Reference

### Required Environment Variables

```bash
# Core
APP_ENV=production
DJANGO_SECRET_KEY=<generate-random-string>
DJANGO_DEBUG=False
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com
CORS_ALLOWED_ORIGINS=https://yourdomain.com

# Database
DATABASE_URL=postgresql://user:pass@host:5432/dbname

# LLM
OPENAI_API_KEY=sk-...
KAIRO_LLM_MODEL_FAST=gpt-4o-mini
KAIRO_LLM_MODEL_HEAVY=gpt-4o
KAIRO_LLM_TIMEOUT_FAST=10
KAIRO_LLM_TIMEOUT_HEAVY=30
LLM_DISABLED=False

# Ingestion
APIFY_TOKEN=apify_api_...
EXTERNAL_SIGNALS_MODE=ingestion

# Observability (Optional)
SENTRY_DSN=https://...@sentry.io/...
LOG_LEVEL=INFO
```

### Security Checklist

- [ ] `DJANGO_DEBUG=False` in production
- [ ] `DJANGO_SECRET_KEY` is unique and random
- [ ] `ALLOWED_HOSTS` restricts to your domains
- [ ] `CORS_ALLOWED_ORIGINS` restricts to your frontend
- [ ] Database credentials not in code
- [ ] API keys not in code
- [ ] HTTPS enforced (platform handles this)

---

## Summary

**For Kairo's current state and trajectory:**

| Phase | Recommendation |
|-------|----------------|
| **Development** | Docker Compose (current setup works) |
| **Validation/MVP** | Railway (fastest, all-in-one) |
| **Growth** | Stay on Railway or migrate to Render for cost |
| **Scale/Enterprise** | Evaluate AWS/GCP when you hit platform limits |

**Next Steps:**
1. Add Gunicorn + missing dependencies
2. Add health check endpoint
3. Add LLM retry logic
4. Create `railway.toml` or `render.yaml`
5. Deploy staging environment
6. Validate with real traffic
7. Set up monitoring (Sentry)
8. Go live

---

*This document should be updated as the system evolves and deployment requirements change.*
