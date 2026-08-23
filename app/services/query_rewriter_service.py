import json
import asyncio
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from langchain_core.messages import HumanMessage, SystemMessage
from langchain.agents import create_agent
from app.core.logger import logger


class RetrievalPlan(BaseModel):
    queries: List[str] = Field(..., description="List of 2 to 3 rewritten search queries from different perspectives.")
    keywords: List[str] = Field(default_factory=list, description="Key entity names, terms, or phrases extracted from the query.")


import re

def extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    cleaned = re.sub(r'<think>[\s\S]*?</think>', '', text, flags=re.IGNORECASE)
    cleaned = re.sub(r'<think>[\s\S]*$', '', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'(?:Here\'s a thinking process|Thinking Process):[\s\S]*?(?=\{|\[|\Z)', '', cleaned, flags=re.IGNORECASE)
    
    if "```" in cleaned:
        parts = cleaned.split("```")
        for part in parts:
            p = part.strip()
            if p.startswith("json"):
                p = p[4:].strip()
            first_b = p.find("{")
            last_b = p.rfind("}")
            if first_b != -1 and last_b != -1 and last_b > first_b:
                try:
                    return json.loads(p[first_b:last_b + 1])
                except Exception:
                    pass

    first_b = cleaned.find("{")
    last_b = cleaned.rfind("}")
    if first_b != -1 and last_b != -1 and last_b > first_b:
        try:
            return json.loads(cleaned[first_b:last_b + 1])
        except Exception:
            pass

    return None


class QueryRewriterService:
    """Service to construct query rewriting agents using LangChain and user LLM configuration."""

    async def rewrite_query(
        self,
        query: str,
        llm_config: Optional[Dict[str, Any]] = None,
        llm_model: Any = None
    ) -> RetrievalPlan:
        """
        Rewrites user search query into RetrievalPlan using LangChain agent and User LLM configuration.
        """
        query_clean = (query or "").strip()
        if not query_clean:
            return RetrievalPlan(queries=[], keywords=[])

        words = [w.strip() for w in query_clean.split() if len(w.strip()) > 2]
        fallback_plan = RetrievalPlan(
            queries=[query_clean],
            keywords=words
        )

        model = llm_model
        if model is None and llm_config and llm_config.get("api_key"):
            try:
                from app.services.agent_service import PROVIDER_REGISTRY
                config_type = llm_config.get("config_type", "provider")
                provider = (llm_config.get("provider") or "openai").lower()
                api_key = llm_config.get("api_key", "").strip()
                model_name = (llm_config.get("default_model") or llm_config.get("model") or "gpt-4o").strip()
                base_url = llm_config.get("base_url")

                if config_type == "custom" or provider not in PROVIDER_REGISTRY:
                    provider_fn = PROVIDER_REGISTRY.get("custom") or PROVIDER_REGISTRY.get("openai-compatible")
                else:
                    provider_fn = PROVIDER_REGISTRY.get(provider)

                if provider_fn:
                    model = provider_fn(
                        api_key=api_key,
                        model=model_name,
                        base_url=base_url,
                        temperature=0.3,
                        max_tokens=1000
                    )
            except Exception as err:
                logger.warning(f"Failed to instantiate User LLM model for Query Rewriter: {err}")

        if model is None:
            return fallback_plan

        system_prompt = (
            "You are an expert search query rewriter for a vector database retrieval system.\n"
            "Given a user query, generate 2 to 3 distinct search query variations and extract key entity keywords.\n"
            "Output ONLY a raw JSON object with keys 'queries' (list of strings) and 'keywords' (list of strings).\n"
            "DO NOT include any thinking process, reasoning, markdown tags, preamble, or explanations."
        )

        try:
            # Method 1: LangChain Structured Output via User LLM model
            structured_llm = model.with_structured_output(RetrievalPlan)
            plan = await structured_llm.ainvoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=f"User Query: \"{query_clean}\"")
            ])
            if isinstance(plan, RetrievalPlan) and plan.queries:
                if query_clean not in plan.queries:
                    plan.queries.insert(0, query_clean)
                return plan
        except Exception as exc:
            logger.warning(f"Structured output with User LLM model failed ({exc}). Retrying with LangChain create_agent...")

        try:
            # Method 2: LangChain create_agent fallback
            agent = create_agent(
                model=model,
                tools=[],
                system_prompt=system_prompt
            )
            res = await agent.ainvoke({"messages": [HumanMessage(content=f"User Query: \"{query_clean}\"")]})
            output_text = ""
            if isinstance(res, dict):
                output_text = res.get("output", "")
                if not output_text and "messages" in res:
                    output_text = res["messages"][-1].content

            if output_text:
                parsed = extract_json_object(output_text)
                if parsed and isinstance(parsed, dict):
                    queries = parsed.get("queries", [query_clean])
                    keywords = parsed.get("keywords", words)
                    if isinstance(queries, list) and queries:
                        if query_clean not in queries:
                            queries.insert(0, query_clean)
                        return RetrievalPlan(queries=queries, keywords=keywords if isinstance(keywords, list) else words)
        except Exception as agent_err:
            logger.warning(f"LangChain create_agent query rewriter failed: {agent_err}")

        return fallback_plan


query_rewriter = QueryRewriterService()
