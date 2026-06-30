import os
import json
import re
import httpx
import yaml
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from google import genai
from google.genai.types import Tool, GoogleSearch, UrlContext, GenerateContentConfig
from dotenv import load_dotenv

load_dotenv()

SEEN_URLS_RETENTION_DAYS = 10
GEMINI_MODEL = "gemini-3.5-flash"

# ── Load profile and seen URLs ────────────────────────────────────────────────

ARXIV_ID_RE = re.compile(r"(\d{4}\.\d{4,5})(v\d+)?")

def normalize_url(url: str) -> str:
    """Canonicalize a URL so the same paper matches across runs regardless of
    arXiv version suffix, trailing slash, query string, scheme, or whether it
    was cited via arxiv.org or huggingface.co/papers."""
    url = url.strip().rstrip("/")
    url = re.sub(r"^https?://", "", url, flags=re.IGNORECASE)
    url = re.sub(r"^www\.", "", url, flags=re.IGNORECASE)
    url = url.split("?")[0].split("#")[0]
    url = url.lower()

    # arXiv and HF-papers URLs both encode an arXiv ID — dedup on that ID
    # alone so the same paper matches regardless of which domain cited it.
    if "arxiv.org" in url or "huggingface.co/papers" in url:
        match = ARXIV_ID_RE.search(url)
        if match:
            return f"arxiv:{match.group(1)}"

    return re.sub(r"v\d+$", "", url)  # strip trailing version suffix (e.g. repo paths)

def load_profile() -> dict:
    with open("goal_profile.yaml") as f:
        return yaml.safe_load(f)

def _read_seen_entries() -> list[tuple[str, date]]:
    """Read (url, seen_date) pairs, tolerating legacy lines with no date."""
    entries = []
    try:
        with open("seen_urls.txt") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                if "|" in line:
                    url, date_str = line.rsplit("|", 1)
                    try:
                        seen_date = datetime.strptime(date_str, "%Y-%m-%d").date()
                    except ValueError:
                        url, seen_date = line, date.today()
                else:
                    url, seen_date = line, date.today()
                entries.append((normalize_url(url), seen_date))
    except FileNotFoundError:
        pass
    return entries

def load_seen_urls() -> set:
    """Return URLs seen within the retention window, pruning older entries
    from disk as a side effect so seen_urls.txt doesn't grow forever."""
    cutoff = date.today() - timedelta(days=SEEN_URLS_RETENTION_DAYS)
    entries = _read_seen_entries()
    fresh = [(url, seen_date) for url, seen_date in entries if seen_date >= cutoff]

    with open("seen_urls.txt", "w") as f:
        for url, seen_date in fresh:
            f.write(f"{url}|{seen_date.isoformat()}\n")

    return set(url for url, _ in fresh)

def save_seen_urls(urls: set):
    today_str = date.today().isoformat()
    with open("seen_urls.txt", "a") as f:
        for url in urls:
            f.write(f"{normalize_url(url)}|{today_str}\n")

# ── HuggingFace daily papers (pre-fetched via API) ────────────────────────────
#
# huggingface.co/papers is a JS-rendered page that Gemini's search-based tools
# can't reliably scrape (search returns stale/empty snippets, not the live
# top-30-by-upvote list). HF exposes the same data through a public,
# unauthenticated JSON endpoint, so we fetch it server-side and inject the
# result directly into the prompt instead of asking the model to search for it.

def fetch_hf_daily_papers(limit: int = 30) -> list[dict]:
    today = date.today()
    is_saturday = today.weekday() == 5
    days_back = 7 if is_saturday else 2  # 2 days: HF often lags a day behind

    papers_by_id = {}
    for offset in range(days_back):
        day = today - timedelta(days=offset)
        try:
            resp = httpx.get(
                "https://huggingface.co/api/daily_papers",
                params={"date": day.isoformat()},
                timeout=10,
            )
            resp.raise_for_status()
            for item in resp.json():
                p = item.get("paper", {})
                pid = p.get("id")
                if pid and pid not in papers_by_id:
                    papers_by_id[pid] = {
                        "id": pid,
                        "title": (p.get("title") or "").strip(),
                        "upvotes": p.get("upvotes", 0),
                        "published": (p.get("publishedAt") or "")[:10],
                        "summary": (p.get("summary") or "").strip().replace("\n", " ")[:300],
                    }
        except Exception:
            continue  # best-effort — a failed day shouldn't break the run

    ranked = sorted(papers_by_id.values(), key=lambda x: x["upvotes"], reverse=True)
    return ranked[:limit]

