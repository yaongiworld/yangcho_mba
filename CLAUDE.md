# yangcho_mba

Personal project supporting **Yangcho's** MBA application to US programs. Lives inside the Yaongiworld workspace; the root [`../CLAUDE.md`](../CLAUDE.md) sets the broader philosophy ("yaongis are yaongis", two-user scale, privacy-first, durable tech).

## What this project is

Two parallel tracks:

1. **Application strategy** — recommendation plan, essay framing, resume phrasing, CEP narrative. See [`MBA_Preparation_Strategy_Candle.md`](MBA_Preparation_Strategy_Candle.md). Bilingual (KO/EN), Korean-first.
2. **Portfolio project: White Space Miner** — an AI-powered tool that mines US consumer complaint data to surface K-Beauty formulation gaps and auto-generates product concept briefs. Full design in [`design.md`](design.md).
   - The killer feature is the **formulation science translation layer**: sentiment → formulation root cause → K-Beauty solution → product brief. The moat is Yangcho's R&D chemistry expertise encoded as a curated knowledge base.
   - Stack: Python, Streamlit, Claude/GPT API, SQLite. Hosted on Streamlit Cloud (free tier).

## People & roles

- **Yangcho** — product owner, R&D/formulation expertise, owns the formulation knowledge base, reviews all auto-generated briefs.
- **Towee** (Tony) — CTO, owns engineering execution. Yangcho cannot touch implementation directly without raising suspicion at her employer.

## Operating constraints

- **Secrecy.** Yangcho is preparing applications without her employer's knowledge. **No proprietary company data, formulas, or internal IP** can ever be referenced or stored in this repo. Public sources only (Amazon reviews via Hugging Face, Reddit via PRAW, public social media, public ingredient databases).
- **Timeline.** Core build: 5–6 weekends. Buffer: 2 weekends. All before MBA application deadlines.
- **Budget.** Minimal — Claude/GPT API (~$30–50/mo), Streamlit Cloud free tier, SQLite.
- **Audience.** MBA admissions committees (non-technical reviewers + technical interviewers). Optimize for *quality of insight* over breadth of data. 2–3 hero case studies > feature-complete platform.

## Architecture (planned)

```
Data ingestion (weekly: Amazon Reviews + Reddit/PRAW)
  → Complaint clustering (embeddings + HDBSCAN)
  → Formulation Knowledge Base (RAG, hand-curated 50–80 entries)
  → Auto-Brief Generator (Claude/GPT + RAG, Confidence Score)
  → Streamlit Dashboard (Cluster Explorer, Briefs, Hero Cases, Discovery Timeline)
```

The weekly pipeline runs as cron on a personal machine or GitHub Actions — **not** on Streamlit Cloud. Streamlit Cloud only hosts the dashboard.

## Working principles for this project

- **The knowledge base is the moat, not the dashboard.** Weekend 1 priority. No code before the first 20 entries exist.
- **Human-in-the-loop is mandatory.** Yangcho signs off on every brief before it goes live. ~10–20 min/week review window. No auto-publish.
- **Boring tech, durable choices.** SQLite, JSON knowledge base in Git, Streamlit. Don't reach for vector DBs, Postgres, or k8s — portfolio scale doesn't need them.
- **Bilingual where it matters.** Strategy docs in Korean are fine. Code/UI for the dashboard targets US admissions readers — English-first.
- **Polish the demo, not the platform.** A 2-minute video and 3 hero case studies beat a feature-rich dashboard.
- **No proprietary data, ever.** Reject any suggestion that involves Yangcho's employer's data, internal formulas, or non-public ingredient information.

## Repo layout (current)

- [`design.md`](design.md) — full project design from `/office-hours` (APPROVED, Builder mode)
- [`MBA_Preparation_Strategy_Candle.md`](MBA_Preparation_Strategy_Candle.md) — Korean-language application strategy (recommenders, CEP framing, AI project framing, resume phrasing)
- `CLAUDE.md` — this file
