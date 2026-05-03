import os
import asyncio
import json
from typing import TypedDict, List, Dict, Any
from langchain_groq import ChatGroq

from langgraph.graph import StateGraph, START, END
from langchain_core.messages import SystemMessage
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv

load_dotenv()
# ================= CONSOLE =================
def debug(title, obj):
    print("\n" + "="*30)
    print(title)
    print("="*30)
    try:
        print(json.dumps(obj, indent=2, ensure_ascii=False))
    except:
        from pprint import pprint
        pprint(obj)


# ================= STATE ================= 
class FundingState(TypedDict):
    company: str
    funding_raw: dict
    funding_clean: List[Dict]
    funding_llm_output: Dict
    funding_final: List[Dict]
    funding_aggregated: List[Dict]       
    funding_aggregated_final: List[Dict]
    errors: List[str]
    mcp_client: Any


# ================= LLM =================
# llm = ChatOpenAI(
#     # model="nvidia/nemotron-3-super-120b-a12b:free",
#     model = "google/gemma-4-26b-a4b-it:free",
#     api_key="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",
#     base_url="https://openrouter.ai/api/v1"
# )


llm = ChatGroq(
    model=os.getenv("MODEL_NAME", "llama-3.3-70b-versatile"),
    temperature=0.1,
    max_tokens=2048,
)

# ================= HELPERS =================
def extract_domain(url: str) -> str:
    try:
        return url.split("//")[1].split("/")[0].replace("www.", "")
    except:
        return "unknown"


def parse_mcp_result(result):
    try:
        texts = [r.text for r in result if hasattr(r, "text")]
        combined = "".join(texts)  
        return json.loads(combined)
    except Exception as e:
        print("Parse error:", e)
        return {"result": []}


# ================= FINAL OUTPUT HELPERS =================
def safe_json_parse(text: str):
    try:
        return json.loads(text)
    except:
        try:
            start = text.index("[")
            end = text.rindex("]") + 1
            return json.loads(text[start:end])
        except:
            return []


def validate_output(output, input_ids: List[str]):
    valid = []
    for event in output:
        if not isinstance(event, dict):
            continue
        ids = event.get("supporting_ids", [])
        if not isinstance(ids, list) or not ids:
            continue
        if not all(str(i) in input_ids for i in ids):
            continue
        valid.append(event)
    return valid


# ================= NODES =================
# ---- 1. FETCH (now sync but using the mcp_client directly) ----
def fetch_funding_node(state: FundingState):
    client = state["mcp_client"]
    company = state["company"]

    print(f"[Funding] company: {company}")
    print(f"[Funding] client type: {type(client)}")
    print(f"[Funding] has session: {client.session is not None if client else False}")

    print("[Funding] About to call MCP tool (sync)...")
    
    try:
        # Use the synchronous wrapper instead of async
        raw = client.call_tool_sync(
            "search_company_funding",
            {"company_name": company}
        )
        print("[Funding] MCP call successful!")
        print(f"[Funding] Raw result type: {type(raw)}")
        print(f"[Funding] Raw result length: {len(raw) if raw else 0}")
        
    except Exception as e:
        print(f"[Funding] ERROR in MCP call: {e}")
        import traceback
        traceback.print_exc()
        return {
            **state,
            "funding_raw": {"result": []},
            "errors": state.get("errors", []) + [f"MCP call error: {str(e)}"]
        }

    debug("raw tool output", raw)
    parsed = parse_mcp_result(raw)
    print(f"[Funding] Parsed result type: {type(parsed)}")

    return {
        **state,
        "funding_raw": parsed
    }


# ---- 2. NORMALIZE ----
def normalize_node(state: FundingState):
    clean = []
    raw = state["funding_raw"]

    if isinstance(raw, dict):
        results = raw.get("result", [])
    else:
        results = raw

    flat_results = []
    for r in results:
        if isinstance(r, list):
            flat_results.extend(r)
        else:
            flat_results.append(r)

    for i, r in enumerate(flat_results):
        if not isinstance(r, dict):
            continue
        clean.append({
            "id": i,
            "title": r.get("title", "")[:200],
            "snippet": r.get("snippet", "")[:500],
            "url": r.get("url", ""),
            "source": extract_domain(r.get("url", "")),
            "flag": "funding"
        })

    debug("extracting source, adding id and flag (clean) ", clean)
    return {
        **state,
        "funding_clean": clean
    }


# ---- 3. LLM EXTRACTION ----
def llm_extraction_node(state: FundingState):
    minimal_input = [
        {
            "id": r["id"],
            "title": r["title"],
            "snippet": r["snippet"]
        }
        for r in state["funding_clean"]
    ]
    debug("minimal input", minimal_input)

    prompt = f"""
You are an information extraction system.

Company: {state["company"]}

Input:
{json.dumps(minimal_input, indent=2)}

For each element:

- If NOT related to the company → return: id: null
- If related → return:
  id: {{
    "date": "dd/mm/yyyy or None",
    "investor": "name or None",
    "amount": "value or None"
  }}

Return ONLY JSON like:
{{
  "0": {{...}},
  "1": null
}}
"""

    response = llm.invoke([SystemMessage(content=prompt)])
    debug("response object", response)
    print(f"==== raw llm response: {response.content}")
    print(f" input tokens : {response.usage_metadata['input_tokens']}")
    print(f"output tokens : {response.usage_metadata['output_tokens']}")
    print(f"total : {response.usage_metadata['total_tokens']}")

    try:
        parsed = safe_json_parse(response.content)
    except:
        parsed = {}

    return {
        **state,
        "funding_llm_output": parsed
    }


