# FastAPI DeepSeek Chatbot Backend

A complete, enterprise-ready, production-grade FastAPI backend integrated with the DeepSeek API. This project is built using **Clean Architecture** and **SOLID principles**, featuring async execution, dependency injection, robust exception handling, structured logging, request validation, and comprehensive automated test coverage.

## Features

- **Clean Architecture & SOLID Principles**: Decoupled routes, services, schemas, and configurations.
- **DeepSeek Integration**: Robust async service wrapper for the DeepSeek `/chat/completions` API with:
  - Exponential backoff retry logic.
  - Upstream timeout protection.
  - DeepSeek API error mapping.
- **In-Memory Conversation History**: Decoupled state management allowing conversation state storage using alternating `system`, `user`, and `assistant` formats, ready to be swapped with Redis or PostgreSQL.
- **Custom Middleware**: Request and response logger tracking latency, statuses, and exceptions.
- **Robust Exception Handling**: Global error maps ensuring a uniform, structured JSON response format for all 400, 422, 429, 500, and 503 HTTP statuses.
- **Pydantic Validation**: Strict limits on user prompts (rejecting empty values, whitespace-only messages, and inputs exceeding 5000 characters).
- **Asynchronous Lifespan Client**: Efficient HTTP client connection pool management using FastAPI `lifespan`.

---

## Folder Structure

```text
app/
│
├── main.py                  # Application initialization, middleware, & error handlers
│
├── api/                     # Controller layer
│   ├── __init__.py          # API route package initializer
│   ├── routes.py            # Master router aggregator
│   └── message.py           # /message route controller
│
├── core/                    # Core configuration & systems
│   ├── config.py            # Settings loaded from .env (BaseSettings)
│   ├── logger.py            # Structured stdout logger
│   ├── constants.py         # Static configuration constants
│   └── dependencies.py      # Dependency injection providers (Settings, Services)
│
├── services/                # Business logic layer
│   ├── deepseek_service.py  # Upstream API communications, timeouts, & retries
│   ├── conversation_service.py # In-memory session history manager
│   └── prompt_service.py    # Dynamic system prompt loader
│
├── models/                  # Domain/Data models
│   └── chat.py              # Conversational structs
│
├── schemas/                 # Data transfer validation schemas
│   ├── request.py           # Request validations
│   ├── response.py          # Success payload structures
│   └── error.py             # Error payload structures
│
├── utils/                   # Shared helpers & exceptions
│   ├── helpers.py           # Execution timers and UUID checks
│   ├── validators.py        # Message content rules
│   └── exceptions.py        # Domain-specific HTTP exceptions
│
├── prompts/                 # Dynamic system prompts (non-hardcoded)
│   └── system_prompt.txt    # Default chatbot instructions
│
├── middleware/              # ASGI Middlewares
│   └── logging.py           # Request & response latency logging middleware
│
├── tests/                   # Automated Pytest suite
│   ├── test_chat.py         # Integration and endpoint validation tests
│   └── test_service.py      # Mocked unit tests for deepseek and conversation services
│
├── .env                     # Local environment settings
├── requirements.txt         # Project package dependencies
├── README.md                # General documentation
└── .gitignore               # Ignored git tracks
```

---

## Environment Variables

Configure these settings inside the `.env` file at the root of the project:

```ini
# API Configuration (Direct DeepSeek or OpenRouter)
# Direct DeepSeek API Configuration
DEEPSEEK_API_KEY=your_actual_deepseek_api_key_here
DEEPSEEK_BASE_URL=https://api.deepseek.com
MODEL_NAME=deepseek-chat

# OpenRouter API Integration Configuration (Optional)
# If OPEN_ROUTER_API_KEY is configured, the backend automatically redirects all completions requests
# to OpenRouter (using base url https://openrouter.ai/api/v1).
OPEN_ROUTER_API_KEY=sk-or-v1-...
# You can leave MODEL_NAME as 'deepseek-chat' (auto-mapped to 'deepseek/deepseek-chat')
# or set to any OpenRouter model identifier, e.g. '~deepseek/deepseek-v4-flash-latest'
MODEL_NAME=deepseek/deepseek-chat

# Server Settings (Optional)
APP_NAME="FastAPI DeepSeek Chatbot"
DEBUG=false
API_PREFIX=/api/v1
```

