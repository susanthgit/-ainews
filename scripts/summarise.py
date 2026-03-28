"""
Step 2: Summarise articles using GitHub Models (GPT-4o mini).
Reads articles.json, adds AI summaries, outputs summaries.json.
"""

import json
import os
import sys
from pathlib import Path

from openai import OpenAI


SCRIPT_DIR = Path(__file__).parent
INPUT_FILE = SCRIPT_DIR / ".." / "site" / "articles.json"
OUTPUT_FILE = SCRIPT_DIR / ".." / "site" / "summaries.json"

# GitHub Models endpoint
GITHUB_MODELS_URL = "https://models.inference.ai.azure.com"
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
MODEL = "gpt-4o-mini"

SYSTEM_PROMPT = """You are an AI news summariser. For each article, write a concise 2-3 sentence summary that:
1. States what happened or was announced
2. Explains why it matters
3. Uses plain English — avoid jargon

Keep each summary under 80 words. Be factual and neutral."""


def summarise_article(client, title, snippet):
    """Generate an AI summary for a single article."""
    user_prompt = f"""Summarise this AI news article:

Title: {title}

Content: {snippet}

Write a 2-3 sentence summary."""

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            max_tokens=150,
            temperature=0.3,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        print(f"    ❌ Summary failed: {e}")
        return ""


def main():
    print("🤖 AI News Summariser (GitHub Models — GPT-4o mini)")
    print("=" * 50)

    if not GITHUB_TOKEN:
        print("❌ GITHUB_TOKEN not set. Set it as an environment variable.")
        print("   For local testing: $env:GITHUB_TOKEN = 'your-token'")
        sys.exit(1)

    # Load articles
    if not INPUT_FILE.exists():
        print(f"❌ No articles found at {INPUT_FILE}")
        print("   Run fetch_news.py first.")
        sys.exit(1)

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        articles = json.load(f)

    print(f"📰 {len(articles)} articles to summarise")
    print()

    # Set up GitHub Models client
    client = OpenAI(
        base_url=GITHUB_MODELS_URL,
        api_key=GITHUB_TOKEN,
    )

    # Summarise each article
    summarised = 0
    skipped = 0
    for i, article in enumerate(articles):
        title = article.get("title", "")
        snippet = article.get("snippet", "")

        if not snippet and not title:
            skipped += 1
            continue

        print(f"  [{i+1}/{len(articles)}] {title[:60]}...", end=" ")
        summary = summarise_article(client, title, snippet)

        if summary:
            article["ai_summary"] = summary
            summarised += 1
            print("✅")
        else:
            skipped += 1
            print("⏭️ skipped")

    # Save output
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(articles, f, indent=2, ensure_ascii=False)

    print()
    print(f"✅ Done: {summarised} summarised, {skipped} skipped")
    print(f"   Saved to: {OUTPUT_FILE}")

    # Rough cost estimate
    avg_tokens = 200  # rough average per article (input + output)
    total_tokens = avg_tokens * summarised
    cost = (total_tokens / 1_000_000) * 0.15  # GPT-4o mini input pricing
    print(f"   💰 Estimated cost: ~${cost:.4f}")


if __name__ == "__main__":
    main()
