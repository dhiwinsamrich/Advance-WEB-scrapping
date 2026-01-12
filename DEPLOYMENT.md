# Deployment Guide

This project is structured for **Split Hosting**.

## Part 1: Backend (`backend/`) -> Render / Railway / VPS

The backend requires **Headless Chrome** and **Docker**.

1.  **Build Context**: Make sure your Docker build context is set to the `backend/` directory if deploying from a monorepo, OR push the `backend` folder as the root of the deployment.
2.  **Dockerfile**: Located in `backend/Dockerfile`.
3.  **Environment Variables**:
    *   `PORT`: `8000`
    *   `BASE_URL`: Target URL (optional default)

## Part 2: Frontend (`frontend/`) -> Vercel

1.  **Import to Vercel**:
    *   Select the `frontend` directory as the **Root Directory** in Vercel project settings.
2.  **Environment Variables**:
    *   `NEXT_PUBLIC_API_URL`: The URL of your deployed backend (e.g., `https://my-scraper-api.onrender.com`).

## Local Development
1.  **Backend**: `cd backend && python -m uvicorn server:app --reload`
2.  **Frontend**: `cd frontend && npm run dev`
