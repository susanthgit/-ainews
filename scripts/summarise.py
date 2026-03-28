"""
Step 2: Summarise articles using GitHub Models (GPT-4o mini).
Reads articles.json, adds AI summaries, outputs summaries.json.

Uses BATCH mode — sends multiple articles per API call to stay
within GitHub Models free-tier rate limit (150 req/day).
"""

import json
import os
import sys
import time
from pathlib import Path

from openai import OpenAI


SCRIPT_DIR = Path(__file__).parent
INPUT_FILE = SCRIPT_DIR / ".." / "site" / "articles.json"
OUTPUT_FILE = SCRIPT_DIR / ".." / "site" / "summaries.json"

# GitHub Models endpoint
GITHUB_MODELS_URL = "https://models.inference.ai.azure.com"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
MODEL = "gpt-4o-mini"

BATCH_SIZE = 10  # Articles per API call (keeps total calls under 150/day)

SYSTEM_PROMPT = """You are an AI news summariser. You will receive multiple articles.
For EACH article, write a concise 2-3 sentence summary that:
1. States what happened or was announced
2. Explains why it matters
3. Uses plain English — avoid jargon

Keep each summary under 80 words. Be factual and neutral.

Return your response as a JSON array of objects, one per article, in the SAME order as the input.
Each object must have: {"index": <number>, "summary": "<text>"}
Return ONLY the JSON array, no other text."""


def summarise_batch(client, batch):
    """Summarise a batch of articles in a single API call."""
    articles_text = ""
    for i, (idx, title, snippet) in enumerate(batch):
        articles_text += f"\n---\nArticle {i}:\nTitle: {title}\nContent: {snippet[:500]}\n"

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"Summarise these {len(batch)} articles:\n{articles_text}"},
            ],
            max_tokens=200 * len(batch),
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
    """Fallback: summarise one article at a time."""
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": "You are an AI news summariser. Write a 2-3 sentence summary under 80 words. Be factual and neutral."},
                {"role": "user", "content": f"Title: {title}\nContent: {snippet[:500]}\n\nWrite a 2-3 sentence summary."},
            ],
            max_tokens=150,
            temperature=0.3,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"    ❌ Summary failed: {e}")
        return ""


def main():
    print("🤖 AI News Summariser (GitHub Models — GPT-4o mini, batch mode)")
    print("=" * 60)

    if not GITHUB_TOKEN:
        print("❌ GITHUB_TOKEN not set. Set it as an environment variable.")
        print("   For local testing: $env:GITHUB_TOKEN = 'your-token'")
        sys.exit(1)

    if not INPUT_FILE.exists():
        print(f"❌ No articles found at {INPUT_FILE}")
        print("   Run fetch_news.py first.")
        sys.exit(1)

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        articles = json.load(f)

    print(f"📰 {len(articles)} articles to summarise")
    print(f"📦 Batch size: {BATCH_SIZE} → ~{(len(articles) // BATCH_SIZE) + 1} API calls")
    print()

    client = OpenAI(
        base_url=GITHUB_MODELS_URL,
        api_key=GITHUB_TOKEN,
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
        total_batches = (len(to_summarise) // BATCH_SIZE) + 1
        print(f"  📦 Batch {batch_num}/{total_batches} ({len(batch)} articles)...", end=" ")

        results = summarise_batch(client, batch)
        api_calls += 1

        if results and isinstance(results, list):
            for j, item in enumerate(results):
                summary = item.get("summary", "") if isinstance(item, dict) else ""
                if summary and j < len(batch):
                    orig_idx = batch[j][0]
                    articles[orig_idx]["ai_summary"] = summary
                    summarised += 1
            print(f"✅ ({len(results)} summaries)")
        else:
            # Fallback: summarise individually
            print("⚠️  falling back to individual mode")
            for idx, title, snippet in batch:
                summary = summarise_single(client, title, snippet)
                api_calls += 1
                if summary:
                    articles[idx]["ai_summary"] = summary
                    summarised += 1
                time.sleep(0.5)

        # Brief pause between batches to avoid rate-limit bursts
        time.sleep(1)

    skipped = len(articles) - summarised

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(articles, f, indent=2, ensure_ascii=False)

    print()
    print(f"✅ Done: {summarised} summarised, {skipped} skipped")
    print(f"   🔄 API calls used: {api_calls} (limit: 150/day)")
    print(f"   Saved to: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
