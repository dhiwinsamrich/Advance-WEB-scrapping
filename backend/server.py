import asyncio
import threading
from fastapi import FastAPI, WebSocket, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from scraper.crawler import Crawler
from scraper.logger import get_logger
import os

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = FastAPI()

# Allow CORS - Restricted Origins
origins = [
    # "https://advance-web-scrapping.vercel.app",
    "http://localhost:3000"  # Keep for local development
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ScrapeRequest(BaseModel):
    url: str
    max_depth: int = 1

class ScraperStatus:
    is_running = False
    pages_scraped = 0
    current_url = ""

status = ScraperStatus()
active_crawler = None

def run_crawler_bg(url: str, max_depth: int):
    global status
    status.is_running = True
    status.current_url = url
    try:
        # Initialize Crawler with dynamic config
        global active_crawler
        active_crawler = Crawler(base_url=url, max_depth=max_depth)
        active_crawler.start()
    except Exception as e:
        print(f"Crawler error: {e}")
    finally:
        status.is_running = False
        status.current_url = ""
        active_crawler = None

@app.post("/start")
async def start_scrape(request: ScrapeRequest):
    if status.is_running:
        raise HTTPException(status_code=400, detail="Scraper is already running")
    
    thread = threading.Thread(target=run_crawler_bg, args=(request.url, request.max_depth))
    thread.start()
    
    return {"message": "Scraper started", "url": request.url}

@app.get("/status")
async def get_status():
    return {
        "is_running": status.is_running,
        "current_url": status.current_url,
        "logs_path": os.path.abspath("logs/scraper.log")
    }

@app.post("/stop")
async def stop_scrape():
    global active_crawler
    if active_crawler:
        active_crawler.stop()
        return {"message": "Stop signal sent"}
    return {"message": "No active crawler to stop"}

@app.get("/download")
async def download_logs():
    log_file_path = os.path.join("logs", "scraper.log")
    if os.path.exists(log_file_path):
        from fastapi.responses import FileResponse
        return FileResponse(log_file_path, media_type='application/json', filename='scraper_data.json')
    raise HTTPException(status_code=404, detail="Log file not found")

@app.websocket("/logs")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    log_file_path = os.path.join("logs", "scraper.log")
    
    # Ensure file exists
    if not os.path.exists(log_file_path):
        open(log_file_path, 'a').close()

    try:
        with open(log_file_path, "r") as f:
            # Go to the end of file
            f.seek(0, 2)
            
            while True:
                line = f.readline()
                if line:
                    await websocket.send_text(line)
                else:
                    await asyncio.sleep(0.1)
    except Exception as e:
        print(f"WebSocket error: {e}")
    finally:
        try:
            await websocket.close()
        except:
            pass
