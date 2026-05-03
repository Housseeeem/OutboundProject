import asyncio
import json
from datetime import datetime
from graph.funding_graph import build_funding_graph
from graph.news_graph import build_news_graph
from mcp_client.client import MCPClient
from utils.intent_store import IntentStore


# build graphs
funding_graph = build_funding_graph()
news_graph = build_news_graph()

COMPANIES = ["France Télévisions"]


async def init_client():
    print(" Initializing MCP client...")
    
    client = MCPClient()
    print(" Connecting to MCP server...")
    await client.connect("mcp_server/mcp_server.py")
    print(" MCP client connected!")
    return client


async def run_company(company: str, client):
    """Run both graphs for a company sequentially in the same event loop"""
    print(f"\nProcessing {company}...")
    
    def invoke_graph(graph, state):
        """Invoke graph synchronously"""
        return graph.invoke(state)
    
    # Run funding graph
    print(f"[{company}] Starting funding graph...")
    funding_result = await asyncio.get_running_loop().run_in_executor(
        None,
        invoke_graph,
        funding_graph,
        {"company": company, "mcp_client": client}
    )
    print(f"[{company}] Funding graph completed")
    
    # Run news graph
    print(f"[{company}] Starting news graph...")
    news_result = await asyncio.get_running_loop().run_in_executor(
        None,
        invoke_graph,
        news_graph,
        {"company": company, "mcp_client": client}
    )
    print(f"[{company}] News graph completed")

    return {
        "company": company,
        "funding": funding_result.get("funding_aggregated_final", []),
        "news": news_result.get("news_final", [])
    }


def create_structured_output(results):
    """Create a well-structured output from the results"""
    
    # Create timestamp
    timestamp = datetime.now().isoformat()
    
    # Build the main data structure
    structured_data = {
        "metadata": {
            "generated_at": timestamp,
            "total_companies": len(results),
            "companies_analyzed": [r["company"] for r in results]
        },
        "companies": {}
    }
    
    # Process each company's results
    for result in results:
        company_name = result["company"]
        
        # Structure funding data
        funding_data = []
        for funding in result["funding"]:
            funding_data.append({
                "event": {
                    "title": funding.get("title", ""),
                    "confidence": funding.get("event_confidence", 0.0)
                },
                "financial_details": {
                    "amount": funding.get("amount", "Unknown"),
                    "amount_confidence": funding.get("amount_confidence", 0.0),
                    "investor": funding.get("investor", "Unknown"),
                    "investor_confidence": funding.get("investor_confidence", 0.0)
                },
                "date": {
                    "value": funding.get("date", "Unknown"),
                    "confidence": funding.get("date_confidence", 0.0)
                },
                "source": {
                    "name": funding.get("source", ""),
                    "url": funding.get("url", "")
                },
                "type": funding.get("flag", "funding")
            })
        
        # Structure news data
        news_data = []
        for news in result["news"]:
            news_data.append({
                "event": {
                    "title": news.get("title", ""),
                    "confidence": news.get("event_confidence", 0.0)
                },
                "source": {
                    "name": news.get("source", ""),
                    "url": news.get("url", "")
                },
                "date": news.get("date", "Unknown"),
                "type": news.get("flag", "news")
            })
        
        # Add to main structure
        structured_data["companies"][company_name] = {
            "funding_events": funding_data,
            "news_events": news_data,
            "summary": {
                "total_funding_events": len(funding_data),
                "total_news_events": len(news_data),
                "high_confidence_funding": len([f for f in funding_data if f["event"]["confidence"] >= 0.7]),
                "high_confidence_news": len([n for n in news_data if n["event"]["confidence"] >= 0.7])
            }
        }
    
    return structured_data


def save_output(structured_data, filename=None):
    """Save the structured data to a JSON file"""
    if filename is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"company_intel_{timestamp}.json"
    
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(structured_data, f, indent=2, ensure_ascii=False)
    
    print(f"\nOutput saved to: {filename}")
    return filename


def print_formatted_output(structured_data):
    """Print the structured data in a readable format"""
    print("\n" + "="*80)
    print("Final output object")
    print("="*80)
    print(f"Generated at: {structured_data['metadata']['generated_at']}")
    print(f"Companies analyzed: {', '.join(structured_data['metadata']['companies_analyzed'])}")
    
    for company_name, data in structured_data["companies"].items():
        print("\n" + "-"*80)
        print(f" {company_name.upper()}")
        print("-"*80)
        
        # Print summary
        summary = data["summary"]
        print(f"\nSummary:")
        print(f"  • Funding Events: {summary['total_funding_events']} ({summary['high_confidence_funding']} high confidence)")
        print(f"  • News Events: {summary['total_news_events']} ({summary['high_confidence_news']} high confidence)")
        
        # Print funding events
        if data["funding_events"]:
            print(f"\n FUNDING EVENTS:")
            for i, event in enumerate(data["funding_events"], 1):
                print(f"\n  {i}. {event['event']['title']}")
                print(f"     Confidence: {event['event']['confidence']:.0%}")
                if event["financial_details"]["amount"] != "Unknown":
                    print(f"     Amount: {event['financial_details']['amount']} (confidence: {event['financial_details']['amount_confidence']:.0%})")
                if event["financial_details"]["investor"] != "Unknown":
                    print(f"     Investor: {event['financial_details']['investor']}")
                print(f"     Source: {event['source']['name']}")
                if event['source']['url']:
                    print(f"     URL: {event['source']['url']}")
        
        # Print news events
        if data["news_events"]:
            print(f"\n NEWS EVENTS:")
            for i, event in enumerate(data["news_events"], 1):
                print(f"\n  {i}. {event['event']['title']}")
                print(f"     Confidence: {event['event']['confidence']:.0%}")
                print(f"     Source: {event['source']['name']} | Date: {event.get('date', 'Unknown')}")
                if event['source']['url']:
                    print(f"     URL: {event['source']['url']}")
    
    print("\n" + "="*80)


async def main(companies=None, save_to_file=True):
    if companies is None:
        companies = COMPANIES

    client = await init_client()

    try:
        results = []
        for company in companies:
            result = await run_company(company, client)
            results.append(result)
    except Exception as e:
        print(f"Error during processing: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("Shutting down...")
        try:
            await client.close()
        except Exception as e:
            print(f"Shutdown error: {e}")

    # Create structured output
    if 'results' in locals() and results:
        structured_data = create_structured_output(results)
        intent_store = IntentStore()
        intent_store.store_intent(structured_data)

        # Print formatted output
        print_formatted_output(structured_data)
        
        # Save to file
        if save_to_file:
            filename = save_output(structured_data)
            print(f"\nData structure is available in the variable 'structured_data'")
            print(f"Example access: structured_data['companies']['Tesla']['funding_events']")
        
        return structured_data
    
    return None


if __name__ == "__main__":
    intent_result = asyncio.run(main())
    print("\n\nRAW DATA STRUCTURE:")    
    print(json.dumps(intent_result, indent=2, default=str))