# LLC — The Logic of Life-Care

Yangcho's MBA portfolio: a daily-updating AI dashboard that translates K-Beauty into American mainstream lifestyle science.

See [`CLAUDE.md`](CLAUDE.md) for project context and the active design doc at `~/.gstack/projects/yaongiworld/tony-unknown-design-20260509-024916.md` for the architecture.

## Layout

```
llc/
├── pipeline/              # Python pipeline (uv-managed, Python 3.14)
│   ├── ingestion/         # Reddit + cultural calendar + TikTok scrapers
│   ├── analysis/          # moments, scoring, friction, product matching
│   ├── playbook/          # influencer + marketing post + new product idea
│   ├── orchestrator/      # daily cron entrypoint
│   ├── queue/             # Yangcho's confidence-gated review queue
│   ├── prompts/           # one .md file per LLM call site
│   ├── scripts/           # dev tools
│   └── tests/             # pytest tests (regression-focused, ~10 total)
├── dashboard/             # Next.js 15 + Tailwind 4 + Supabase
├── supabase/migrations/   # SQL migrations
├── data/                  # cultural calendar, influencer list (curated, public)
├── docs/                  # TikTok spike findings
└── .github/workflows/     # daily-cron.yml
```

## Setup

### Python pipeline (uv)

```bash
# Install uv if you haven't: https://docs.astral.sh/uv/getting-started/installation/
curl -LsSf https://astral.sh/uv/install.sh | sh

# Pin Python 3.14 (uv reads .python-version)
uv python install 3.14

# Sync dependencies into .venv/
uv sync

# Run the orchestrator stub
uv run python -m pipeline.orchestrator.run

# Run tests
uv run pytest

# Run ruff
uv run ruff check pipeline/
```

### Dashboard

See [`dashboard/README.md`](dashboard/README.md). Requires `npm install` + a Supabase project. Not done yet.

## Conventions

- **Atomic conventional commits.** One logical change per commit.
- **Python 3.14 only.** Pinned via `.python-version`. uv picks it up automatically.
- **No proprietary data.** Public sources only. The hook enforces this at commit-time.
