from fastmcp import FastMCP
from ddgs import DDGS
from dotenv import load_dotenv
import os
import json
import sys


load_dotenv()

mcp = FastMCP("intent-tools")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "idempotentHint": False,
        "destructiveHint": False,
        "openWorldHint": True
    }
)
def search_company_funding(company_name: str) -> list:
    """
    Search for recent news about a company related to funding.

    Args:
        company_name: Name of the company

    Returns:
        List of top 5 news results with title, url, snippet
    """
    query = f"{company_name} funding"

    results_list = []

    try:
        with DDGS() as ddgs:
            results = ddgs.text(query, max_results=5)

            for r in results:
                results_list.append({
                    "title": r.get("title"),
                    "url": r.get("href"),
                    "snippet": r.get("body")
                })

    except Exception as e:
        return [{"error": str(e)}]

    return results_list



@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "idempotentHint": False,
        "destructiveHint": False,
        "openWorldHint": True
    }
)
def search_company_partnerships(company_name: str) -> list:
    """
    Search for recent news about a company related to partnerships.

    Args:
        company_name: Name of the company

    Returns:
        List of top 5 news results with title, url, snippet
    """
    query = f"{company_name} partnership"

    results_list = []

    try:
        with DDGS() as ddgs:
            results = ddgs.text(query, max_results=5)

            for r in results:
                results_list.append({
                    "title": r.get("title"),
                    "url": r.get("href"),
                    "snippet": r.get("body")
                })

    except Exception as e:
        return [{"error": str(e)}]

    return results_list



@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "idempotentHint": False,
        "destructiveHint": False,
        "openWorldHint": True
    }
)
def search_company_news(company_name: str) -> list:
    """
    Search for recent general news about a company.

    Args:
        company_name: Name of the company

    Returns:
        List of top 5 news results with title, url, date, snippet, source
    """
    query = f"{company_name} news"

    results_list = []

    try:
        with DDGS() as ddgs:
            results = ddgs.news(query, max_results=5)

            for r in results:
                results_list.append({
                    "title": r.get("title"),
                    "url": r.get("url"),
                    "snippet": r.get("body"),
                    "date": r.get("date"),
                    "source": r.get("source")
                })

    except Exception as e:
        return [{"error": str(e)}]

    return results_list


@mcp.tool(
    annotations={
        "readOnlyHint": True,
        "idempotentHint": True,
        "destructiveHint": False,
        "openWorldHint": True
    }
)
def retrieve_company_intent(company_name: str, format_type: str = "llm_context") -> str:
    """
    Retrieve stored intelligence about a company. 
    Use this to get context before answering questions about the company.
    
    Args:
        company_name: Name of the company
        format_type: Format of the output - 'llm_context' (optimized for LLM), 
                    'full_data' (complete JSON), or 'summary' (brief summary)
    
    Returns:
        Company intelligence in the requested format
    """
    
    from utils.intent_store import IntentStore
    intent_store = IntentStore()

    if format_type == "llm_context":
        return intent_store.get_llm_context(company_name)
    elif format_type == "full_data":
        data = intent_store.retrieve_intent(company_name, "all")
        return json.dumps(data, indent=2, default=str)
    elif format_type == "summary":
        data = intent_store.retrieve_intent(company_name, "long_term")
        memories = data.get("long_term", [])
        if memories:
            return "\n".join([m["content"] for m in memories])
        return f"No stored memories for {company_name}"
    else:
        return intent_store.get_llm_context(company_name)

if __name__ == "__main__":
    mcp.run()