import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo
from langchain_core.tools import tool
from langchain_community.utilities import DuckDuckGoSearchAPIWrapper
from app.services.qdrant_service import qdrant_service
from app.services.query_rewriter_service import query_rewriter
from app.core.logger import logger

# Initialize DuckDuckGo API wrapper at module level
search_api = DuckDuckGoSearchAPIWrapper(max_results=5)

_search_attempts = 0

def reset_search_counter():
    global _search_attempts
    _search_attempts = 0


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
    Search the chatbot's private uploaded knowledge base and documents.

    Use this tool when the user's question may require information from uploaded documents such as PDFs, resumes, reports, policies, company information, products, or other private knowledge.

    The tool performs query rewriting, multi-query retrieval, Qdrant vector search, deduplication, reranking, and relevance evaluation.

    If the returned RETRIEVAL_STATUS is LOW_CONFIDENCE, consider calling this tool again with a more specific, rephrased, or alternative search query.

    Args:
        query: The semantic search query to look up in uploaded documents.
    """

    try:
        global _search_attempts
        _search_attempts += 1

        if _search_attempts > 2:
            logger.warning(f"[DOC_SEARCH] Maximum 2 search attempts reached for this turn. Blocking further search calls.")
            return (
                "RETRIEVAL_STATUS: LOW_CONFIDENCE\n"
                "RESULT_COUNT: 0\n"
                "TOP_SCORE: 0.0000\n\n"
                "Maximum search attempt limit (2 attempts) reached for this turn. Do NOT call document_search or web_search again. "
                "Inform the user clearly based on available facts or state that the uploaded documents do not contain the answer."
            )

        from app.core.context import current_user_id, current_chatbot_id, current_llm_config
        from app.db.mongodb import db
        import json

        logger.info(f"[DOC_SEARCH] Executed by Agent (attempt {_search_attempts}) with query: '{query}'")

        # Clean query if LLM agent passed a raw JSON object string
        query_str = (query or "").strip()
        if query_str.startswith("{") and "queries" in query_str:
            try:
                parsed_q = json.loads(query_str)
                if isinstance(parsed_q, dict):
                    qs = parsed_q.get("queries")
                    if isinstance(qs, list) and qs:
                        query_str = str(qs[0])
                        logger.info(f"[DOC_SEARCH] Extracted clean query string from JSON input: '{query_str}'")
            except Exception:
                pass

        user_id = current_user_id.get(None)
        chatbot_id = current_chatbot_id.get(None)
        llm_config = current_llm_config.get(None)

        if qdrant_service.mongo_db is None:
            try:
                qdrant_service.mongo_db = db.database
            except Exception:
                pass

        # 1. Query Rewriter: Generate retrieval plan with multi-query variations & keywords using User LLM Config
        plan = await query_rewriter.rewrite_query(query_str, llm_config=llm_config)
        queries_to_search = plan.queries if plan and plan.queries else [query_str]
        keywords = [k.lower() for k in (plan.keywords if plan and plan.keywords else [])]

        logger.info(f"[REWRITER] Retrieval Plan | Queries to search: {queries_to_search} | Keywords: {keywords}")

        # 2. Parallel Qdrant Search for all query variations
        search_tasks = [
            qdrant_service.similarity_search(
                query=search_q,
                limit=5,
                chatbot_id=chatbot_id,
                user_id=None if chatbot_id else user_id,
            )
            for search_q in queries_to_search
        ]

        search_results_list = await asyncio.gather(*search_tasks, return_exceptions=True)

        all_results = []
        for res in search_results_list:
            if isinstance(res, list):
                all_results.extend(res)

        logger.info(f"[QDRANT] Raw matches retrieved: {len(all_results)} total chunks across {len(queries_to_search)} queries")

        if not all_results:
            logger.warning(f"[LOW_CONFIDENCE] 0 vector matches returned from Qdrant for query: '{query_str}'")
            return (
                "RETRIEVAL_STATUS: LOW_CONFIDENCE\n"
                "RESULT_COUNT: 0\n"
                "TOP_SCORE: 0.0000\n\n"
                "No relevant information was found in the uploaded documents.\n\n"
                "INSTRUCTION FOR ASSISTANT: Do NOT call document_search again. "
                "If the query asks about real-world facts, a person, or a company, execute web_search ONCE now. Otherwise, state clearly that the uploaded documents do not contain this information."
            )

        # 3. Deduplicate & Rerank Results
        dedup_map = {}
        for item in all_results:
            text = (item.get("text") or "").strip()
            if not text:
                continue
            
            doc_key = text[:150]
            if doc_key not in dedup_map:
                dedup_map[doc_key] = {
                    "text": item.get("text", ""),
                    "filename": item.get("filename", "Unknown"),
                    "document_id": item.get("document_id", ""),
                    "scores": [item.get("score", 0.0)],
                    "frequency": 1
                }
            else:
                dedup_map[doc_key]["scores"].append(item.get("score", 0.0))
                dedup_map[doc_key]["frequency"] += 1

        # Calculate reranked scores with domain & employment pattern boost
        is_work_query = any(w in query_str.lower() for w in ["work", "job", "previous", "company", "employer", "experience", "past", "history", "role", "where"])

        reranked = []
        for key, item in dedup_map.items():
            base_score = max(item["scores"])
            freq_boost = (item["frequency"] - 1) * 0.05
            
            content_lower = item["text"].lower()
            filename_lower = item["filename"].lower()
            kw_boost = 0.0
            for kw in keywords:
                if kw in content_lower or kw in filename_lower:
                    kw_boost += 0.08

            # Work & Employment pattern boost for job/career queries
            if is_work_query:
                emp_terms = ["developer", "engineer", "designer", "manager", "sde", "pvt", "ltd", "inc", "remote", "technologies", "experience", "present", "jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
                emp_count = sum(1 for t in emp_terms if t in content_lower)
                if emp_count >= 2:
                    kw_boost += min(0.25, emp_count * 0.05)
            
            final_score = base_score + freq_boost + kw_boost
            item["final_score"] = final_score
            reranked.append(item)

        # Sort descending by final_score
        reranked.sort(key=lambda x: x["final_score"], reverse=True)

        top_score = reranked[0]["final_score"] if reranked else 0.0
        RELEVANCE_THRESHOLD = 0.20

        logger.info(f"[RERANK] Reranking complete | Candidate docs: {len(reranked)} | Top score: {top_score:.4f} | Threshold: {RELEVANCE_THRESHOLD}")

        if top_score < RELEVANCE_THRESHOLD:
            logger.warning(f"[LOW_CONFIDENCE] Top score {top_score:.4f} is below threshold {RELEVANCE_THRESHOLD}")
            return (
                f"RETRIEVAL_STATUS: LOW_CONFIDENCE\n"
                f"RESULT_COUNT: {len(reranked)}\n"
                f"TOP_SCORE: {top_score:.4f}\n\n"
                f"The retrieved documents do not contain sufficiently relevant information for this query.\n\n"
                f"INSTRUCTION FOR ASSISTANT: Do NOT call document_search again. "
                f"If the query asks about real-world facts, a person, or a company, execute web_search ONCE now. Otherwise, state clearly that the uploaded documents do not contain this information."
            )

        top_results = reranked[:5]
        sources_summary = ", ".join([f"'{r.get('filename')}' (score: {r.get('final_score', 0):.4f})" for r in top_results])
        logger.info(f"[SUCCESS] RETRIEVAL_STATUS: SUCCESS | Top score: {top_score:.4f} | Returning {len(top_results)} results | Sources: [{sources_summary}]")

        # 4. Format Top Context for LLM
        formatted_results = [
            f"RETRIEVAL_STATUS: SUCCESS\n"
            f"RESULT_COUNT: {len(top_results)}\n"
            f"TOP_SCORE: {top_score:.4f}"
        ]
        for index, result in enumerate(top_results, start=1):
            formatted_results.append(
                f"""RESULT {index}
Source: {result.get("filename", "Unknown")}
Relevance score: {result.get("final_score", 0):.4f}

Content:
{result.get("text", "")}"""
            )

        formatted_results.append(
            "INSTRUCTION FOR ASSISTANT: You now have sufficient relevant information from the uploaded documents. "
            "Do NOT call any more tools (neither document_search nor web_search). Answer the user's question directly now using this content."
        )

        return "\n\n".join(formatted_results)

    except Exception as exc:
        logger.error(f"❌ [document_search] Execution failed with exception: {exc}", exc_info=True)
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