def format_hf_papers(papers: list[dict]) -> str:
    if not papers:
        return "(no data retrieved from the HuggingFace daily papers API today)"
    lines = []
    for p in papers:
        lines.append(
            f"- \"{p['title']}\" — arXiv:{p['id']} — {p['upvotes']} upvotes — "
            f"published {p['published']} — https://arxiv.org/abs/{p['id']} — "
            f"{p['summary']}"
        )
    return "\n".join(lines)

# ── arXiv cs.MA listing (pre-fetched via the official arXiv API) ──────────────
#
# The cs.MA listing page is static HTML and was already scrapable via search,
# but arXiv's own API (export.arxiv.org/api/query) returns the same data as
# structured Atom XML with no scraping/interpretation risk, so we use it.

def fetch_arxiv_cs_ma(limit: int = 50) -> list[dict]:
    try:
        resp = httpx.get(
            "https://export.arxiv.org/api/query",
            params={
                "search_query": "cat:cs.MA",
                "sortBy": "submittedDate",
                "sortOrder": "descending",
                "max_results": limit,
            },
            timeout=15,
            follow_redirects=True,
        )
        resp.raise_for_status()
    except Exception:
        return []

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    try:
        root = ET.fromstring(resp.text)
    except ET.ParseError:
        return []

    papers = []
    for entry in root.findall("atom:entry", ns):
        raw_id = entry.findtext("atom:id", default="", namespaces=ns)
        arxiv_id = re.sub(r"v\d+$", "", raw_id.rsplit("/", 1)[-1]) if raw_id else ""
        title = (entry.findtext("atom:title", default="", namespaces=ns) or "").strip().replace("\n", " ")
        summary = (entry.findtext("atom:summary", default="", namespaces=ns) or "").strip().replace("\n", " ")[:300]
        published = (entry.findtext("atom:published", default="", namespaces=ns) or "")[:10]
        if arxiv_id:
            papers.append({"id": arxiv_id, "title": title, "published": published, "summary": summary})
    return papers

def format_arxiv_papers(papers: list[dict]) -> str:
    if not papers:
        return "(no data retrieved from the arXiv API today)"
    lines = []
    for p in papers:
        lines.append(
            f"- \"{p['title']}\" — arXiv:{p['id']} — published {p['published']} — "
            f"https://arxiv.org/abs/{p['id']} — {p['summary']}"
        )
    return "\n".join(lines)

# ── Lab blog RSS feeds (pre-fetched, deterministic freshness filtering) ──────
#
# Where a lab publishes an official RSS/Atom feed, parsing it directly is
# more reliable than asking the model to search and judge freshness itself.

def fetch_rss_items(feed_url: str, days_back: int) -> list[dict]:
    try:
        resp = httpx.get(feed_url, timeout=15, follow_redirects=True)
        resp.raise_for_status()
        root = ET.fromstring(resp.text)
    except Exception:
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    items = []
    for item in root.findall(".//item"):  # RSS 2.0
        pub_date_str = item.findtext("pubDate") or ""
        try:
            pub_date = parsedate_to_datetime(pub_date_str)
            if pub_date.tzinfo is None:
                pub_date = pub_date.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue
        if pub_date < cutoff:
            continue
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        description = re.sub(r"<[^>]+>", "", item.findtext("description") or "").strip()[:300]
        items.append({
            "title": title,
            "link": link,
            "published": pub_date.date().isoformat(),
            "summary": description,
        })
    return items

def format_blog_items(label: str, items: list[dict]) -> str:
    if not items:
        return f"{label}: no new posts today"
    lines = [f"{label}:"]
    for it in items:
        lines.append(f"  - \"{it['title']}\" — {it['published']} — {it['link']} — {it['summary']}")
    return "\n".join(lines)

