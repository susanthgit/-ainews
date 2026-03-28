"""
Step 1: Fetch AI news from RSS feeds and NewsAPI.
Outputs articles.json with deduplicated, last-24-hour articles.
"""

import json
import os
import sys
import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser
import requests
from dateutil import parser as dateparser


SCRIPT_DIR = Path(__file__).parent
FEEDS_FILE = SCRIPT_DIR / "feeds.json"
OUTPUT_FILE = SCRIPT_DIR / ".." / "site" / "articles.json"
NEWSAPI_KEY = os.environ.get("NEWSAPI_KEY", "")
HOURS_LOOKBACK = 48  # fetch last 48 hours to catch anything missed


def load_feeds():
    with open(FEEDS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def parse_date(date_str):
    """Parse various date formats into timezone-aware datetime."""
    if not date_str:
        return None
    try:
        dt = dateparser.parse(date_str)
        if dt and dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def article_id(url, title):
    """Generate a unique ID for deduplication."""
    key = (url or "") + (title or "")
    return hashlib.md5(key.encode()).hexdigest()


def fetch_rss_feeds(categories, cutoff_time):
    """Fetch articles from all RSS feeds."""
    articles = []
    for category in categories:
        cat_id = category["id"]
        cat_name = category["name"]
        cat_emoji = category["emoji"]

        for feed_info in category.get("feeds", []):
            feed_name = feed_info["name"]
            feed_url = feed_info["url"]
            print(f"  📡 Fetching RSS: {feed_name}...", end=" ")

            try:
                feed = feedparser.parse(feed_url)
                count = 0
                for entry in feed.entries:
                    published = parse_date(
                        getattr(entry, "published", None)
                        or getattr(entry, "updated", None)
                    )

                    if published and published < cutoff_time:
                        continue

                    title = getattr(entry, "title", "No title")
                    link = getattr(entry, "link", "")
                    summary = getattr(entry, "summary", "")
                    # Clean HTML tags from summary
                    if summary:
                        import re
                        summary = re.sub(r"<[^>]+>", "", summary)
                        summary = summary[:500]

                    articles.append({
                        "id": article_id(link, title),
                        "title": title,
                        "url": link,
                        "source": feed_name,
                        "category_id": cat_id,
                        "category_name": cat_name,
                        "category_emoji": cat_emoji,
                        "published": published.isoformat() if published else datetime.now(timezone.utc).isoformat(),
                        "snippet": summary,
                        "ai_summary": ""
                    })
                    count += 1

                print(f"✅ {count} articles")
            except Exception as e:
                print(f"❌ Error: {e}")

    return articles


def fetch_newsapi(categories, cutoff_time):
    """Fetch articles from NewsAPI using category keywords."""
    if not NEWSAPI_KEY:
        print("  ⚠️  NEWSAPI_KEY not set — skipping NewsAPI")
        return []

    articles = []
    from_date = cutoff_time.strftime("%Y-%m-%dT%H:%M:%S")

    # Build keyword queries per category
    for category in categories:
        keywords = category.get("keywords", [])
        if not keywords:
            continue

        cat_id = category["id"]
        cat_name = category["name"]
        cat_emoji = category["emoji"]

        # Use OR to combine keywords (NewsAPI syntax)
        query = " OR ".join(f'"{kw}"' for kw in keywords[:5])

        print(f"  🔍 NewsAPI: {cat_name} ({len(keywords)} keywords)...", end=" ")

        try:
            resp = requests.get(
                "https://newsapi.org/v2/everything",
                params={
                    "q": query,
                    "from": from_date,
                    "sortBy": "publishedAt",
                    "language": "en",
                    "pageSize": 10,
                    "apiKey": NEWSAPI_KEY,
                },
                timeout=15,
            )
            data = resp.json()

            if data.get("status") != "ok":
                print(f"❌ {data.get('message', 'Unknown error')}")
                continue

            count = 0
            for item in data.get("articles", []):
                title = item.get("title", "")
                url = item.get("url", "")
                if not title or title == "[Removed]":
                    continue

                published = parse_date(item.get("publishedAt"))
                description = item.get("description", "") or ""

                articles.append({
                    "id": article_id(url, title),
                    "title": title,
                    "url": url,
                    "source": item.get("source", {}).get("name", "NewsAPI"),
                    "category_id": cat_id,
                    "category_name": cat_name,
                    "category_emoji": cat_emoji,
                    "published": published.isoformat() if published else datetime.now(timezone.utc).isoformat(),
                    "snippet": description[:500],
                    "ai_summary": ""
                })
                count += 1

            print(f"✅ {count} articles")
        except Exception as e:
            print(f"❌ Error: {e}")

    return articles


def deduplicate(articles):
    """Remove duplicate articles by ID."""
    seen = set()
    unique = []
    for article in articles:
        if article["id"] not in seen:
            seen.add(article["id"])
            unique.append(article)
    return unique


def main():
    print("🗞️  AI News Fetcher")
    print("=" * 50)

    config = load_feeds()
    categories = config["categories"]
    cutoff_time = datetime.now(timezone.utc) - timedelta(hours=HOURS_LOOKBACK)
    print(f"📅 Looking back {HOURS_LOOKBACK} hours (since {cutoff_time.strftime('%Y-%m-%d %H:%M UTC')})")
    print()

    # Fetch from both sources
    print("📡 RSS Feeds:")
    rss_articles = fetch_rss_feeds(categories, cutoff_time)

    print()
    print("🔍 NewsAPI:")
    newsapi_articles = fetch_newsapi(categories, cutoff_time)

    # Combine and deduplicate
    all_articles = rss_articles + newsapi_articles
    all_articles = deduplicate(all_articles)

    # Sort by published date (newest first)
    all_articles.sort(key=lambda a: a["published"], reverse=True)

    # Apply per-category article limits (Microsoft categories are unlimited)
    cat_limits = {}
    ms_categories = set()
    for cat in categories:
        if cat.get("parent") == "microsoft" or cat["id"] == "microsoft":
            ms_categories.add(cat["id"])
        max_articles = cat.get("max_articles")
        if max_articles:
            cat_limits[cat["id"]] = max_articles

    # Filter: keep all Microsoft articles, limit others
    cat_counts = {}
    filtered_articles = []
    for article in all_articles:
        cat_id = article["category_id"]
        cat_counts[cat_id] = cat_counts.get(cat_id, 0) + 1

        if cat_id in ms_categories:
            filtered_articles.append(article)
        elif cat_id in cat_limits:
            if cat_counts[cat_id] <= cat_limits[cat_id]:
                filtered_articles.append(article)
        else:
            filtered_articles.append(article)

    if len(filtered_articles) < len(all_articles):
        print(f"   📊 Trimmed from {len(all_articles)} → {len(filtered_articles)} (non-Microsoft categories capped)")

    all_articles = filtered_articles

    # Save output
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(all_articles, f, indent=2, ensure_ascii=False)

    print()
    print(f"✅ Total: {len(all_articles)} unique articles")
    print(f"   RSS: {len(rss_articles)} | NewsAPI: {len(newsapi_articles)}")
    print(f"   Saved to: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
