# Production-Ready Web Scraping Framework

A modular, configurable, and scalable web scraper built with Python, Selenium, and BeautifulSoup.

## Project Structure
-   **`backend/`**: FastAPI server, Scraper logic, Dockerfile.
-   **`frontend/`**: Next.js Web Dashboard.

## Quick Start (Dashboard)

### 1. Start the Backend API
```bash
cd backend
python -m uvicorn server:app --reload --port 8000
```

### 2. Start the Frontend UI
```bash
cd frontend
npm run dev
```

### 3. Access
Open **http://localhost:3000** in your browser.

## Features
- **Hybrid Scraping**: Requests for static pages, Selenium for dynamic content.
- **Web Dashboard**: Shadcn-style Black & White UI.
- **Recursive Crawling**: Configurable depth control.
- **Structured Logging**: JSON-formatted logs.
- **Anti-bot**: Random User-Agents, dynamic delays.

## Deployment
See `DEPLOYMENT.md` for instructions on hosting the frontend on Vercel and backend on Render/Docker.