# ---- 4. MERGE ----
def merge_node(state: FundingState):
    final = []
    llm_data = state.get("funding_llm_output", {})
    clean = state.get("funding_clean", [])

    for r in clean:
        idx = str(r["id"])
        
        if idx not in llm_data:
            continue
        
        if llm_data[idx] is None:
            continue
            
        extracted = llm_data[idx]
        
        # Normalize values - convert "None" strings to None
        date_val = extracted.get("date")
        investor_val = extracted.get("investor")
        amount_val = extracted.get("amount")
        
        if date_val in ("None", "null", ""):
            date_val = None
        if investor_val in ("None", "null", ""):
            investor_val = None
        if amount_val in ("None", "null", ""):
            amount_val = None
        
        # Only skip if ALL fields are None AND investor is None
        # (an event with just an investor name IS still a funding event)
        if not date_val and not investor_val and not amount_val:
            continue
        
        final.append({
            "id": idx,
            "title": r["title"],
            "source": r["source"],
            "url": r["url"],
            "snippet": r["snippet"],
            "date": date_val if date_val else "None",
            "investor": investor_val if investor_val else "None",
            "amount": amount_val if amount_val else "None",
            "flag": "funding"
        })

    print(f"[MERGE] {len(clean)} articles -> {len(final)} funding events kept")
    
    return {
        **state,
        "funding_final": final
    }


# ================= FINAL OUTPUT NODES =================
def aggregation_node(state: Dict):
    print("LLM aggregating events")
    
    
    events = state.get("funding_final", [])
    company = state.get("company", "")

    if not events:
        return {**state, "funding_aggregated": []}

    events = events[:10]
    input_ids = [str(e["id"]) for e in events]

    prompt = f"""
You are a financial data extraction system. Your task is to identify and group funding events for this company : {company}.

INPUT:
{json.dumps(events, indent=2)}

RULES:
1. Group news articles that describe the SAME funding round/event
2. Each unique funding event = 1 output object
3. Use ONLY information from the provided articles
4. If a detail is not mentioned, set it to null (not "None" string, not "Unknown")
5. Every article ID must appear in exactly ONE group (no duplicates, no orphans)

OUTPUT FORMAT - Return a JSON list of objects:
[
  {{
    "event_title": "Brief descriptive title of this funding event",
    "event_confidence": 0.0 to 1.0 (0.9+ if multiple sources agree, 0.5-0.8 if partial match, <0.5 if uncertain),
    "source": "single most authoritative source name from the grouped articles",
    "supporting_ids": ["id1", "id2"],
    "date": "extracted date or null",
    "date_confidence": 0.0 to 1.0,
    "investor": "investor name(s) or null",
    "investor_confidence": 0.0 to 1.0,
    "amount": "funding amount with currency or null",
    "amount_confidence": 0.0 to 1.0
  }}
]

Return ONLY the JSON array, nothing else.
"""

    response = None
    for _ in range(2):
        response = llm.invoke([SystemMessage(content=prompt)])
        parsed = safe_json_parse(response.content)
        if parsed:
            break

    if not response:
        return {**state, "funding_aggregated": []}

    debug("raw response", response.content)
    parsed = safe_json_parse(response.content)
    debug("response after parsing", parsed)
    validated = validate_output(parsed, input_ids)
    debug("aggregation output", validated)

    return {
        **state,
        "funding_aggregated": validated
    }


def finalize_node(state):
    aggregated = state.get("funding_aggregated", [])
    original = state.get("funding_final", [])

    final = []
    for event in aggregated:
        ids = event.get("supporting_ids", [])
        chosen_url = None
        for i in ids:
            for r in original:
                if str(r["id"]) == str(i):
                    chosen_url = r["url"]
                    break
            if chosen_url:
                break

        final.append({
            "title": event.get("event_title"),
            "event_confidence": event.get("event_confidence"),
            "source": event.get("source"),
            "url": chosen_url,
            "date": event.get("date"),
            "date_confidence": event.get("date_confidence"),
            "investor": event.get("investor"),
            "investor_confidence": event.get("investor_confidence"),
            "amount": event.get("amount"),
            "amount_confidence": event.get("amount_confidence"),
            "flag": "funding"
        })

    return {
        **state,
        "funding_aggregated_final": final
    }


# ================= BUILD GRAPH =================
def build_funding_graph():
    graph = StateGraph(FundingState)

    graph.add_node("fetch", fetch_funding_node)
    graph.add_node("normalize", normalize_node)
    graph.add_node("extract", llm_extraction_node)
    graph.add_node("merge", merge_node)
    graph.add_node("aggregate", aggregation_node)
    graph.add_node("finalize", finalize_node)

    graph.add_edge(START, "fetch")
    graph.add_edge("fetch", "normalize")
    graph.add_edge("normalize", "extract")
    graph.add_edge("extract", "merge")
    graph.add_edge("merge", "aggregate")
    graph.add_edge("aggregate", "finalize")
    graph.add_edge("finalize", END)

    return graph.compile()