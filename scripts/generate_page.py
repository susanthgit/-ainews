"""
Step 3: Generate static HTML page from summarised articles.
Supports two layouts: 'cards' (grouped by category) and 'timeline' (chronological).
"""

import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from dateutil import parser as dateparser
from jinja2 import Environment, FileSystemLoader


SCRIPT_DIR = Path(__file__).parent
TEMPLATES_DIR = SCRIPT_DIR / ".." / "templates"
INPUT_FILE = SCRIPT_DIR / ".." / "site" / "summaries.json"
FEEDS_FILE = SCRIPT_DIR / "feeds.json"
SITE_DIR = SCRIPT_DIR / ".." / "site"

# Common words to ignore when extracting trending topics
STOP_WORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "is", "it", "its", "that", "this", "are",
    "was", "were", "be", "been", "has", "have", "had", "do", "does", "did",
    "will", "would", "could", "should", "may", "might", "can", "how", "what",
    "why", "when", "where", "who", "which", "not", "no", "all", "more",
    "than", "just", "about", "over", "into", "out", "up", "new", "now",
    "says", "said", "get", "got", "also", "like", "after", "before",
    "here", "your", "you", "we", "our", "their", "its", "his", "her",
    "as", "if", "so", "very", "most", "some", "any", "other", "us",
    "use", "using", "used", "make", "made", "first", "want", "wants",
    "one", "two", "per", "way", "top", "big", "best", "next", "last",
    "being", "still", "even", "much", "don", "let", "back", "going",
}


def format_date(iso_string):
    """Format ISO date to readable display format."""
    try:
        dt = dateparser.parse(iso_string)
        now = datetime.now(timezone.utc)
        delta = now - dt.astimezone(timezone.utc)

        if delta.total_seconds() < 3600:
            mins = int(delta.total_seconds() / 60)
            return f"{mins}m ago"
        elif delta.total_seconds() < 86400:
            hours = int(delta.total_seconds() / 3600)
            return f"{hours}h ago"
        else:
            return dt.strftime("%b %d, %H:%M")
    except Exception:
        return ""


def load_category_colors():
    """Load category colors from feeds.json."""
    with open(FEEDS_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)
    return {cat["id"]: cat["color"] for cat in config["categories"]}


def extract_trending_topics(articles, top_n=15):
    """Extract most mentioned meaningful words/phrases from article titles."""
    word_counts = Counter()

    for article in articles:
        title = article.get("title", "")
        words = re.findall(r"[A-Za-z][A-Za-z'-]+", title)
        for word in words:
            lower = word.lower()
            if lower not in STOP_WORDS and len(word) > 2:
                # Preserve original casing for proper nouns
                if word[0].isupper() and len(word) > 2:
                    word_counts[word] += 1
                else:
                    word_counts[lower] += 1

    # Merge case variants (keep the most common casing)
    merged = {}
    for word, count in word_counts.items():
        key = word.lower()
        if key in merged:
            existing_word, existing_count = merged[key]
            if count > existing_count:
                merged[key] = (word, count + existing_count)
            else:
                merged[key] = (existing_word, count + existing_count)
        else:
            merged[key] = (word, count)

    sorted_topics = sorted(merged.values(), key=lambda x: x[1], reverse=True)
    return [word for word, count in sorted_topics[:top_n] if count >= 2]


def generate_cards(articles, feeds_config, date_str=None, nav_links=None, page_type="daily"):
    """Generate cards layout — grouped by category."""
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    template = env.get_template("cards.html.j2")

    # Group articles by category, preserving order from feeds_config
    categories_map = {}
    for cat in feeds_config["categories"]:
        categories_map[cat["id"]] = {
            "id": cat["id"],
            "name": cat["name"],
            "emoji": cat["emoji"],
            "color": cat["color"],
            "parent": cat.get("parent", ""),
            "articles": [],
        }

    for article in articles:
        cat_id = article.get("category_id", "industry")
        article["published_display"] = format_date(article.get("published", ""))
        if cat_id in categories_map:
            categories_map[cat_id]["articles"].append(article)

    categories_with_articles = [
        cat for cat in categories_map.values() if cat["articles"]
    ]

    sources = set(a["source"] for a in articles)
    trending = extract_trending_topics(articles)

    if not nav_links:
        nav_links = {}

    page_titles = {
        "daily": "DAILY INTELLIGENCE DIGEST",
        "weekly": "WEEKLY TOP STORIES",
        "monthly": "MONTHLY ROUNDUP",
    }

    html = template.render(
        generated_date=date_str or datetime.now(timezone.utc).strftime("%A, %B %d, %Y — %H:%M UTC"),
        total_articles=len(articles),
        total_sources=len(sources),
        total_categories=len(categories_with_articles),
        categories_with_articles=categories_with_articles,
        trending_topics=trending,
        nav_links=nav_links,
        page_type=page_type,
        page_subtitle=page_titles.get(page_type, page_titles["daily"]),
    )

    return html


