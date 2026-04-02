"""
Step 2: Summarise articles using Azure OpenAI (GPT-4o mini).
Reads articles.json, adds AI summaries, outputs summaries.json.

Uses BATCH mode — sends multiple articles per API call for efficiency.
Authenticates via Azure AD token (no API keys needed).
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from openai import AzureOpenAI


SCRIPT_DIR = Path(__file__).parent
INPUT_FILE = SCRIPT_DIR / ".." / "site" / "articles.json"
OUTPUT_FILE = SCRIPT_DIR / ".." / "site" / "summaries.json"

# Azure OpenAI configuration
AZURE_ENDPOINT = os.environ.get("AZURE_OPENAI_ENDPOINT", "https://ainews-openai.openai.azure.com/")
AZURE_TOKEN = os.environ.get("AZURE_OPENAI_TOKEN", "")
DEPLOYMENT = "gpt-4o-mini"
API_VERSION = "2024-10-21"

BATCH_SIZE = 10  # Articles per API call

SYSTEM_PROMPT = """You are an AI news summariser and curator. You will receive multiple articles.

For EACH article, produce:

1. **summary** — A concise 2-3 sentence summary (under 80 words). State what happened, explain significance. Use plain English.
2. **why_it_matters** — A single punchy sentence (under 25 words) explaining why this matters to someone following AI/tech. Start with a verb or impact word.
3. **tier** — Classify the article into one of three tiers:
   - "headline" — Major breaking news, big product launches, significant funding rounds, industry-shaking announcements. Only 3-5 articles per batch should be headlines.
   - "deep_dive" — Interesting analysis, detailed coverage, noteworthy developments worth reading in full.
   - "quick" — Minor updates, routine announcements, niche topics that are good to know but don't need deep attention.

Be factual and neutral. Aim for roughly 20% headlines, 50% deep_dive, 30% quick.

Return your response as a JSON array of objects, one per article, in the SAME order as the input.
Each object must have: {"index": <number>, "summary": "<text>", "why_it_matters": "<text>", "tier": "<headline|deep_dive|quick>"}
Return ONLY the JSON array, no other text."""


def summarise_batch(client, batch):
    """Summarise a batch of articles in a single API call."""
    articles_text = ""
    for i, (idx, title, snippet) in enumerate(batch):
        articles_text += f"\n---\nArticle {i}:\nTitle: {title}\nContent: {snippet[:500]}\n"

    try:
        response = client.chat.completions.create(
            model=DEPLOYMENT,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Summarise these {len(batch)} articles:\n{articles_text}"},
            ],
            max_tokens=300 * len(batch),
            temperature=0.3,
        )
        raw = response.choices[0].message.content.strip()
        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()
        return json.loads(raw)
    except json.JSONDecodeError:
        print(f"    ⚠️  JSON parse failed, retrying one-by-one")
        return None
    except Exception as e:
        print(f"    ❌ Batch failed: {e}")
        return None


def summarise_single(client, title, snippet):
    """Fallback: summarise one article at a time. Returns dict with summary, why_it_matters, tier."""
    try:
        response = client.chat.completions.create(
            model=DEPLOYMENT,
            messages=[
                {"role": "system", "content": "You are an AI news summariser. Return a JSON object with: {\"summary\": \"2-3 sentence summary under 80 words\", \"why_it_matters\": \"single punchy sentence under 25 words\", \"tier\": \"headline|deep_dive|quick\"}. Return ONLY the JSON object."},
                {"role": "user", "content": f"Title: {title}\nContent: {snippet[:500]}\n\nSummarise and classify this article."},
            ],
            max_tokens=250,
            temperature=0.3,
        )
        raw = response.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()
        return json.loads(raw)
    except (json.JSONDecodeError, Exception) as e:
        print(f"    ❌ Summary failed: {e}")
        return {"summary": "", "why_it_matters": "", "tier": "quick"}


def main():
    print("🤖 AI News Summariser (Azure OpenAI — GPT-4o mini)")
    print("=" * 60)

    if not AZURE_TOKEN:
        print("❌ AZURE_OPENAI_TOKEN not set.")
        print("   Run: az account get-access-token --resource https://cognitiveservices.azure.com --query accessToken -o tsv")
        sys.exit(1)

    if not INPUT_FILE.exists():
        print(f"❌ No articles found at {INPUT_FILE}")
        print("   Run fetch_news.py first.")
        sys.exit(1)

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        articles = json.load(f)

    print(f"📰 {len(articles)} articles to summarise")
    print(f"📦 Batch size: {BATCH_SIZE}")
    print(f"🔗 Endpoint: {AZURE_ENDPOINT}")
    print()

    # Azure OpenAI client with AD token auth
    client = AzureOpenAI(
        azure_endpoint=AZURE_ENDPOINT,
        api_key=AZURE_TOKEN,
        api_version=API_VERSION,
    )

    # Build list of articles that need summarising
    to_summarise = []
    for i, article in enumerate(articles):
        title = article.get("title", "")
        snippet = article.get("snippet", "")
        if title or snippet:
            to_summarise.append((i, title, snippet))

    # Process in batches
    summarised = 0
    api_calls = 0
    for batch_start in range(0, len(to_summarise), BATCH_SIZE):
        batch = to_summarise[batch_start:batch_start + BATCH_SIZE]
        batch_num = (batch_start // BATCH_SIZE) + 1
        total_batches = (len(to_summarise) + BATCH_SIZE - 1) // BATCH_SIZE
        print(f"  📦 Batch {batch_num}/{total_batches} ({len(batch)} articles)...", end=" ")

        results = summarise_batch(client, batch)
        api_calls += 1

        if results and isinstance(results, list):
            for j, item in enumerate(results):
                summary = item.get("summary", "") if isinstance(item, dict) else ""
                if summary and j < len(batch):
                    orig_idx = batch[j][0]
                    articles[orig_idx]["ai_summary"] = summary
                    articles[orig_idx]["why_it_matters"] = item.get("why_it_matters", "")
                    articles[orig_idx]["tier"] = item.get("tier", "deep_dive")
                    summarised += 1
            print(f"✅ ({len(results)} summaries)")
        else:
            # Fallback: summarise individually
            print("⚠️  falling back to individual mode")
            for idx, title, snippet in batch:
                result = summarise_single(client, title, snippet)
                api_calls += 1
                if isinstance(result, dict) and result.get("summary"):
                    articles[idx]["ai_summary"] = result["summary"]
                    articles[idx]["why_it_matters"] = result.get("why_it_matters", "")
                    articles[idx]["tier"] = result.get("tier", "deep_dive")
                    summarised += 1
                time.sleep(0.5)

        time.sleep(1)

    skipped = len(articles) - summarised

    # Wrap in an object with metadata for the frontend
    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_articles": len(articles),
        "summarised": summarised,
        "articles": articles,
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print()
    print(f"✅ Done: {summarised} summarised, {skipped} skipped")
    print(f"   🔄 API calls used: {api_calls}")
    print(f"   Saved to: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
