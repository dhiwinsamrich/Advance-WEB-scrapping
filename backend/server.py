import asyncio
import threading
from fastapi import FastAPI, WebSocket, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from scraper.crawler import Crawler
from scraper.logger import get_logger, JSONFormatter
import os
import uuid
import logging
import logging.handlers

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

app = FastAPI()

# Allow CORS - Restricted Origins
origins = [
    "https://advance-web-scrapping.vercel.app",  # Production frontend
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
    session_id = ""
    current_log_file = ""

status = ScraperStatus()
active_crawler = None

def run_crawler_bg(url: str, max_depth: int):
    global status
    
    # Generate Session ID
    session_id = str(uuid.uuid4())[:8]
    log_filename = f"scrape_{session_id}.log"
    log_path = os.path.join("logs", log_filename)
    
    status.is_running = True
    status.current_url = url
    status.session_id = session_id
    status.current_log_file = os.path.abspath(log_path)
    
    # Setup Dynamic File Handler for this session
    handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=10*1024*1024, backupCount=1, encoding='utf-8'
    )
    handler.setFormatter(JSONFormatter())
    
    # Attach to loggers
    loggers = ["crawler", "scraper", "errors"]
    active_handlers = []
    
    for name in loggers:
        l = logging.getLogger(name)
        l.addHandler(handler)
        active_handlers.append((l, handler))

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
        
        # Cleanup: Remove handlers to prevent duplicate logs in future runs
        for l, h in active_handlers:
            l.removeHandler(h)
        handler.close()

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
    import json
    # Use current log file if running, or fall back to most recent if available
    # For now, we rely on the status.current_log_file which might be empty if restarted.
    # But if a scrape just finished, it should ideally persist? 
    # Actually, status object persists in memory so it should be fine until server restart.
    
    log_file_path = status.current_log_file
    if not log_file_path or not os.path.exists(log_file_path):
         # Fallback: try to find the latest log file? or just fail gracefully.
         # For reliability, let's look for 'logs/scraper.log' as a fallback or just error.
         # Actually, let's fallback to the generic scraper.log if specific one fails, 
         # essentially assuming legacy behavior if no session.
         log_file_path = os.path.join("logs", "scraper.log")
    
    def clean_data(obj):
        """
        Recursively remove empty strings, empty lists, empty dicts, and None values.
        """
        if isinstance(obj, dict):
            new_dict = {}
            for k, v in obj.items():
                cleaned_v = clean_data(v)
                if cleaned_v not in ["", [], {}, None]:
                    new_dict[k] = cleaned_v
            return new_dict
        elif isinstance(obj, list):
            new_list = []
            for item in obj:
                cleaned_item = clean_data(item)
                if cleaned_item not in ["", [], {}, None]:
                    new_list.append(cleaned_item)
            return new_list if new_list else []
        elif obj == "":
            return None
        else:
            return obj

    if os.path.exists(log_file_path):
        cleaned_logs = []
        try:
            with open(log_file_path, "r", encoding="utf-8") as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                        # We only want entries that have extracted data
                        if entry.get("message") == "Extracted content" and "data" in entry:
                            # Extract the 'data' field which contains the scrape results
                            scraped_data = entry.get("data")
                            processed_data = clean_data(scraped_data)
                            if processed_data:
                                cleaned_logs.append(processed_data)
                    except json.JSONDecodeError:
                        continue
            
            # Create a string buffer
            from io import StringIO
            # Return as a JSON response with file attachment headers
            from fastapi.responses import Response
            
            json_content = json.dumps(cleaned_logs, indent=2)
            
            return Response(
                content=json_content,
                media_type='application/json',
                headers={"Content-Disposition": "attachment; filename=scraper_data.json"}
            )
            
        except Exception as e:
            print(f"Error processing logs: {e}")
            raise HTTPException(status_code=500, detail="Error processing log file")

    raise HTTPException(status_code=404, detail="Log file not found")

@app.websocket("/logs")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    
    # Determine which log file to watch
    # If a scrape is running, watch that one.
    log_file_path = status.current_log_file
    
    # If no active scrape, maybe wait or just default to something?
    # If path is empty, we wait until it's set?
    if not log_file_path:
        # Fallback to standard log or wait
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
