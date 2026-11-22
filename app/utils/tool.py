import asyncio
from langchain_core.tools import tool
from langchain_community.utilities import DuckDuckGoSearchAPIWrapper
from app.services.qdrant_service import qdrant_service
from app.services.query_rewriter_service import query_rewriter
from app.core.logger import logger
from app.core.timeutil import now_local

from app.core.context import current_search_attempts

# Initialize DuckDuckGo API wrapper at module level
search_api = DuckDuckGoSearchAPIWrapper(max_results=5)

def reset_search_counter():
    """Reset the search attempt counter for the current user turn context."""
    current_search_attempts.set(0)


@tool
def web_search(query: str) -> str:
    """Search the public web for real-time external information, news, or internet data.

    Use this tool when the user's question requires current, external, or public internet information.

    Args:
        query: The search query to look up on the web.
    """
    try:
        logger.info(f"[WEB_SEARCH] Executing web search query: '{query}'")
        res = search_api.run(query)
        logger.info(f"[WEB_SEARCH] Returned web search result length: {len(res) if res else 0} chars")
        return res
    except Exception as e:
        logger.error(f"[WEB_SEARCH_ERROR] Error executing web search for '{query}': {e}")
        return f"Error executing web search: {str(e)}"


@tool
async def document_search(query: str) -> str:
    """
    Search the chatbot's private uploaded knowledge base.

    Uses semantic query rewriting, multi-query Qdrant retrieval,
    deduplication, and relevance ranking.

    Use when uploaded documents may contain information relevant
    to the user's request.
    """

    try:
        import json

        from app.core.context import (
            current_user_id,
            current_chatbot_id,
            current_llm_config,
            current_search_attempts,
        )
        from app.db.mongodb import db

        # User-turn level attempt management: isolated per asyncio task context
        attempts = current_search_attempts.get(0) + 1
        current_search_attempts.set(attempts)

        if attempts > 2:
            logger.warning(f"[DOC_SEARCH] Maximum 2 search attempts reached for this turn context (user={current_user_id.get(None)}). Blocking further search calls.")
            return (
                "RETRIEVAL_STATUS: LOW_CONFIDENCE\n"
                "RESULT_COUNT: 0\n"
                "TOP_SCORE: 0.0000\n\n"
                "Maximum search attempt limit (2 attempts) reached for this turn. Do NOT call document_search or web_search again. "
                "Inform the user clearly based on available facts or state that the uploaded documents do not contain the answer."
            )

        query_str = (query or "").strip()

        if not query_str:
            return (
                "RETRIEVAL_STATUS: ERROR\n"
                "No valid search query was provided."
            )

        # Handle structured JSON input from the LLM.
        if query_str.startswith("{"):
            try:
                parsed = json.loads(query_str)
                queries = parsed.get("queries")

                if isinstance(queries, list) and queries:
                    query_str = " ".join(
                        str(q).strip() for q in queries if q
                    )
            except (ValueError, AttributeError):
                pass

        user_id = current_user_id.get(None)
        chatbot_id = current_chatbot_id.get(None)
        llm_config = current_llm_config.get(None)

        if qdrant_service.mongo_db is None:
            qdrant_service.mongo_db = db.database

        logger.info(
            f"[DOC_SEARCH] Starting semantic retrieval: {query_str}"
        )

        # 1. Generate semantic retrieval plan.
        plan = await query_rewriter.rewrite_query(
            query_str,
            llm_config=llm_config,
        )

        queries_to_search = (
            plan.queries if plan and plan.queries else [query_str]
        )

        logger.info(
            f"[REWRITER] Generated {len(queries_to_search)} queries"
        )

        # 2. Search Qdrant in parallel.
        search_tasks = [
            qdrant_service.similarity_search(
                query=search_query,
                limit=5,
                chatbot_id=chatbot_id,
                user_id=None if chatbot_id else user_id,
            )
            for search_query in queries_to_search
        ]

        search_results = await asyncio.gather(
            *search_tasks,
            return_exceptions=True,
        )

        all_results = []

        for result in search_results:
            if isinstance(result, Exception):
                logger.error(
                    f"[QDRANT] Search query failed: {result}"
                )
                continue

            if isinstance(result, list):
                all_results.extend(result)

        logger.info(
            f"[QDRANT] Retrieved {len(all_results)} raw chunks"
        )

        if not all_results:
            return (
                "RETRIEVAL_STATUS: NO_RESULTS\n"
                "RESULT_COUNT: 0\n"
                "No matching document chunks were retrieved. "
                "The search did not establish whether the information "
                "exists elsewhere in the uploaded documents."
            )

        # 3. Deduplicate retrieved chunks.
        dedup_map = {}

        for item in all_results:
            content = (item.get("text") or "").strip()

            if not content:
                continue

            doc_key = content

            if doc_key not in dedup_map:
                dedup_map[doc_key] = {
                    "text": content,
                    "filename": item.get("filename", "Unknown"),
                    "document_id": item.get("document_id", ""),
                    "score": item.get("score", 0.0),
                }
            else:
                dedup_map[doc_key]["score"] = max(
                    dedup_map[doc_key]["score"],
                    item.get("score", 0.0),
                )

        # 4. Rank by retrieval relevance.
        reranked = list(dedup_map.values())

        reranked.sort(
            key=lambda item: item["score"],
            reverse=True,
        )

        top_results = reranked[:5]

        top_score = (
            top_results[0]["score"] if top_results else 0.0
        )

        logger.info(
            f"[RERANK] Unique chunks: {len(reranked)} | "
            f"Top score: {top_score}"
        )

        # 5. Return retrieved context.
        formatted_results = [
            "RETRIEVAL_STATUS: SUCCESS",
            f"RESULT_COUNT: {len(top_results)}",
            f"TOP_SCORE: {top_score}",
            "Retrieved document context follows:"
        ]

        for index, result in enumerate(top_results, start=1):
            formatted_results.append(
                f"""
RESULT {index}

Source: {result["filename"]}
Relevance score: {result["score"]}

Content:
{result["text"]}
"""
            )

        logger.info(
            f"[SUCCESS] Returning {len(top_results)} document chunks"
        )

        return "\n\n".join(formatted_results)

    except Exception as exc:
        logger.error(
            f"[DOC_SEARCH] Execution failed: {exc}",
            exc_info=True,
        )

        return (
            "RETRIEVAL_STATUS: ERROR\n"
            f"Search execution failed: {str(exc)}"
        )


@tool
def current_datetime() -> str:
    """Get the current date and time. Use this for current date/time questions."""
    
    now = now_local()

    return (
        f"Current date: {now.strftime('%Y-%m-%d')}\n"
        f"Current time: {now.strftime('%H:%M:%S')}\n"
        f"Day: {now.strftime('%A')}\n"
        f"Timezone: {now.tzinfo}"
    )


# Re-export appointment tools
from app.tools.appointment import book_appointment, check_appointment

__all__ = ["web_search", "document_search", "current_datetime", "book_appointment", "check_appointment", "reset_search_counter"]

