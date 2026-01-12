import logging
import logging.handlers
import os
import json
import time
from datetime import datetime
from .config import Config

class StructuredMessage:
    def __init__(self, message, **kwargs):
        self.message = message
        self.kwargs = kwargs

    def __str__(self):
        s = self.message
        if self.kwargs:
            s += " | " + json.dumps(self.kwargs, default=str)
        return s

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_entry = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "message": record.msg,
            "module": record.module,
        }
        
        # Standard LogRecord attributes to ignore
        standard_attrs = {
            'args', 'asctime', 'created', 'exc_info', 'exc_text', 'filename',
            'funcName', 'levelname', 'levelno', 'lineno', 'module', 'msecs',
            'message', 'msg', 'name', 'pathname', 'process', 'processName',
            'relativeCreated', 'stack_info', 'thread', 'threadName', 'taskName'
        }

        # Include any extra attributes passed via 'extra={...}'
        for key, value in record.__dict__.items():
            if key not in standard_attrs and not key.startswith("_"):
                log_entry[key] = value
        
        return json.dumps(log_entry, default=str)

def setup_loggers():
    if not os.path.exists(Config.LOG_DIR):
        os.makedirs(Config.LOG_DIR)

    loggers = {
        "crawler": "crawler.log",
        "scraper": "scraper.log",
        "errors": "errors.log"
    }
    
    LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    formatter = logging.Formatter(LOG_FORMAT)
    json_formatter = JSONFormatter()

    configured_loggers = {}

    for name, filename in loggers.items():
        logger = logging.getLogger(name)
        logger.setLevel(Config.LOG_LEVEL)
        logger.propagate = False  # Prevent double logging to root

        # File Handler (JSON structured for machine reading if needed, or standard)
        # Requirement: Structured JSON logs
        file_handler = logging.handlers.RotatingFileHandler(
            os.path.join(Config.LOG_DIR, filename), 
            maxBytes=10*1024*1024, # 10MB
            backupCount=5,
            encoding='utf-8'
        )
        file_handler.setFormatter(json_formatter)
        logger.addHandler(file_handler)

        # Console Handler (High level progress)
        if name == "crawler":
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(formatter)
            logger.addHandler(console_handler)
            
        configured_loggers[name] = logger

    return configured_loggers

# Usage shortcut
_loggers = None
def get_logger(name):
    global _loggers
    if _loggers is None:
        _loggers = setup_loggers()
    return _loggers.get(name, logging.getLogger(name))
