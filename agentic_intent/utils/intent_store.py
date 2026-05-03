import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional
import sqlite3
from contextlib import contextmanager


class IntentStore:
    """Manages short-term and long-term memory for company intents"""
    
    def __init__(self, db_path="intents.db"):
        self.db_path = db_path
        self.init_db()
    
    @contextmanager
    def get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
    
    def init_db(self):
        """Initialize database tables"""
        with self.get_connection() as conn:
            # Short-term memory: Recent events (last 7 days)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS short_term_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company TEXT NOT NULL,
                    event_type TEXT NOT NULL,  -- 'funding' or 'news'
                    title TEXT NOT NULL,
                    summary TEXT,
                    confidence REAL,
                    source TEXT,
                    url TEXT,
                    amount TEXT,
                    investor TEXT,
                    date TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Long-term memory: Aggregated insights
            conn.execute("""
                CREATE TABLE IF NOT EXISTS long_term_memory (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company TEXT NOT NULL,
                    memory_type TEXT NOT NULL,  -- 'funding_summary', 'news_summary', 'trend', 'insight'
                    content TEXT NOT NULL,
                    importance REAL DEFAULT 0.5,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expires_at TIMESTAMP,
                    UNIQUE(company, memory_type, created_at)
                )
            """)
            
            # Intent snapshots: Full structured data snapshots
            conn.execute("""
                CREATE TABLE IF NOT EXISTS intent_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    company TEXT NOT NULL,
                    snapshot_data TEXT NOT NULL,  -- JSON string
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            conn.commit()
    
    def store_intent(self, structured_data: Dict):
        """Store intent data in both short-term and long-term memory"""
        with self.get_connection() as conn:
            for company_name, data in structured_data.get("companies", {}).items():
                # Store short-term memories (individual events)
                for event in data.get("funding_events", []):
                    conn.execute("""
                        INSERT INTO short_term_memory 
                        (company, event_type, title, summary, confidence, source, url, amount, investor, date)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        company_name,
                        "funding",
                        event["event"]["title"],
                        self._generate_summary(event, "funding"),
                        event["event"]["confidence"],
                        event["source"]["name"],
                        event["source"]["url"],
                        event["financial_details"]["amount"],
                        event["financial_details"]["investor"],
                        event["date"]["value"]
                    ))
                
                for event in data.get("news_events", []):
                    conn.execute("""
                        INSERT INTO short_term_memory 
                        (company, event_type, title, summary, confidence, source, url, date)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        company_name,
                        "news",
                        event["event"]["title"],
                        self._generate_summary(event, "news"),
                        event["event"]["confidence"],
                        event["source"]["name"],
                        event["source"]["url"],
                        event["date"]
                    ))
                
                # Store long-term memories (aggregated insights)
                self._store_long_term_memories(conn, company_name, data)
                
                # Store full snapshot
                conn.execute("""
                    INSERT INTO intent_snapshots (company, snapshot_data)
                    VALUES (?, ?)
                """, (company_name, json.dumps(data)))
            
            conn.commit()
    
    def _generate_summary(self, event: Dict, event_type: str) -> str:
        """Generate a brief summary of an event"""
        if event_type == "funding":
            parts = [event["event"]["title"]]
            if event["financial_details"]["amount"] != "Unknown":
                parts.append(f"Amount: {event['financial_details']['amount']}")
            if event["financial_details"]["investor"] != "Unknown":
                parts.append(f"Investor: {event['financial_details']['investor']}")
            return ". ".join(parts)
        else:
            return event["event"]["title"]
    
    def _store_long_term_memories(self, conn, company_name: str, data: Dict):
        """Generate and store long-term memories"""
        now = datetime.now()
        
        # Funding summary
        funding_events = data.get("funding_events", [])
        if funding_events:
            total_funding = len(funding_events)
            high_conf = sum(1 for e in funding_events if e["event"]["confidence"] >= 0.7)
            
            funding_summary = f"{company_name} has {total_funding} recent funding events ({high_conf} high confidence). "
            
            amounts = [e for e in funding_events if e["financial_details"]["amount"] != "Unknown"]
            if amounts:
                funding_summary += f"Notable amounts include: " + ", ".join(
                    f"{e['financial_details']['amount']} ({e['event']['title'][:50]}...)"
                    for e in amounts[:3]
                )
            
            conn.execute("""
                INSERT OR REPLACE INTO long_term_memory 
                (company, memory_type, content, importance, created_at, expires_at)
                VALUES (?, 'funding_summary', ?, ?, ?, ?)
            """, (
                company_name,
                funding_summary,
                min(0.9, 0.5 + (high_conf / max(total_funding, 1) * 0.4)),
                now.isoformat(),
                (now + timedelta(days=30)).isoformat()
            ))
        
        # News summary
        news_events = data.get("news_events", [])
        if news_events:
            high_conf_news = [e for e in news_events if e["event"]["confidence"] >= 0.7]
            news_summary = f"{company_name} has {len(news_events)} recent news events. Key topics: " + \
                          "; ".join(e["event"]["title"][:80] for e in high_conf_news[:3])
            
            conn.execute("""
                INSERT OR REPLACE INTO long_term_memory 
                (company, memory_type, content, importance, created_at, expires_at)
                VALUES (?, 'news_summary', ?, ?, ?, ?)
            """, (
                company_name,
                news_summary,
                0.7,
                now.isoformat(),
                (now + timedelta(days=30)).isoformat()
            ))
    
    def retrieve_intent(self, company: str, memory_type: str = "all", limit: int = 10) -> Dict:
        """
        Retrieve intent data for a company.
        memory_type: 'short_term', 'long_term', 'snapshot', or 'all'
        """
        result = {
            "company": company,
            "retrieved_at": datetime.now().isoformat(),
            "short_term": [],
            "long_term": [],
            "snapshots": []
        }
        
        with self.get_connection() as conn:
            if memory_type in ["short_term", "all"]:
                rows = conn.execute("""
                    SELECT * FROM short_term_memory 
                    WHERE company = ? 
                    ORDER BY created_at DESC 
                    LIMIT ?
                """, (company, limit)).fetchall()
                
                result["short_term"] = [dict(r) for r in rows]
            
            if memory_type in ["long_term", "all"]:
                rows = conn.execute("""
                    SELECT * FROM long_term_memory 
                    WHERE company = ? AND (expires_at IS NULL OR expires_at > ?)
                    ORDER BY importance DESC, created_at DESC 
                    LIMIT ?
                """, (company, datetime.now().isoformat(), limit)).fetchall()
                
                result["long_term"] = [dict(r) for r in rows]
            
            if memory_type in ["snapshot", "all"]:
                rows = conn.execute("""
                    SELECT * FROM intent_snapshots 
                    WHERE company = ? 
                    ORDER BY created_at DESC 
                    LIMIT 1
                """, (company,)).fetchall()
                
                result["snapshots"] = [dict(r) for r in rows]
        
        return result
    
    def get_llm_context(self, company: str) -> str:
        """
        Get a formatted context string optimized for LLM context windows.
        Returns a concise, well-structured text representation.
        """
        data = self.retrieve_intent(company, "all", limit=5)
        
        context_parts = [f"# Company Intelligence: {company}\n"]
        
        # Long-term memories first (most important for context)
        if data["long_term"]:
            context_parts.append("## Key Insights")
            for mem in data["long_term"]:
                context_parts.append(f"- [{mem['memory_type']}] {mem['content']}")
        
        # Recent events
        if data["short_term"]:
            context_parts.append("\n## Recent Events")
            
            funding_events = [e for e in data["short_term"] if e["event_type"] == "funding"]
            news_events = [e for e in data["short_term"] if e["event_type"] == "news"]
            
            if funding_events:
                context_parts.append("\n### Funding")
                for event in funding_events[:3]:
                    parts = [f"• {event['title']}"]
                    if event.get('amount'):
                        parts.append(f"  Amount: {event['amount']}")
                    if event.get('investor'):
                        parts.append(f"  Investor: {event['investor']}")
                    if event.get('source'):
                        parts.append(f"  Source: {event['source']} (confidence: {event.get('confidence', 0):.0%})")
                    context_parts.append("\n".join(parts))
            
            if news_events:
                context_parts.append("\n### News")
                for event in news_events[:3]:
                    parts = [f"• {event['title']}"]
                    if event.get('source'):
                        parts.append(f"  Source: {event['source']} ({event.get('date', 'unknown date')})")
                    context_parts.append("\n".join(parts))
        
        # Latest snapshot summary
        if data["snapshots"]:
            snapshot = json.loads(data["snapshots"][0]["snapshot_data"])
            if "summary" in snapshot:
                summary = snapshot["summary"]
                context_parts.append(f"\n## Summary")
                context_parts.append(f"Total funding events: {summary.get('total_funding_events', 0)}")
                context_parts.append(f"High confidence funding: {summary.get('high_confidence_funding', 0)}")
                context_parts.append(f"Total news events: {summary.get('total_news_events', 0)}")
        
        return "\n".join(context_parts)
    
    def clear_old_memories(self, days: int = 7):
        """Clear old short-term memories and expired long-term memories"""
        with self.get_connection() as conn:
            conn.execute("""
                DELETE FROM short_term_memory 
                WHERE created_at < ?
            """, ((datetime.now() - timedelta(days=days)).isoformat(),))
            
            conn.execute("""
                DELETE FROM long_term_memory 
                WHERE expires_at IS NOT NULL AND expires_at < ?
            """, (datetime.now().isoformat(),))
            
            conn.commit()