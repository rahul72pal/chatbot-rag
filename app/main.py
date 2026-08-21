from contextlib import asynccontextmanager
from typing import AsyncGenerator
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import httpx

from app.api.routes import api_router
from app.core.config import settings
from app.core.logger import logger
from app.middleware.logging import LoggingMiddleware
from app.schemas.error import ErrorResponse
from app.utils.exceptions import ChatbotException
from app.routes.auth import router as auth_router

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manages the lifespan of the FastAPI application.
    
    Ensures that a single, shared HTTPX AsyncClient is initialized at startup
    and closed gracefully at shutdown, and connects to MongoDB.
    """
    logger.info("Initializing HTTP client session and MongoDB client...")
    # Initialize the httpx client and attach it to application state
    app.state.http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(settings.DEEPSEEK_TIMEOUT)
    )
    
    from app.db.mongodb import db
    db.init(settings.MONGO_URL)
    app.state.mongo_client = db.client
    app.state.mongo_db = db.database
    
    # Create TTL indexes for 24-hour auto-expiration (86400 seconds)
    try:
        await db.conversations_collection.create_index("created_at", expireAfterSeconds=86400)
        await db.messages_collection.create_index("created_at", expireAfterSeconds=86400)
        await db.conversations_collection.create_index("deleted", expireAfterSeconds=86400)
        await db.messages_collection.create_index("deleted", expireAfterSeconds=86400)
    except Exception as ttl_err:
        logger.warning(f"TTL index creation note: {ttl_err}")

    
    yield
    logger.info("Closing HTTP client session and MongoDB client...")
    # Close the HTTPX client when application stops
    await app.state.http_client.aclose()
    # Close MongoDB client
    db.close()


app = FastAPI(
    title=settings.APP_NAME,
    description="A clean-architecture, production-ready FastAPI backend for DeepSeek Chatbot.",
    version="1.0.0",
    debug=settings.DEBUG,
    lifespan=lifespan
)

# CORS middleware configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict to specific domains in production environments
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Custom request-response logging middleware
app.add_middleware(LoggingMiddleware)

# Include routes (mount without prefix so `/message` is available directly at root)
app.include_router(api_router)
app.include_router(auth_router)


@app.get("/health", status_code=status.HTTP_200_OK, tags=["System"])
async def health_check() -> dict:
    """Basic health check route."""
    return {
        "status": "healthy",
        "app_name": settings.APP_NAME
    }


@app.get("/widget.js", tags=["Widget"])
async def get_widget_js():
    """Serves the widget embed JavaScript file."""
    import os
    from fastapi.responses import FileResponse, Response
    
    widget_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "chatbot-ui", "public", "widget.js")
    if os.path.exists(widget_path):
        return FileResponse(
            widget_path, 
            media_type="application/javascript",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"}
        )
    
    return Response(
        content="console.error('widget.js file not found on server.');",
        media_type="application/javascript"
    )



# Exception Handler: Domain Specific Chatbot Exceptions
@app.exception_handler(ChatbotException)
async def chatbot_exception_handler(request: Request, exc: ChatbotException) -> JSONResponse:
    """Transforms custom chatbot exceptions into unified error responses."""
    logger.error(
        f"Domain error caught: {exc.message} | Error Code: {exc.error_code} | Status: {exc.status_code}"
    )
    error_response = ErrorResponse(
        success=False,
        error_code=exc.error_code,
        message=exc.message,
        details=exc.details
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=error_response.model_dump()
    )


# Exception Handler: Request Input Pydantic Validations
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Transforms input schema validation errors (FastAPI/Pydantic) into unified format."""
    logger.error(f"Input validation failed: {exc.errors()}")
    
    # Format detailed error descriptions
    errors = exc.errors()
    for err in errors:
        if "ctx" in err and isinstance(err["ctx"], dict) and "error" in err["ctx"]:
            err["ctx"]["error"] = str(err["ctx"]["error"])
            
    error_details = {"errors": errors}
    
    error_response = ErrorResponse(
        success=False,
        error_code="INPUT_VALIDATION_ERROR",
        message="Request schema validation failed. Please check field formats.",
        details=error_details
    )
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=error_response.model_dump()
    )


# Exception Handler: Catch-all Fallback
@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Fallback handler to prevent server crashes and keep response format uniform."""
    logger.exception(f"Unhandled exception encountered: {exc}")
    
    error_response = ErrorResponse(
        success=False,
        error_code="INTERNAL_SERVER_ERROR",
        message="An unexpected server error occurred."
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=error_response.model_dump()
    )