def generate_timeline(articles, feeds_config):
    """Generate timeline layout — chronological with category badges."""
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)))
    template = env.get_template("timeline.html.j2")

    colors = load_category_colors()
    sources = set()

    for article in articles:
        article["published_display"] = format_date(article.get("published", ""))
        article["category_color"] = colors.get(article.get("category_id", ""), "#666")
        sources.add(article["source"])

    all_categories = [
        {"id": cat["id"], "name": cat["name"], "emoji": cat["emoji"]}
        for cat in feeds_config["categories"]
    ]

    cat_ids_with_articles = set(a.get("category_id") for a in articles)

    html = template.render(
        generated_date=datetime.now(timezone.utc).strftime("%A, %B %d, %Y — %H:%M UTC"),
        total_articles=len(articles),
        total_sources=len(sources),
        total_categories=len(cat_ids_with_articles),
        articles=articles,
        all_categories=all_categories,
    )

    output_path = SITE_DIR / "timeline.html"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  ✅ Timeline layout → {output_path}")
    return html


def get_archived_dates():
    """Find all archived daily data files and return sorted dates."""
    data_dir = SITE_DIR / "data"
    if not data_dir.exists():
        return []
    dates = []
    for f in data_dir.glob("*.json"):
        try:
            dates.append(f.stem)  # e.g., "2026-03-28"
        except Exception:
            pass
    return sorted(dates)


