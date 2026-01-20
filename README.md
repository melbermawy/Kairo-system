# Kairo Backend

AI-native content copilot for brands and content teams.

This repo contains the **backend system** (Django + PostgreSQL + Redis + LLM orchestration).

## Quick Start

### Prerequisites

- Python 3.11+
- PostgreSQL (or use our hosted Supabase instance)
- Redis (for job queue)
- OpenAI API key
- Apify API token (for social media scraping)

### Installation

```bash
# Clone the repo
git clone https://github.com/melbermawy/kairo-backend.git
cd kairo-backend

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -e ".[dev]"

# Create environment file
cp .env.example .env
# Edit .env with your settings (see Environment Variables below)

# Run migrations
python manage.py migrate

# Start the development server
python manage.py runserver
```

The API will be available at `http://localhost:8000`.

### Environment Variables

Create a `.env` file in the root directory:

```bash
# Database (PostgreSQL connection string)
# You can use our shared Supabase instance or your own PostgreSQL
DATABASE_URL=postgresql://user:password@host:port/database

# Django secret key (generate a random string for production)
DJANGO_SECRET_KEY=your-secret-key-here

# OpenAI API key (REQUIRED - get one at https://platform.openai.com/api-keys)
OPENAI_API_KEY=sk-proj-your-key-here

# LLM Models (defaults shown)
KAIRO_LLM_MODEL_FAST=gpt-4o-mini
KAIRO_LLM_MODEL_HEAVY=gpt-4o

# Apify (for social media scraping)
APIFY_TOKEN=apify_api_your-token-here
APIFY_ENABLED=true
APIFY_DAILY_SPEND_CAP_USD=3.00

# SourceActivation mode
# - fixture_only: Use local fixture data (no Apify spend)
# - live_cap_limited: Use Apify with daily spend cap
SOURCEACTIVATION_MODE_DEFAULT=live_cap_limited

# Redis (for job queue)
REDIS_URL=redis://localhost:6379/0
```

## Running the Full Stack

Kairo requires three processes running:

### 1. Django Server (API)

```bash
python manage.py runserver
```

### 2. Redis (Job Queue)

```bash
# macOS
brew services start redis
# Or run directly
redis-server

# Linux
sudo systemctl start redis
# Or run directly
redis-server
```

### 3. Opportunities Worker (Background Jobs)

```bash
python -m kairo.hero.queues.opportunities_worker
```

This worker processes opportunity generation jobs (scraping + synthesis).

## Project Structure

```
kairo/
├── settings.py              # Django settings (env-driven)
├── urls.py                  # URL routing
├── hero/                    # Hero loop app
│   ├── views.py             # API endpoints
│   ├── models/              # Django models
│   ├── engines/             # Business logic
│   ├── graphs/              # LLM pipelines
│   └── queues/              # Job queue workers
├── sourceactivation/        # Social media scraping
│   ├── query_planner.py     # LLM-powered query generation
│   └── recipes/             # Platform-specific scrapers
└── integrations/
    └── apify/               # Apify API client

tests/                       # Pytest test suite
docs/                        # Documentation
```

## Key Features

- **Brand Onboarding**: Create brands with positioning, pillars, and voice
- **Today Board**: AI-generated content opportunities
- **SourceActivation**: Social media scraping from TikTok, Instagram
- **Synthesis Pipeline**: LLM-powered opportunity generation

## API Endpoints

### Health Check
```
GET /health/
```

### Brands
```
POST /api/brands/                        # Create brand
GET  /api/brands/{id}/                   # Get brand
GET  /api/brands/{id}/today/             # Get today board
POST /api/brands/{id}/today/regenerate/  # Regenerate opportunities
```

### Onboarding
```
POST /api/onboarding/session/            # Start onboarding
POST /api/onboarding/step/               # Submit step
POST /api/onboarding/finalize/           # Complete onboarding
```

## Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=kairo

# Run specific test file
pytest tests/test_healthcheck.py
```

## Development Notes

### Using Fixtures (No Apify Spend)

To develop without Apify costs:

```bash
# In .env
SOURCEACTIVATION_MODE_DEFAULT=fixture_only
```

This uses local fixture data instead of live scraping.

### Database

The app writes to the configured PostgreSQL database. For development, you can:
1. Use your own local PostgreSQL
2. Use the shared Supabase instance (contact maintainer for credentials)

## License

MIT
