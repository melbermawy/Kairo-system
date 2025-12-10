# Kairo Backend

AI-native content copilot for brands and content teams.

This repo contains the **backend system** (Django + PostgreSQL + future LLM orchestration).

## Quick Start

### Prerequisites

- Docker and Docker Compose
- Python 3.11+ (for local development without Docker)

### Using Docker (Recommended)

```bash
# Start all services (postgres + django)
docker-compose up

# Or run in detached mode
docker-compose up -d

# View logs
docker-compose logs -f web

# Stop all services
docker-compose down
```

The API will be available at `http://localhost:8000`.

### Local Development (without Docker)

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -e ".[dev]"

# Set up environment variables
cp .env.example .env
# Edit .env with your DATABASE_URL (requires local postgres)

# Run migrations
python manage.py migrate

# Start the development server
python manage.py runserver
```

### Running Tests

```bash
# With Docker
docker-compose exec web pytest

# Local (uses sqlite in-memory)
pytest
```

## Project Structure

```
kairo/                  # Django project
  settings.py           # App configuration (env-driven)
  urls.py               # URL routing
  hero/                 # Hero loop app (today board, packages, variants)
    views.py            # API endpoints
    urls.py             # App routes

tests/                  # Pytest test suite
  test_healthcheck.py   # Basic smoke tests

docs/                   # Documentation
  prd/                  # Product requirements
  technical/            # Architecture docs
  engines/              # Engine specifications
```

## Documentation

- [docs/README.md](docs/README.md) - Documentation index
- [docs/prd/kairo-v1-prd.md](docs/prd/kairo-v1-prd.md) - PRD for v1 hero loop
- [docs/prd/PR-map-and-standards](docs/prd/PR-map-and-standards) - PR roadmap
- [docs/technical/](docs/technical/) - Technical architecture

## Environment Variables

See [.env.example](.env.example) for all available configuration options.

Key variables:
- `DJANGO_SECRET_KEY` - Django secret key (required in production)
- `DATABASE_URL` - PostgreSQL connection string
- `DJANGO_DEBUG` - Debug mode (True/False)
- `LLM_DISABLED` - Kill switch for LLM calls (True for tests/dev)

## API Endpoints

### Health Check

```
GET /health/
```

Returns `{"status": "ok", "service": "kairo-backend"}`.

---

**Status:** PR-0 (repo + env spine) complete. No business logic yet.
