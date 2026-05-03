import os
import asyncio
import json
from typing import TypedDict, List, Dict


from langgraph.graph import StateGraph, START, END
from langchain_groq import ChatGroq
from langchain_core.messages import SystemMessage

from mcp_client.client import MCPClient
from langchain_openai import ChatOpenAI
from utils.async_utils import run_async
from dotenv import load_dotenv

load_dotenv()
# ================= cONSOLE =================
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
class NewsState(TypedDict):
    company: str
    news_raw: dict
    news_clean: List[Dict]
    news_aggregated: List[Dict]
    news_final: List[Dict]       
    errors: List[str]
    mcp_client: any


# ================= LLM =================
# llm = ChatOpenAI(
#     model="nvidia/nemotron-3-super-120b-a12b:free",
#     api_key="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", # openrouter api
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
        # split the url by //, take the second part ([1])
        # split the second part by /, take the first part ([0])
        # remove www
        # ============= improvement : replace with urlparse library
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
    """Try to safely parse JSON output from LLM."""
    try:
        return json.loads(text)
    except:
        # fallback: try to extract JSON substring
        try:
            start = text.index("[")
            end = text.rindex("]") + 1
            return json.loads(text[start:end])
        except:
            return []


def validate_output(output, input_ids: List[str]):
    """Basic validation to avoid hallucinated structure."""
    valid = []

    for event in output:
        if not isinstance(event, dict):
            continue

        # must have supporting_ids
        ids = event.get("supporting_ids", [])
        if not isinstance(ids, list) or not ids:
            continue

        # ensure ids exist in input
        if not all(str(i) in input_ids for i in ids):
            continue

        valid.append(event)

    return valid



# ================= NODES =================
# ---- 1. FETCH ----
def fetch_news_node(state: NewsState):
    """Fetch news using shared MCP client"""
    client = state["mcp_client"]
    company = state["company"]

    print(f"[News] company: {company}")
    print("[News] About to call MCP tool (sync)...")

    try:
        # Use the synchronous wrapper
        raw = client.call_tool_sync(
            "search_company_news",
            {"company_name": company}
        )
        print("[News] MCP call successful!")
    except Exception as e:
        print(f"[News] ERROR in MCP call: {e}")
        import traceback
        traceback.print_exc()
        return {
            **state,
            "news_raw": {"result": []},
            "errors": state.get("errors", []) + [f"MCP call error: {str(e)}"]
        }

    debug("raw tool output", raw)
    parsed = parse_mcp_result(raw)

    return {
        **state,
        "news_raw": parsed
    }


# ---- 2. NORMALIZE ----
def normalize_node(state: NewsState):
    """ normalize format and add source, id """
    clean = []
    raw = state["news_raw"]

    # STEP 1: ensure we always get a list
    if isinstance(raw, dict):
        results = raw.get("result", [])
    else:
        results = raw

    # STEP 2: unwrap nested lists if needed
    flat_results = []
    for r in results:
        if isinstance(r, list):
            flat_results.extend(r)
        else:
            flat_results.append(r)

    # STEP 3: safe parsing
    for i, r in enumerate(flat_results):
        if not isinstance(r, dict):
            continue  # skip bad items

        clean.append({
            "id": i,
            "title": r.get("title", "")[:200],
            "snippet": r.get("snippet", "")[:500],
            "url": r.get("url", ""),
            "source": r.get("source", ""),
            "date": r.get("date"),
            "flag": "news"
        })

    debug("extracting source, adding id and flag (clean) ", clean)
    # print(f"=== llm input : {clean}")

    return {
        **state,
        "news_clean": clean
    }




