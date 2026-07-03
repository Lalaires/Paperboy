# Paperboy: Daily AI Briefing Agent

Most AI news aggregators are generic. This agent is personal, it knows your role, your current problems, and what you want to ignore. Instead of skimming 10 tabs every morning, you get a focused briefing in Discord with exactly what matters to you, grounded in full paper and post content rather than headlines.

Built on the principle of loop engineering, rather than prompting an AI agent every morning, you design the system that does it. The trigger, the goal, and the termination condition are all defined once, the agent runs itself.

**Outcome:** a daily Discord message with 3–6 curated items, each with a summary, key finding, and a "what to do with this" line, plus a synthesis of any cross-cutting theme. Runs fully automatically, costs a few cents per day.

---

## How It Works

The agent runs a 4-pass loop each day:

1. **Collect:** Pre-fetches papers from HuggingFace and arXiv cs.MA via their official APIs, pulls OpenAI and DeepMind blog posts from RSS, then uses Gemini's Google Search tool to scan GitHub Trending, Anthropic research, Meta AI, and Microsoft AI news.
2. **Evaluate:** Scores each candidate 0–10 against your goal profile using listing snippets only. Assigns preliminary tiers (`must_read` / `worth_knowing` / `drop`).
3. **Deep Read:** Fetches full content for shortlisted items using Gemini's URL Context tool. Re-scores based on actual content.
4. **Synthesise:** Ranks all non-dropped items globally, applies tier caps, and produces the final briefing.

The output is delivered to Discord via webhook in chunked messages.

---

## Output Format

```
## 🔴 MUST READ

**[Title]**
`[source domain] · [popularity] · [date] · [url]`
**Summary:** one sentence: what it is
**Details:** one sentence: the specific finding or method
**For you:** one sentence: what to do or think differently about

## 🟡 WORTH KNOWING

**[Title]**
`[source domain] · [popularity] · [date] · [url]`
**Summary:** one sentence
**For you:** one sentence

## 🔗 Today's Theme

[One or two sentences on a concrete theme connecting 2+ items, if one exists.]
```

Tier caps: max 3 must_read, max 3 worth_knowing. No filler, marginal items are dropped entirely.

---

## Sources

| Source | Method |
|---|---|
| HuggingFace daily papers | HF public API, top 40 by upvotes |
| arXiv cs.MA | arXiv Atom API, 20 most recent |
| OpenAI blog | RSS feed |
| DeepMind blog | RSS feed |
| GitHub Trending | Gemini Google Search |
| Anthropic research | Gemini Google Search |
| Meta AI research | Gemini Google Search |
| Microsoft AI news | Gemini Google Search |

> On Saturdays, the agent automatically widens its window. HuggingFace papers look back 7 days, GitHub Trending switches to weekly, and blog posts cover the past 7 days instead of 24 hours. This catches anything that may have been missed or published later in the week.

---

## Deduplication

Seen URLs are tracked in `seen_urls.txt` (committed back to the repo after each run). Entries expire after 10 days. arXiv papers are deduplicated by paper ID so the same paper is never included twice regardless of whether it was cited via `arxiv.org` or `huggingface.co/papers`.

---

## Setup

### 1. Clone and install dependencies

```bash
git clone https://github.com/Lalaires/paperboy.git
cd paperboy
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment

Create a `.env` file in the project root:

```bash
GEMINI_API_KEY=your_key_here
DISCORD_WEBHOOK_URL=your_webhook_url_here
```

> **Cost:** Gemini's Google Search and URL Context tools require a billing-enabled Google Cloud project. At typical usage the agent costs a few cents per run. The GitHub Actions workflow itself is free.

### 3. Customize your goal profile

Edit `goal_profile.yaml` — this is the core personalization. The agent scores every candidate against your `current_problems` and `interests`, and drops anything in the `ignore` list before even evaluating it.

```yaml
role: "AI Engineer"

current_problems:
  - "Building end-to-end agentic systems"
  - "Innovative AI ideas"

interests:
  - "Cutting-edge machine learning models"
  - "Tool use"
  - "Multimodal AI"
  - "LLM"
  - "Multi-agent systems"

ignore:
  - "Autonomous vehicles"
  - "Gaming AI"

delivery_time: "06:00"
timezone: "Asia/Taipei"
```

### 4. Run once manually

```bash
python run_now.py
```

`seen_urls.txt` doesn't exist on a fresh clone, the agent creates it automatically on the first run.

### 5. Run on a local schedule

If you prefer to run the agent on your own machine instead of GitHub Actions, use the included scheduler:

```bash
python scheduler.py
```

It reads `delivery_time` and `timezone` from `goal_profile.yaml` and runs the full pipeline at that time every day. Keep the process running (e.g. in a tmux session or as a system service). Press `Ctrl+C` to stop.

---

## Automated Deployment (GitHub Actions)

The workflow at `.github/workflows/daily.yml` runs every day at **6:00 AM Asia/Taipei** (22:00 UTC previous day).

Required repository secrets:
- `GEMINI_API_KEY`
- `DISCORD_WEBHOOK_URL`

After each run, the workflow commits `seen_urls.txt` back to the repo with `[skip ci]` to persist deduplication state across runs.

To trigger a run manually: Actions → Daily Research Briefing → Run workflow.

> **GitHub Actions cron delay:** GitHub's scheduled workflows can fire anywhere from a few minutes to a few hours late under high load, especially on the free tier. If exact delivery time matters, set your cron earlier than needed, or use `scheduler.py` locally for precise timing.

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