# ── Source list builder ───────────────────────────────────────────────────────

def build_sources() -> str:
    today = date.today()
    is_saturday = today.weekday() == 5

    gh_since = "weekly" if is_saturday else "daily"

    return f"""
Tools & releases:
- github.com/trending?since={gh_since} — first page, all languages

Lab blogs (include only posts from last {"7 days" if is_saturday else "24 hours"}):
- anthropic.com/research
- news.microsoft.com/source/topics/ai (formerly blogs.microsoft.com/ai, which now redirects here)
- ai.meta.com/research
Note: if a lab blog has no new posts, write "[blog name]: no new posts today"
""".strip()

# ── System prompt ─────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a personal AI research agent for an AI Engineer.

Today's date: {date}

Goal profile:
{profile}

Already seen URLs (do not include these in the briefing):
{seen_urls}

Pre-fetched data (fetched server-side via official APIs/feeds — do not
search for these yourself, use this data as-is as Pass 1 candidates):

HuggingFace daily papers (top upvoted):
{hf_papers}

arXiv cs.MA recent submissions:
{arxiv_papers}

OpenAI blog (already filtered to the freshness window):
{openai_blog}

DeepMind blog (already filtered to the freshness window):
{deepmind_blog}

Run the following 4-pass loop:

---

PASS 1 — COLLECT
For the pre-fetched data above, use it as-is — do not search for those
sources again. Use the google_search tool only for the remaining required
sources listed below. For each item collect: title, url, source domain,
date published, one-line description. Do not score or filter yet. Goal is
coverage.

Remaining required sources (use google_search for these):
{sources}

Freshness rules:
- Lab blogs fetched via google_search: discard posts older than 24h (or 7
  days on Saturday). Note "[blog]: no new posts today" if nothing qualifies.
- The pre-fetched OpenAI/DeepMind blog data above is already freshness-
  filtered — if it says "no new posts today", report that as-is.
- HuggingFace, cs.MA, GitHub: no date filter needed.

---

PASS 2 — EVALUATE (shallow, from snippets only)
Score each candidate 0–10 against the goal profile using listing
descriptions only — do not fetch full content yet.
Assign tier: must_read / worth_knowing / drop.

Scoring rules:
- Score current_problems matches highest
- Score interests matches second
- Anything in ignore list: score 0, drop immediately
- Anything not from required domains: drop
- Lab blog posts from last 24h: always include regardless of score
- Any URL in the seen list: drop immediately. Compare URLs canonically —
  ignore scheme (http/https), "www.", trailing slashes, query strings,
  and arXiv version suffixes (e.g. treat 2606.08162 and 2606.08162v2 as
  the same URL as 2606.08162 in the seen list)

Self-check before Pass 3:
- Have I found at least one item per current problem?
- If not: run one targeted web search to fill the gap.

Output: shortlist of 8–12 non-dropped items with preliminary tiers.

---

PASS 3 — DEEP READ
Use the url_context tool to fetch and read full content for each
shortlisted item:
- arXiv / HF paper → fetch arxiv.org/abs/[id] (no version suffix), read abstract + conclusion
- Lab blog post → fetch full page, read entire post
- GitHub repo → fetch repo page (github.com/[owner]/[repo], no query params), read README first 500 words

Always record URLs in their canonical stable form (strip version suffixes,
query strings, and trailing slashes) so the same item maps to the same URL
across daily runs.

Re-score after reading. Tier may change based on actual content.
Update relevance_score and tier accordingly.

This pass is what grounds Details, Impact, and For you in real content.

---

PASS 4 — SYNTHESISE
Rank all non-dropped items by updated relevance score globally.
Do not guarantee items from any one source.

Apply tier caps (do not pad to hit caps — quality over quantity):
- must_read: max 3
- worth_knowing: max 3

Drop everything that doesn't make either tier — there is no fyi tier.
Briefings should be short; do not include marginal items just for coverage.

