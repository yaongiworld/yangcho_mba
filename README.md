# LLC — The Logic of Life-Care

Yangcho's MBA portfolio: a daily-updating AI dashboard that translates K-Beauty into American mainstream lifestyle science.

See [`CLAUDE.md`](CLAUDE.md) for project context and the active design doc at `~/.gstack/projects/yaongiworld/tony-unknown-design-20260509-024916.md` for the architecture.

## Layout

```
llc/
├── pipeline/              # Python pipeline (uv-managed, Python 3.14)
│   ├── ingestion/         # cultural calendar + TikTok scraper
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

### Required environment variables

Pipeline `.env` (NOT committed; pipeline-side only):

```bash
ANTHROPIC_API_KEY=sk-ant-...      # friction analysis, scoring, marketing posts
GEMINI_API_KEY=...                # vision OCR for product catalog (Flash 2.5)
SUPABASE_URL=https://<ref>.supabase.co
SUPABASE_SECRET_KEY=sb_secret_... # bypasses RLS; never ship to client
```

Why two LLM providers: Claude handles reasoning (the moat), Gemini Flash 2.5 handles vision-OCR for product catalog images. Right tool for each job, ~10x cheaper for the OCR work.

### Dashboard

See [`dashboard/README.md`](dashboard/README.md). Requires `npm install` + a Supabase project. Not done yet.

## Conventions

- **Atomic conventional commits.** One logical change per commit.
- **Python 3.14 only.** Pinned via `.python-version`. uv picks it up automatically.
- **No proprietary data.** Public sources only. The hook enforces this at commit-time.