def load_archived_articles(date_str):
    """Load articles from an archived data file."""
    path = SITE_DIR / "data" / f"{date_str}.json"
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def archive_daily(articles, today_str, feeds_config):
    """Archive today's data and generate the daily page with prev/next nav."""
    data_dir = SITE_DIR / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    # Save today's data
    data_path = data_dir / f"{today_str}.json"
    with open(data_path, "w", encoding="utf-8") as f:
        json.dump(articles, f, indent=2, ensure_ascii=False)
    print(f"  📦 Archived data → {data_path}")

    # Build nav links
    all_dates = get_archived_dates()
    nav_links = {"weekly": "/weekly/latest.html", "monthly": "/monthly/latest.html"}

    if today_str in all_dates:
        idx = all_dates.index(today_str)
        if idx > 0:
            prev_date = all_dates[idx - 1]
            nav_links["prev"] = f"/archive/{prev_date}/index.html"
            nav_links["prev_date"] = prev_date
        if idx < len(all_dates) - 1:
            next_date = all_dates[idx + 1]
            nav_links["next"] = f"/archive/{next_date}/index.html"
            nav_links["next_date"] = next_date

    today_display = dateparser.parse(today_str).strftime("%A, %B %d, %Y")

    # Generate today's page
    html = generate_cards(articles, feeds_config, date_str=today_display, nav_links=nav_links, page_type="daily")

    # Save as index.html (latest)
    index_path = SITE_DIR / "index.html"
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  ✅ Today's page → {index_path}")

    # Save archive copy
    archive_dir = SITE_DIR / "archive" / today_str
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_path = archive_dir / "index.html"
    with open(archive_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  📁 Archive copy → {archive_path}")

    # Rebuild previous day's page to add "next" link (if exists)
    if "prev" in nav_links:
        prev_date = nav_links["prev_date"]
        prev_articles = load_archived_articles(prev_date)
        if prev_articles:
            prev_nav = {"next": f"/archive/{today_str}/index.html", "next_date": today_str}
            prev_idx = all_dates.index(prev_date)
            if prev_idx > 0:
                prev_nav["prev"] = f"/archive/{all_dates[prev_idx - 1]}/index.html"
                prev_nav["prev_date"] = all_dates[prev_idx - 1]
            prev_nav["weekly"] = "/weekly/latest.html"
            prev_nav["monthly"] = "/monthly/latest.html"
            prev_display = dateparser.parse(prev_date).strftime("%A, %B %d, %Y")
            prev_html = generate_cards(prev_articles, feeds_config, date_str=prev_display, nav_links=prev_nav, page_type="daily")
            prev_path = SITE_DIR / "archive" / prev_date / "index.html"
            with open(prev_path, "w", encoding="utf-8") as f:
                f.write(prev_html)
            print(f"  🔗 Updated prev day nav → {prev_path}")


def generate_weekly_digest(feeds_config):
    """Generate a weekly digest from the last 7 days of archived data."""
    all_dates = get_archived_dates()
    if not all_dates:
        print("  ⚠️  No archived data for weekly digest")
        return

    # Get last 7 days
    recent_dates = all_dates[-7:]
    all_articles = []
    seen_ids = set()
    for date_str in recent_dates:
        for article in load_archived_articles(date_str):
            if article["id"] not in seen_ids:
                seen_ids.add(article["id"])
                all_articles.append(article)

    all_articles.sort(key=lambda a: a.get("published", ""), reverse=True)

    date_range = f"{recent_dates[0]} to {recent_dates[-1]}"
    nav_links = {"home": "/index.html", "monthly": "/monthly/latest.html"}

    html = generate_cards(
        all_articles, feeds_config,
        date_str=f"Week of {date_range} ({len(recent_dates)} days)",
        nav_links=nav_links,
        page_type="weekly",
    )

    weekly_dir = SITE_DIR / "weekly"
    weekly_dir.mkdir(parents=True, exist_ok=True)
    weekly_path = weekly_dir / "latest.html"
    with open(weekly_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  ✅ Weekly digest ({len(all_articles)} articles) → {weekly_path}")


def generate_monthly_digest(feeds_config):
    """Generate a monthly digest from all days in the current month."""
    all_dates = get_archived_dates()
    if not all_dates:
        print("  ⚠️  No archived data for monthly digest")
        return

    current_month = datetime.now(timezone.utc).strftime("%Y-%m")
    month_dates = [d for d in all_dates if d.startswith(current_month)]

    if not month_dates:
        print(f"  ⚠️  No data for {current_month}")
        return

    all_articles = []
    seen_ids = set()
    for date_str in month_dates:
        for article in load_archived_articles(date_str):
            if article["id"] not in seen_ids:
                seen_ids.add(article["id"])
                all_articles.append(article)

    all_articles.sort(key=lambda a: a.get("published", ""), reverse=True)

    month_display = dateparser.parse(month_dates[0]).strftime("%B %Y")
    nav_links = {"home": "/index.html", "weekly": "/weekly/latest.html"}

    html = generate_cards(
        all_articles, feeds_config,
        date_str=f"{month_display} ({len(month_dates)} days so far)",
        nav_links=nav_links,
        page_type="monthly",
    )

    monthly_dir = SITE_DIR / "monthly"
    monthly_dir.mkdir(parents=True, exist_ok=True)
    monthly_path = monthly_dir / "latest.html"
    with open(monthly_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  ✅ Monthly digest ({len(all_articles)} articles) → {monthly_path}")


def main():
    print("🎨 AI News Page Generator")
    print("=" * 50)

    if not INPUT_FILE.exists():
        print(f"❌ No summaries found at {INPUT_FILE}")
        print("   Run summarise.py first.")
        sys.exit(1)

    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    # Support both old format (bare array) and new format (object with articles key)
    if isinstance(raw_data, dict):
        articles = raw_data.get("articles", [])
    else:
        articles = raw_data

    with open(FEEDS_FILE, "r", encoding="utf-8") as f:
        feeds_config = json.load(f)

    print(f"📰 {len(articles)} articles to render")
    print()

    SITE_DIR.mkdir(parents=True, exist_ok=True)
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # 1. Archive today + generate daily page
    print("📅 Daily page:")
    archive_daily(articles, today_str, feeds_config)
    print()

    # 2. Generate weekly digest
    print("📰 Weekly digest:")
    generate_weekly_digest(feeds_config)
    print()

    # 3. Generate monthly digest
    print("📊 Monthly digest:")
    generate_monthly_digest(feeds_config)
    print()

    print("🎉 Done!")


if __name__ == "__main__":
    main()
