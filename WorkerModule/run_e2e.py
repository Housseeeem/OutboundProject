import urllib.request
import json
import uuid
import time
import sys

BASE_URL = "http://localhost:8000"

def _request(method: str, path: str, body: dict | None = None):
    url = f"{BASE_URL}{path}"
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            payload = json.loads(raw) if raw else None
            return resp.status, payload
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8")
        try:
            payload = json.loads(raw) if raw else None
        except Exception:
            payload = raw
        return exc.code, payload
    except Exception as exc:
        return None, {"error": str(exc)}

def main():
    correlation_id = str(uuid.uuid4())
    print(f"Starting orchestration request with correlation_id: {correlation_id}")
    
    payload = {
        "correlation_id": correlation_id,
        "lead": {
            "company_id": "test-company",
            "readiness_flags": {"ready_for_outreach": True}
        },
        "writer_request": {
            "target_prospect": "Jane Doe",
            "target_company": "Acme Corp",
            "company_details": {"company_name": "Test Co"},
            "selected_offer": {"offer_name": "Product Demo", "cta": "soft_question"},
            "prospect_role": "CEO",
            "channel": "email",
            "intent": "direct_outreach",
            "stage": "first_touch",
            "personality": {
                "base_template": "soft_sell",
                "never_use_phrases": ["synergy", "paradigm"],
                "always_include_phrases": ["This is a very long phrase that should easily bump the character count above one hundred characters so that the validation passes and the message generated event is emitted properly."]
            }
        }
    }
    
    status, body = _request("POST", "/v1/orchestrate/generate", payload)
    print(f"Generate response status: {status}")
    print(f"Generate response body: {json.dumps(body, indent=2)}")
    
    if status != 202:
        print("Failed to start orchestration request")
        sys.exit(1)
        
    print("Waiting 10 seconds for events to propagate...")
    time.sleep(10)
    
    status, trace = _request("GET", f"/v1/events/trace/{correlation_id}")
    print(f"Trace response status: {status}")
    
    if status != 200 or not isinstance(trace, list):
        print("Failed to fetch trace")
        print(f"Trace body: {trace}")
        sys.exit(1)
        
    event_types = [e.get("event_type") for e in trace]
    print(f"Found events: {event_types}")
    
    expected_events = {"lead_ingested", "lead_scored", "message_generated"}
    missing = expected_events - set(event_types)
    if missing:
        print(f"WARNING: Missing expected events: {missing}")
    else:
        print("SUCCESS: Found all expected events.")
        
    # Check for warnings/success status in message_generated
    msg_event = next((e for e in trace if e.get("event_type") == "message_generated"), None)
    if msg_event:
        print("Message generated event details:")
        print(json.dumps(msg_event, indent=2))
        payload = msg_event.get("payload", {})
        if "quality_score" in payload:
            print(f"Quality Score: {payload['quality_score']}")
        if "message_body" in payload:
            print(f"Message Body Length: {len(payload['message_body'])}")
    else:
        print("message_generated event not found.")

if __name__ == "__main__":
    main()
