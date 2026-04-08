# linkedin/ml/search_keywords.py
"""LLM-based generation of LinkedIn People search keywords."""
from __future__ import annotations

import logging

import jinja2
from pydantic import BaseModel, Field

from linkedin.conf import PROMPTS_DIR

logger = logging.getLogger(__name__)


class SearchKeywords(BaseModel):
    """Structured LLM output for search keyword generation."""
    keywords: list[str] = Field(description="List of LinkedIn People search queries")


def generate_search_keywords(
    product_docs: str,
    campaign_objective: str,
    n_keywords: int = 10,
    exclude_keywords: list[str] | None = None,
) -> list[str]:
    """Call LLM to generate LinkedIn search keywords from campaign context.

    Returns a list of search query strings.
    """
    from langchain_google_genai import ChatGoogleGenerativeAI
    from langchain_openai import ChatOpenAI

    from linkedin.conf import get_llm_config

    llm_api_key, ai_model, llm_api_base = get_llm_config()
    if not llm_api_key:
        raise ValueError("LLM_API_KEY is not set in Site Configuration.")

    env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(PROMPTS_DIR)))
    template = env.get_template("search_keywords.j2")

    prompt = template.render(
        product_docs=product_docs,
        campaign_objective=campaign_objective,
        n_keywords=n_keywords,
        exclude_keywords=exclude_keywords or [],
    )

    ai_model = "gemini-3.1-pro-preview"  # Hard-coded override per user request
    if "gemini" in ai_model.lower():
        llm = ChatGoogleGenerativeAI(
            model=ai_model,
            google_api_key=llm_api_key,
            temperature=0.9,
            timeout=60,
        )
    else:
        llm = ChatOpenAI(
            model=ai_model,
            temperature=0.9,
            api_key=llm_api_key,
            base_url=llm_api_base,
            timeout=60,
        )
    structured_llm = llm.with_structured_output(SearchKeywords)
    result = structured_llm.invoke(prompt)

    logger.info("Generated %d search keywords via LLM", len(result.keywords))
    return result.keywords
