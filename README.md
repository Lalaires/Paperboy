# Daily AI Research Briefing Agent

A personal AI research agent that runs daily, scans curated sources for relevant AI developments, and delivers a tiered briefing to Discord — automatically, every morning.

---

## How It Works

The agent runs a 4-pass loop each day:

1. **Collect** — Pre-fetches papers from HuggingFace and arXiv cs.MA via their official APIs, pulls OpenAI and DeepMind blog posts from RSS, then uses Gemini's Google Search tool to scan GitHub Trending, Anthropic research, Meta AI, and Microsoft AI news.
2. **Evaluate** — Scores each candidate 0–10 against your goal profile using listing snippets only. Assigns preliminary tiers (`must_read` / `worth_knowing` / `drop`).
3. **Deep Read** — Fetches full content for shortlisted items using Gemini's URL Context tool. Re-scores based on actual content.
4. **Synthesise** — Ranks all non-dropped items globally, applies tier caps, and produces the final briefing.

The output is delivered to Discord via webhook in chunked messages.

---

## Output Format

```
## 🔴 MUST READ

**[Title]**
`[source domain] · [popularity] · [date] · [url]`
**Summary:** one sentence — what it is
**Details:** one sentence — the specific finding or method
**For you:** one sentence — what to do or think differently about

## 🟡 WORTH KNOWING

**[Title]**
`[source domain] · [popularity] · [date] · [url]`
**Summary:** one sentence
**For you:** one sentence

## 🔗 Today's Theme

[One or two sentences on a concrete theme connecting 2+ items, if one exists.]
```

Tier caps: max 3 must_read, max 3 worth_knowing. No filler — marginal items are dropped entirely.

---

## Sources

| Source | Method |
|---|---|
| HuggingFace daily papers | HF public API — top 40 by upvotes |
| arXiv cs.MA | arXiv Atom API — 20 most recent |
| OpenAI blog | RSS feed |
| DeepMind blog | RSS feed |
| GitHub Trending | Gemini Google Search |
| Anthropic research | Gemini Google Search |
| Meta AI research | Gemini Google Search |
| Microsoft AI news | Gemini Google Search |

---

## Deduplication

Seen URLs are tracked in `seen_urls.txt` (committed back to the repo after each run). Entries expire after 10 days. arXiv papers are deduplicated by paper ID so the same paper is never included twice regardless of whether it was cited via `arxiv.org` or `huggingface.co/papers`.

---

## Setup

### 1. Clone and install dependencies

```bash
git clone https://github.com/Lalaires/Daily-AI-brief-agent.git
cd Daily-AI-brief-agent
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Fill in your keys:
# GEMINI_API_KEY=...
# DISCORD_WEBHOOK_URL=...
```

> **Note:** Gemini's Google Search and URL Context tools require a billing-enabled Google Cloud project, even within the free quota.

### 3. Customize your goal profile

Edit `goal_profile.yaml` to match your role and interests. The agent scores all candidates against this profile.

```yaml
role: "AI Engineer"
current_problems:
  - "Building end-to-end agentic systems"
  - "Implementable innovative AI ideas"
interests:
  - "Cutting-edge machine learning models"
  - "Tool use"
  - "Multimodal AI"
  - "LLM"
  - "Multi-agent systems"
```

### 4. Run manually

```bash
python run_now.py
```

---

## Automated Deployment (GitHub Actions)

The workflow at `.github/workflows/daily.yml` runs every day at **6:00 AM Asia/Taipei** (22:00 UTC previous day).

Required repository secrets:
- `GEMINI_API_KEY`
- `DISCORD_WEBHOOK_URL`

After each run, the workflow commits `seen_urls.txt` back to the repo with `[skip ci]` to persist deduplication state across runs.

To trigger a run manually: Actions → Daily Research Briefing → Run workflow.

---

## Project Structure

```
agent.py          # 4-pass agent loop, pre-fetch functions, dedup logic
deliver.py        # Discord webhook delivery with chunking
run_now.py        # Entry point: run agent then deliver
scheduler.py      # Local scheduler (alternative to GitHub Actions)
goal_profile.yaml # Your role, problems, and interests
seen_urls.txt     # Dedup state (auto-managed, committed by CI)
requirements.txt
.github/
  workflows/
    daily.yml     # GitHub Actions cron workflow
```

---

## Model

Runs on `gemini-3.5-flash` with `google_search` and `url_context` tools enabled.