Group entries under two section headings, in this exact order, and omit
any section that has zero qualifying items:
## 🔴 MUST READ
## 🟡 WORTH KNOWING

Write each entry using content from Pass 3. The header line always includes
source domain, popularity (trending rank, upvote count, GitHub star count,
or citation count — whichever applies to that source), date, and the
canonical referenced link.

must_read format (3 fields):
**[Title]**
`[source domain] · [popularity] · [date] · [referenced link]`
**Summary:** [one sentence — what it is]
**Details:** [one sentences — the specific finding, method, number, or impact]
**For you:** [one sentence — what you should do or think differently about]

worth_knowing format (3 fields):
**[Title]**
`[source domain] · [popularity] · [date] · [referenced link]`
**Summary:** [one sentence]
**For you:** [one sentence]

After all entries:
- If 2+ items share a concrete theme: write a section headed exactly
  "## 🔗 Today's Theme" followed by at most two sentences naming the
  theme and what it means. Otherwise omit the section entirely.
  Never exceed two sentences.

Before finalizing, silently verify internally that every required source
was checked (or noted as having nothing new) — this is for your own
self-validation only. Do NOT print a "Sources checked" line or any list of
sources in the output; the user does not want to see this.

End with exactly this line, starting with the literal label shown (do not
omit or rename the label — code parses it):
Relevant URLs: [JSON array of every URL included in the briefing, for dedup]

The "Relevant URLs:" label must appear as literal text immediately before
the JSON array — do not print the array in a code block with no label.

---

OUTPUT RULES
- Return only the formatted briefing. No preamble, no meta-commentary.
- Do not include items from the seen URLs list.
- Always include the two section headings (## 🔴 MUST READ, ## 🟡 WORTH KNOWING), skipping only the ones with zero items.
- Do not invent content — if a source had nothing relevant, skip it.
- Do not print a "Sources checked" section in the output.
- The final line must be the Relevant URLs JSON array.
"""

# ── Main agent function ───────────────────────────────────────────────────────

def run_agent() -> str:
    profile = load_profile()
    seen_urls = load_seen_urls()
    client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

    today = date.today()
    is_saturday = today.weekday() == 5
    blog_days_back = 7 if is_saturday else 1

    hf_papers = format_hf_papers(fetch_hf_daily_papers())
    arxiv_papers = format_arxiv_papers(fetch_arxiv_cs_ma())
    openai_blog = format_blog_items(
        "openai.com/research", fetch_rss_items("https://openai.com/news/rss.xml", blog_days_back)
    )
    deepmind_blog = format_blog_items(
        "deepmind.google/research", fetch_rss_items("https://deepmind.google/blog/rss.xml", blog_days_back)
    )

    prompt = SYSTEM_PROMPT.format(
        date=today.strftime("%A, %B %d, %Y"),
        profile=yaml.dump(profile, allow_unicode=True),
        seen_urls="\n".join(seen_urls) if seen_urls else "none",
        hf_papers=hf_papers,
        arxiv_papers=arxiv_papers,
        openai_blog=openai_blog,
        deepmind_blog=deepmind_blog,
        sources=build_sources()
    )

    print(f"[{datetime.now().strftime('%H:%M:%S')}] Running agent...")

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=GenerateContentConfig(
            max_output_tokens=20000,
            tools=[
                Tool(google_search=GoogleSearch()),
                Tool(url_context=UrlContext()),
            ],
        ),
    )

    full_text = response.text or ""

    # Extract and save new URLs for dedup
    try:
        marker_idx = full_text.rindex("Relevant URLs:")
        tail = full_text[marker_idx + len("Relevant URLs:"):]
        array_start = tail.index("[")
        array_end = tail.rindex("]")
        json_str = tail[array_start:array_end + 1]
        new_urls = set(json.loads(json_str))
        save_seen_urls(new_urls)
        # Remove the URL section from the output before delivering
        full_text = full_text[:marker_idx].strip()
    except Exception:
        pass  # Dedup is best-effort — don't let it break delivery

    print(f"[{datetime.now().strftime('%H:%M:%S')}] Agent complete.")
    return full_text


if __name__ == "__main__":
    print(run_agent())
