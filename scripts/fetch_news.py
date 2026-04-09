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
BROKEN_FEEDS_FILE = SCRIPT_DIR / ".." / "site" / "broken_feeds.json"
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
    broken_feeds = []
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
                if feed.bozo and not feed.entries:
                    error_msg = str(getattr(feed, 'bozo_exception', 'Unknown parse error'))
                    print(f"❌ Feed error: {error_msg[:60]}")
                    broken_feeds.append({"name": feed_name, "url": feed_url, "category": cat_name, "error": error_msg[:120]})
                    continue
                if hasattr(feed, 'status') and feed.status >= 400:
                    print(f"❌ HTTP {feed.status}")
                    broken_feeds.append({"name": feed_name, "url": feed_url, "category": cat_name, "error": f"HTTP {feed.status}"})
                    continue
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

                    # Extract thumbnail from RSS media tags
                    image = ""
                    media = getattr(entry, "media_content", None)
                    if media and len(media) > 0:
                        image = media[0].get("url", "")
                    if not image:
                        media_thumb = getattr(entry, "media_thumbnail", None)
                        if media_thumb and len(media_thumb) > 0:
                            image = media_thumb[0].get("url", "")
                    if not image:
                        enclosures = getattr(entry, "enclosures", [])
                        for enc in enclosures:
                            if enc.get("type", "").startswith("image/"):
                                image = enc.get("href", enc.get("url", ""))
                                break

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
                        "image": image,
                        "ai_summary": ""
                    })
                    count += 1

                print(f"✅ {count} articles")
            except Exception as e:
                print(f"❌ Error: {e}")
                broken_feeds.append({"name": feed_name, "url": feed_url, "category": cat_name, "error": str(e)[:120]})

    return articles, broken_feeds


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
                    "image": item.get("urlToImage", ""),
                    "ai_summary": ""
                })
                count += 1

            print(f"✅ {count} articles")
        except Exception as e:
            print(f"❌ Error: {e}")

    return articles


def deduplicate(articles):
    """Remove duplicate articles by ID and fuzzy title matching."""
    seen_ids = set()
    seen_titles = []
    unique = []
    for article in articles:
        if article["id"] in seen_ids:
            continue
        # Fuzzy title dedup: normalise and check similarity
        norm_title = _normalise_title(article.get("title", ""))
        if norm_title and any(_title_similarity(norm_title, st) > 0.75 for st in seen_titles):
            continue
        seen_ids.add(article["id"])
        if norm_title:
            seen_titles.append(norm_title)
        unique.append(article)
    return unique


def _normalise_title(title):
    """Lowercase, strip punctuation and common prefixes for comparison."""
    import re
    t = title.lower().strip()
    # Remove common source prefixes like "[EXTERNAL]", "BREAKING:", etc.
    t = re.sub(r"^\[.*?\]\s*", "", t)
    t = re.sub(r"^(breaking|exclusive|update|report):\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"[^\w\s]", "", t)
    return " ".join(t.split())


def _title_similarity(a, b):
    """Simple word-overlap similarity ratio (Jaccard-like)."""
    words_a = set(a.split())
    words_b = set(b.split())
    if not words_a or not words_b:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)


def recategorize_by_keywords(articles, categories):
    """Move articles from general categories to vendor categories if keywords match.
    
    Articles from TechCrunch/Verge about DeepSeek get moved to the DeepSeek category.
    Only moves from general categories (top-stories, rumours, industry, opensource).
    Never moves articles already in a specific vendor category.
    """
    # Build keyword → category mapping (only for categories that have keywords)
    general_cats = {"top-stories", "rumours", "industry", "opensource"}
    keyword_map = []
    for cat in categories:
        keywords = cat.get("keywords", [])
        if keywords and cat["id"] not in general_cats:
            keyword_map.append({
                "id": cat["id"],
                "name": cat["name"],
                "emoji": cat["emoji"],
                "keywords": [kw.lower() for kw in keywords],
            })

    moved = 0
    for article in articles:
        # Only re-categorize articles currently in general categories
        if article["category_id"] not in general_cats:
            continue

        text = (article.get("title", "") + " " + article.get("snippet", "")).lower()

        for cat_info in keyword_map:
            if any(kw in text for kw in cat_info["keywords"]):
                article["category_id"] = cat_info["id"]
                article["category_name"] = cat_info["name"]
                article["category_emoji"] = cat_info["emoji"]
                moved += 1
                break

    print(f"  📦 Re-categorized {moved} articles based on keyword matching")
    return articles


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
    rss_articles, broken_feeds = fetch_rss_feeds(categories, cutoff_time)

    print()
    print("🔍 NewsAPI:")
    newsapi_articles = fetch_newsapi(categories, cutoff_time)

    # Combine and deduplicate
    all_articles = rss_articles + newsapi_articles
    all_articles = deduplicate(all_articles)

    # Re-categorize: move articles from general feeds to vendor categories based on keywords
    print()
    print("🏷️  Keyword re-categorization:")
    all_articles = recategorize_by_keywords(all_articles, categories)

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

    # Write broken feeds report
    BROKEN_FEEDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(BROKEN_FEEDS_FILE, "w", encoding="utf-8") as f:
        json.dump(broken_feeds, f, indent=2, ensure_ascii=False)
    if broken_feeds:
        print(f"   ⚠️  {len(broken_feeds)} broken feed(s) — see {BROKEN_FEEDS_FILE}")


if __name__ == "__main__":
    main()
