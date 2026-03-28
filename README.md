# 🗞️ AI News — ainews.aguidetocloud.com

Automated AI news aggregator that runs every night, fetches the latest AI news from RSS feeds and NewsAPI, summarises each article using GPT-4o mini (via GitHub Models), and publishes a slick retro-neon dashboard.

## 🌐 Live Site

**[ainews.aguidetocloud.com](https://ainews.aguidetocloud.com)** — Updated daily at midnight NZT

## 🏗️ Architecture

```
RSS Feeds ──┐
             ├──▶ fetch_news.py ──▶ summarise.py ──▶ generate_page.py ──▶ index.html
NewsAPI ────┘      (articles)       (GPT-4o mini)     (retro HTML)        (deployed)

GitHub Actions runs this pipeline nightly → commits output → deploys to Azure Static Web App
```

## 📰 News Categories

| Section | What's Covered |
|---------|---------------|
| 🔥 Top Stories | Biggest AI headlines from TechCrunch, The Verge, Ars Technica |
| 🗣️ Rumours & Gossip | Leaks, speculation, "reportedly" stories |
| 🟦 Microsoft | Copilot, Azure AI, Foundry, Windows AI |
| 🟩 OpenAI | GPT models, ChatGPT, API updates |
| 🟥 Google | Gemini, DeepMind, Vertex AI |
| 🟪 Meta | Llama, open-source AI |
| 🟧 Anthropic | Claude, MCP protocol |
| ⬛ Open Source | Hugging Face, community models |
| 🔵 Industry | Regulations, funding, trends |

## 📅 Features

- **Daily page** with sidebar navigation and category cards
- **Weekly digest** — top stories from the last 7 days
- **Monthly roundup** — all stories from the current month
- **Archive** — browse back through previous days
- **Retro neon theme** — dark, glowing, visually appealing

## 💰 Cost

Under **$2/month** — mostly AI summarisation. Hosting, automation, and news sources are free.

## 🔧 Local Development

```bash
pip install -r requirements.txt
export NEWSAPI_KEY="your-key"
export GITHUB_TOKEN="your-pat"
python scripts/fetch_news.py
python scripts/summarise.py
python scripts/generate_page.py
# Open site/index.html in browser
```

## 📝 License

Built by [Sutheesh](https://www.aguidetocloud.com) — Part of the Cloud & AI learning journey.
