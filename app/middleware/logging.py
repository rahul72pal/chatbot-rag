import time
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from app.core.logger import logger

class LoggingMiddleware(BaseHTTPMiddleware):
    """Middleware to log incoming HTTP requests, latencies, and response statuses."""
    
    async def dispatch(self, request: Request, call_next) -> Response:
        start_time = time.perf_counter()
        
        # Log incoming request details
        method = request.method
        path = request.url.path
        client_host = request.client.host if request.client else "unknown"
        
        logger.info(f"Incoming request: {method} {path} from IP {client_host}")
        
        try:
            response = await call_next(request)
            
            # Calculate duration
            latency = time.perf_counter() - start_time
            logger.info(
                f"Response: {method} {path} finished with status {response.status_code} "
                f"in {latency:.4f}s"
            )
            return response
            
        except Exception as exc:
            # Handle and log unexpected middleware-level crashes
            latency = time.perf_counter() - start_time
            logger.exception(
                f"Request failed: {method} {path} with exception '{type(exc).__name__}' "
                f"after {latency:.4f}s"
            )
            raise exc
