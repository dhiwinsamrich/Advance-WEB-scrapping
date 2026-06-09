import asyncio
import threading
import os
import uuid
import json
import logging
import logging.handlers

from fastapi import FastAPI, WebSocket, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel
from dotenv import load_dotenv

from scraper.crawler import Crawler
from scraper.logger import get_logger, JSONFormatter

load_dotenv()

app = FastAPI()

origins = [
    "https://advance-web-scrapping.vercel.app",
    "http://localhost:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Scraper state ────────────────────────────────────────────────────────────

_status_lock = threading.Lock()


class ScraperStatus:
    def __init__(self):
        self.is_running = False
        self.current_url = ""
        self.session_id = ""
        self.current_log_file = ""


status = ScraperStatus()
active_crawler = None


class ScrapeRequest(BaseModel):
    url: str
    max_depth: int = 1


def run_crawler_bg(url: str, max_depth: int):
    global active_crawler

    session_id = str(uuid.uuid4())[:8]
    log_filename = f"scrape_{session_id}.log"
    log_dir = os.path.join(os.path.dirname(__file__), "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, log_filename)

    handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=10 * 1024 * 1024, backupCount=1, encoding="utf-8"
    )
    handler.setFormatter(JSONFormatter())

    logger_names = ["crawler", "scraper", "errors"]
    active_handlers = []
    for name in logger_names:
        lg = logging.getLogger(name)
        lg.addHandler(handler)
        active_handlers.append((lg, handler))

    with _status_lock:
        status.is_running = True
        status.current_url = url
        status.session_id = session_id
        status.current_log_file = os.path.abspath(log_path)

    try:
        active_crawler = Crawler(base_url=url, max_depth=max_depth)
        active_crawler.start()
    except Exception as e:
        print(f"Crawler error: {e}")
    finally:
        with _status_lock:
            status.is_running = False
            status.current_url = ""
        active_crawler = None

        for lg, h in active_handlers:
            lg.removeHandler(h)
        handler.close()


@app.post("/start")
async def start_scrape(request: ScrapeRequest):
    with _status_lock:
        if status.is_running:
            raise HTTPException(status_code=400, detail="Scraper is already running")

    thread = threading.Thread(
        target=run_crawler_bg, args=(request.url, request.max_depth), daemon=True
    )
    thread.start()
    return {"message": "Scraper started", "url": request.url}


@app.get("/status")
async def get_status():
    with _status_lock:
        return {
            "is_running": status.is_running,
            "current_url": status.current_url,
            "logs_path": status.current_log_file,
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
    log_file_path = status.current_log_file
    if not log_file_path or not os.path.exists(log_file_path):
        raise HTTPException(status_code=404, detail="No scrape session log found")

    def clean_data(obj):
        if isinstance(obj, dict):
            return {k: v2 for k, v in obj.items() if (v2 := clean_data(v)) not in ["", [], {}, None]}
        if isinstance(obj, list):
            cleaned = [c for item in obj if (c := clean_data(item)) not in ["", [], {}, None]]
            return cleaned
        return None if obj == "" else obj

    cleaned_logs = []
    try:
        with open(log_file_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    entry = json.loads(line)
                    if entry.get("message") == "Extracted content" and "data" in entry:
                        processed = clean_data(entry.get("data"))
                        if processed:
                            cleaned_logs.append(processed)
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        print(f"Error processing logs: {e}")
        raise HTTPException(status_code=500, detail="Error processing log file")

    return Response(
        content=json.dumps(cleaned_logs, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=scraper_data.json"},
    )


@app.websocket("/logs")
async def websocket_logs(websocket: WebSocket):
    await websocket.accept()

    current_file = None
    file_handle = None

    try:
        while True:
            # Pick up new session log file whenever one becomes active
            with _status_lock:
                new_file = status.current_log_file

            if new_file and new_file != current_file and os.path.exists(new_file):
                if file_handle:
                    file_handle.close()
                current_file = new_file
                file_handle = open(current_file, "r", encoding="utf-8")
                file_handle.seek(0, 2)  # tail from end

            if file_handle:
                line = file_handle.readline()
                if line:
                    await websocket.send_text(line)
                    continue

            await asyncio.sleep(0.1)
    except Exception as e:
        print(f"WebSocket /logs error: {e}")
    finally:
        if file_handle:
            file_handle.close()
        try:
            await websocket.close()
        except Exception:
            pass


# ── Sitemap Audit state ───────────────────────────────────────────────────────

_audit_lock = threading.Lock()


class AuditStatus:
    def __init__(self):
        self.is_running = False
        self.session_id = ""
        self.current_log_file = ""
        self.report_path = ""


audit_status = AuditStatus()
active_auditor = None


class AuditRequest(BaseModel):
    url: str
    sitemap_override: str = ""
    max_pages: int = 500
    max_workers: int = 5
    delay: float = 0.5
    strip_query: bool = False
    js_fallback: bool = False


def run_audit_bg(request: AuditRequest):
    global active_auditor

    from scraper.sitemap_auditor import SitemapAuditor, AuditConfig

    session_id = str(uuid.uuid4())[:8]
    log_dir = os.path.join(os.path.dirname(__file__), "logs")
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, f"audit_{session_id}.log")
    report_path = os.path.join(log_dir, f"audit_{session_id}_report.json")

    handler = logging.handlers.RotatingFileHandler(
        log_path, maxBytes=10 * 1024 * 1024, backupCount=1, encoding="utf-8"
    )
    handler.setFormatter(JSONFormatter())

    audit_logger = logging.getLogger("auditor")
    audit_logger.addHandler(handler)

    with _audit_lock:
        audit_status.is_running = True
        audit_status.session_id = session_id
        audit_status.current_log_file = os.path.abspath(log_path)
        audit_status.report_path = os.path.abspath(report_path)

    try:
        cfg = AuditConfig(
            root_url=request.url,
            sitemap_override=request.sitemap_override or None,
            max_pages=request.max_pages,
            max_workers=request.max_workers,
            delay=request.delay,
            strip_query=request.strip_query,
            js_fallback=request.js_fallback,
        )
        active_auditor = SitemapAuditor(cfg)
        report = active_auditor.run()

        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report.to_json())

    except Exception as e:
        print(f"Audit error: {e}")
    finally:
        with _audit_lock:
            audit_status.is_running = False
        active_auditor = None
        audit_logger.removeHandler(handler)
        handler.close()


@app.post("/audit")
async def start_audit(request: AuditRequest):
    with _audit_lock:
        if audit_status.is_running:
            raise HTTPException(status_code=400, detail="Audit is already running")

    thread = threading.Thread(target=run_audit_bg, args=(request,), daemon=True)
    thread.start()
    return {"message": "Audit started", "url": request.url}


@app.post("/audit/stop")
async def stop_audit():
    global active_auditor
    if active_auditor:
        active_auditor.stop()
        return {"message": "Stop signal sent"}
    return {"message": "No active audit to stop"}


@app.get("/audit/status")
async def get_audit_status():
    with _audit_lock:
        return {
            "is_running": audit_status.is_running,
            "session_id": audit_status.session_id,
            "logs_path": audit_status.current_log_file,
            "report_path": audit_status.report_path,
        }


@app.get("/audit/report")
async def get_audit_report():
    report_path = audit_status.report_path
    if not report_path or not os.path.exists(report_path):
        raise HTTPException(status_code=404, detail="No audit report found — run an audit first")

    with open(report_path, "r", encoding="utf-8") as f:
        content = f.read()

    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=audit_report.json"},
    )


@app.websocket("/audit/logs")
async def websocket_audit_logs(websocket: WebSocket):
    await websocket.accept()

    current_file = None
    file_handle = None

    try:
        while True:
            with _audit_lock:
                new_file = audit_status.current_log_file

            if new_file and new_file != current_file and os.path.exists(new_file):
                if file_handle:
                    file_handle.close()
                current_file = new_file
                file_handle = open(current_file, "r", encoding="utf-8")
                file_handle.seek(0, 2)

            if file_handle:
                line = file_handle.readline()
                if line:
                    await websocket.send_text(line)
                    continue

            await asyncio.sleep(0.1)
    except Exception as e:
        print(f"WebSocket /audit/logs error: {e}")
    finally:
        if file_handle:
            file_handle.close()
        try:
            await websocket.close()
        except Exception:
            pass
