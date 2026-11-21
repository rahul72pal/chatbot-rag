import logging
import sys
from typing import Any
from app.logging_setup import JsonFormatter

def setup_logger(name: str = "chatbot") -> logging.Logger:
    """Sets up a structured console logger for the application."""
    logger = logging.getLogger(name)
    
    # If the logger is already configured, return it
    if logger.handlers:
        return logger

    logger.setLevel(logging.INFO)
    
    # Create console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    
    formatter = JsonFormatter()
    console_handler.setFormatter(formatter)
    
    logger.addHandler(console_handler)
    
    # Disable propagation to prevent duplicate logs in Uvicorn
    logger.propagate = False
    
    return logger

# Singleton logger instance
logger = setup_logger()