---

## Installation & Setup

### Prerequisites

- **Python**: v3.12 or newer.
- **Pip**: Recommended version matches Python 3.12.

### Step 1: Clone & Navigate

Navigate to the project root:

```bash
cd c:\Users\lenovo\Desktop\New folder\chatbot
```

### Step 2: Set up a Virtual Environment

Create and activate a Python virtual environment:

```powershell
# In PowerShell:
python -m venv .venv
.venv\Scripts\Activate.ps1
```

### Step 3: Install Dependencies

```powershell
pip install -r requirements.txt
```

### Step 4: Configure Environment Variables

Edit the `.env` file at the root and fill in your actual DeepSeek API Key:

```ini
DEEPSEEK_API_KEY=sk-your-deepseek-api-key
```

---

## Running the Application

To start the FastAPI server locally with auto-reload:

```powershell
uvicorn app.main:app --reload
```

The service will start on: `http://127.0.0.1:8000`

- **Interactive API Documentation (Swagger)**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- **API Status / Health Check**: [http://127.0.0.1:8000/health](http://127.0.0.1:8000/health)

---

## API Documentation

### POST `/message`

Processes a chat message. If no `conversation_id` is supplied, a new conversation is initialized and a UUID is returned in the response.

#### **Headers**
```http
Content-Type: application/json
```

#### **Request Body**
```json
{
    "conversation_id": null, // Optional UUID (or string UUID format). Set to null or omit to start a new chat.
    "message": "Hello, what models are you running?"
}
```

#### **Success Response (200 OK)**
```json
{
  "success": true,
  "conversation_id": "76de3432-845b-4395-8123-f36bc4c803f2",
  "message": "Hello! I am powered by DeepSeek-Chat, a large language model created by DeepSeek. How can I assist you today?",
  "usage": {
    "prompt_tokens": 12,
    "completion_tokens": 25,
    "total_tokens": 37
  }
}
```

#### **Error Responses**

- **400 Bad Request (Validation failure like message size or empty check)**
  ```json
  {
    "success": false,
    "error_code": "VALIDATION_FAILED",
    "message": "Message cannot be empty or consist only of whitespace.",
    "details": {}
  }
  ```

- **422 Unprocessable Entity (Malformed JSON structure or invalid UUID type)**
  ```json
  {
    "success": false,
    "error_code": "INPUT_VALIDATION_ERROR",
    "message": "Request schema validation failed. Please check field formats.",
    "details": {
      "errors": [
        {
          "type": "uuid_parsing",
          "loc": ["body", "conversation_id"],
          "msg": "Input should be a valid UUID, unable to parse string as an UUID",
          "input": "invalid-uuid-string"
        }
      ]
    }
  }
  ```

- **503 Service Unavailable (DeepSeek Upstream Timed Out or Server down)**
  ```json
  {
    "success": false,
    "error_code": "DEEPSEEK_TIMEOUT_ERROR",
    "message": "Connection to DeepSeek API timed out.",
    "details": {}
  }
  ```

---

## Testing

The project uses `pytest` and `pytest-asyncio` to execute unit and integration tests. The test suite mocks DeepSeek API responses to facilitate fully offline testing.

### Run Tests

Execute the following command to run all test specifications:

```powershell
pytest -v
```

This runs:
- Schema input validations.
- DeepSeek service integration mocks.
- Latency and retry triggers.
- Global exception mapping validations.

---

## Future Improvements

While this is an enterprise-ready base, the following improvements are recommended for staging/production deployments:

1. **Persistent History Store**: Swap out the in-memory `ConversationService` storage dictionary with a **Redis cache** or a **PostgreSQL relational database** to allow application horizontal scaling.
2. **Conversation Token Limit Truncation**: Implement chat history token counting (e.g. using `tiktoken`) to prune/summarize old messages, ensuring the context window does not exceed the model token boundaries.
3. **API Authentication & Authorization**: Add API authentication middleware (e.g. JWT or OAuth2) to secure endpoints.
4. **Streaming Response Endpoint**: Support Server-Sent Events (SSE) `/message/stream` endpoint for real-time text generation interfaces.
5. **Correlation ID propagation**: Track requests through internal sub-calls via a custom ContextVar for even clearer multi-threaded logging.
