from langchain_core.tools import tool
from langchain_community.utilities import DuckDuckGoSearchAPIWrapper
from app.services.qdrant_service import qdrant_service

# Initialize DuckDuckGo API wrapper at module level
search_api = DuckDuckGoSearchAPIWrapper(max_results=5)


@tool
def web_search(query: str) -> str:
    """Search the web for real-time information, news, or current events.
    
    Args:
        query: The search query to look up.
    """
    try:
        return search_api.run(query)
    except Exception as e:
        return f"Error executing web search: {str(e)}"


@tool
async def document_search(query: str) -> str:
    """
    Search uploaded documents using semantic similarity.

    Use this tool when the user asks questions about documents,
    uploaded files, resumes, policies, reports, PDFs, or other
    private knowledge stored in the knowledge base.

    Args:
        query: The semantic search query.
    """

    try:
        from app.core.context import current_user_id, current_chatbot_id
        from app.db.mongodb import db
        user_id = current_user_id.get(None)
        chatbot_id = current_chatbot_id.get(None)

        if qdrant_service.mongo_db is None:
            try:
                qdrant_service.mongo_db = db.database
            except Exception:
                pass

        # STRICT CHATBOT ISOLATION:
        # If chatbot_id is available, filter strictly by chatbot_id so documents from other chatbots of the same user are never returned.
        results = await qdrant_service.similarity_search(
            query=query,
            limit=5,
            chatbot_id=chatbot_id,
            user_id=None if chatbot_id else user_id,
        )

        if not results:
            return "No relevant information was found in the uploaded documents."

        formatted_results = []

        for index, result in enumerate(results, start=1):

            formatted_results.append(
                f"""
Result {index}

Source: {result.get("filename", "Unknown")}

Relevance score: {result.get("score", 0):.4f}

Content:
{result.get("text", "")}
"""
            )

        return "\n".join(formatted_results)

    except Exception as exc:
        return f"Document search failed: {str(exc)}"

@tool
def current_datetime() -> str:
    """Get the current date and time. Use this for current date/time questions."""
    
    now = datetime.now(ZoneInfo("Asia/Kolkata"))

    return (
        f"Current date: {now.strftime('%Y-%m-%d')}\n"
        f"Current time: {now.strftime('%H:%M:%S')}\n"
        f"Day: {now.strftime('%A')}\n"
        f"Timezone: Asia/Kolkata"
    )