# ================= FINAL OUTPUT NODE =================
def aggregation_node(state: Dict):
    """ aggregate news into unique (llm) """
    print("LLM aggregating news")
    # events = state.get("news_clean", [])
    company = state.get("company", "")

    minimal_input = [
        {
            "id": r["id"],
            "title": r["title"],
            "snippet": r["snippet"],
            "source": r["source"]
        }
        for r in state["news_clean"]
    ]
    if not minimal_input:
        return {**state, "news_clean": []}

    # limit input size
    minimal_input = minimal_input[:10]

    input_ids = [str(e["id"]) for e in minimal_input]

    prompt = f"""
You are a news clustering system.

Group news articles that describe the same real-world event related to this company: {company}.

INPUT:
{json.dumps(minimal_input, indent=2)}

TASKS:

1. COMPANY FILTERING
- Only consider articles that are primarily about the specified company
- The company must be a central subject, not just mentioned in passing


2. CLUSTERING
- Group articles referring to the same event
- Same event = same incident/announcement/development
- Do NOT mix unrelated news

3. OUTPUT PER CLUSTER
Return one object per event:

- event_title: clear general title of the event
- supporting_ids: all article IDs in the cluster
- source: BEST single source from within the cluster (most credible/authoritative)
- event_confidence:
  0.8–1.0 strong agreement
  0.5–0.8 partial agreement
  <0.5 weak match

4. RULES
- Use only given articles
- Do NOT invent data
- Each article appears in exactly one group
- source must come from grouped articles only

Return ONLY valid JSON list:
[
  {{
    "event_title": "",
    "event_confidence": 0.0,
    "source": "",
    "supporting_ids": []
  }}
]
"""

    # ===== LLM CALL WITH RETRY =====
    response = None
    for _ in range(2):  # retry once if parsing fails
        response = llm.invoke([SystemMessage(content=prompt)])
        parsed = safe_json_parse(response.content)

        if parsed:
            break

    if not response:
        return {**state, "news_clean": []}

    parsed = safe_json_parse(response.content)

    # ===== VALIDATION =====
    validated = validate_output(parsed, input_ids)
    debug("aggregation output", validated)

    return {
        **state,
        "news_aggregated": validated
    }



def finalize_node(state):
    print("\n================ FINALIZE NODE ================")

    aggregated = state.get("news_aggregated", [])
    original = state.get("news_clean", [])

    print(f"[DEBUG] aggregated events: {len(aggregated)}")
    print(f"[DEBUG] original articles: {len(original)}")

    if not aggregated:
        print("[ERROR] news_aggregated is EMPTY → LLM step failed or got filtered out")

    final = []

    # build lookup map for speed
    by_id = {str(r["id"]): r for r in original}

    print(f"[DEBUG] lookup map size: {len(by_id)}")

    for idx, event in enumerate(aggregated):
        print(f"\n--- EVENT {idx} ---")
        print("[DEBUG] event:", event)

        ids = event.get("supporting_ids", [])
        chosen_source = event.get("source")

        print(f"[DEBUG] supporting_ids: {ids}")
        print(f"[DEBUG] chosen_source: {chosen_source}")

        # 1. get all articles in this cluster
        candidates = [
            by_id[str(i)] for i in ids if str(i) in by_id
        ]

        print(f"[DEBUG] candidates found: {len(candidates)}")

        if not candidates:
            print("[WARNING] No candidates found for event → skipping")
            continue

        # 2. pick article matching chosen source
        match = [
            r for r in candidates
            if r.get("source") == chosen_source
        ]

        print(f"[DEBUG] matches for chosen source: {len(match)}")

        # fallback if mismatch
        chosen = match[0] if match else candidates[0]

        print(f"[DEBUG] chosen article: {chosen}")

        # 3. attach metadata
        final_item = {
            "title": event.get("event_title"),
            "event_confidence": event.get("event_confidence"),
            "source": chosen_source,
            "url": chosen.get("url"),
            "date": chosen.get("date"),
            "flag": "news"
        }

        print(f"[DEBUG] final item: {final_item}")

        final.append(final_item)

    print("\n================ FINAL OUTPUT READY ================")
    print(f"[DEBUG] total final events: {len(final)}")

    return {
        **state,
        "news_final": final
    }

# ================= BUILD GRAPH =================
def build_news_graph():
    graph = StateGraph(NewsState)

    graph.add_node("fetch", fetch_news_node)
    graph.add_node("normalize", normalize_node)
    graph.add_node("aggregate", aggregation_node)
    graph.add_node("finalize", finalize_node)
    

    graph.add_edge(START, "fetch")
    graph.add_edge("fetch", "normalize")
    graph.add_edge("normalize", "aggregate")
    graph.add_edge("aggregate", "finalize")
    graph.add_edge("finalize", END)
    

    return graph.compile()


