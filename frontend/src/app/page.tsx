"use client";

import { useEffect, useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { Card, CardHeader, CardTitle, CardContent, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { API_BASE } from "@/lib/api";

interface AgentRun {
  run_id: string;
  correlation_id: string;
  objective: string;
  status: string;
  created_at: string;
  updated_at: string;
  state?: any;
}

interface TraceEvent {
  event_type: string;
  module: string;
  timestamp: string;
  payload: any;
}

function StatusDot({ status }: { status: string }) {
  const colors: Record<string, string> = {
    running: "bg-amber-400 shadow-amber-400/50",
    awaiting_approval: "bg-yellow-400 shadow-yellow-400/50 animate-pulse",
    completed: "bg-emerald-400 shadow-emerald-400/50",
    failed: "bg-red-400 shadow-red-400/50",
  };
  return (
    <span
      className={`inline-block w-2.5 h-2.5 rounded-full shadow-sm ${colors[status] || "bg-slate-500"}`}
    />
  );
}

function StatusLabel({ status }: { status: string }) {
  const labels: Record<string, { text: string; cls: string }> = {
    running: { text: "Running", cls: "text-amber-400" },
    awaiting_approval: { text: "Awaiting Approval", cls: "text-yellow-400" },
    completed: { text: "Completed", cls: "text-emerald-400" },
    failed: { text: "Failed", cls: "text-red-400" },
  };
  const l = labels[status] || { text: status, cls: "text-slate-400" };
  return <span className={`text-xs font-semibold uppercase tracking-wide ${l.cls}`}>{l.text}</span>;
}

function timeAgo(dateStr: string): string {
  const d = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - d.getTime();
  const diffMin = Math.floor(diffMs / 60000);
  if (diffMin < 1) return "just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  return `${Math.floor(diffHr / 24)}d ago`;
}

export default function CommandCenter() {
  const router = useRouter();
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [events, setEvents] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  // Trace viewer
  const [traceId, setTraceId] = useState("");
  const [traceData, setTraceData] = useState<TraceEvent[] | null>(null);
  const [traceLoading, setTraceLoading] = useState(false);
  const [traceError, setTraceError] = useState("");

  const loadData = useCallback(async () => {
    try {
      const [runsRes, eventsRes] = await Promise.all([
        fetch(`${API_BASE}/v1/agent/runs?limit=20`),
        fetch(`${API_BASE}/v1/events?limit=50`),
      ]);
      if (runsRes.ok) {
        const runsData = await runsRes.json();
        setRuns(runsData.items || []);
      }
      if (eventsRes.ok) {
        const eventsData = await eventsRes.json();
        setEvents(eventsData.items || []);
      }
    } catch (e) {
      console.error("Failed to load command center data", e);
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    loadData();
    const interval = setInterval(loadData, 8000);
    return () => clearInterval(interval);
  }, [loadData]);

  const handleTrace = async () => {
    if (!traceId.trim()) return;
    setTraceLoading(true);
    setTraceError("");
    try {
      const res = await fetch(`${API_BASE}/v1/events/trace/${traceId}`);
      if (!res.ok) throw new Error("Trace not found");
      setTraceData(await res.json());
    } catch (e: any) {
      setTraceError(e.message);
      setTraceData(null);
    }
    setTraceLoading(false);
  };

  // Compute stats from events
  const companiesFound = events.filter(e => e.event_type === "companies_identified").length;
  const leadsIngested = events.filter(e => e.event_type === "lead_ingested").length;
  const personasFound = events.filter(e => e.event_type === "personas_identified").length;
  const messagesGenerated = events.filter(e => e.event_type === "message_generated").length;
  const activeRuns = runs.filter(r => r.status === "running" || r.status === "awaiting_approval").length;
  const completedRuns = runs.filter(r => r.status === "completed").length;

  return (
    <div className="flex flex-col gap-8 max-w-6xl">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold flex items-center gap-3">
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="url(#cmdGrad)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <defs>
                <linearGradient id="cmdGrad" x1="0%" y1="0%" x2="100%" y2="100%">
                  <stop offset="0%" stopColor="#60a5fa" />
                  <stop offset="100%" stopColor="#a78bfa" />
                </linearGradient>
              </defs>
              <rect x="3" y="3" width="7" height="7" rx="1" />
              <rect x="14" y="3" width="7" height="7" rx="1" />
              <rect x="14" y="14" width="7" height="7" rx="1" />
              <rect x="3" y="14" width="7" height="7" rx="1" />
            </svg>
            Command Center
          </h2>
          <p className="text-sm text-slate-400 mt-1">Real-time overview of your agentic outbound operations</p>
        </div>
        <Button
          onClick={() => router.push("/mission")}
          className="bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white border-0 shadow-lg shadow-blue-600/20"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="mr-2">
            <path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 0 0-2.91-.09z"/>
            <path d="m12 15-3-3a22 22 0 0 1 2-3.95A12.88 12.88 0 0 1 22 2c0 2.72-.78 7.5-6 11a22.35 22.35 0 0 1-4 2z"/>
            <path d="M9 12H4s.55-3.03 2-4c1.62-1.08 5 0 5 0"/>
            <path d="M12 15v5s3.03-.55 4-2c1.08-1.62 0-5 0-5"/>
          </svg>
          New Mission
        </Button>
      </div>

      {/* Stats Grid */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[
          { label: "Active Missions", value: activeRuns, color: "text-amber-400", icon: "🔥" },
          { label: "Companies Found", value: companiesFound, color: "text-blue-400", icon: "🏢" },
          { label: "Personas Enriched", value: personasFound, color: "text-violet-400", icon: "👤" },
          { label: "Messages Drafted", value: messagesGenerated, color: "text-emerald-400", icon: "✉️" },
        ].map((stat) => (
          <Card key={stat.label} className="bg-slate-900/80 border-slate-800/60 backdrop-blur-sm hover:border-slate-700/60 transition-colors">
            <CardContent className="pt-5 pb-4 px-5">
              <div className="flex items-center justify-between mb-2">
                <span className="text-2xl">{stat.icon}</span>
                <span className={`text-3xl font-bold tabular-nums ${stat.color}`}>
                  {loading ? "—" : stat.value}
                </span>
              </div>
              <div className="text-xs text-slate-400 font-medium uppercase tracking-wider">{stat.label}</div>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Two column layout */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6">
        {/* Agent Runs — takes 3 cols */}
        <div className="lg:col-span-3 flex flex-col gap-4">
          <Card className="bg-slate-900/80 border-slate-800/60 backdrop-blur-sm flex-1">
            <CardHeader className="pb-3">
              <div className="flex items-center justify-between">
                <CardTitle className="text-lg flex items-center gap-2">
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-blue-400">
                    <circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>
                  </svg>
                  Recent Agent Runs
                </CardTitle>
                <span className="text-xs text-slate-500 font-mono">{runs.length} total</span>
              </div>
            </CardHeader>
            <CardContent className="pt-0 space-y-2">
              {loading ? (
                <div className="text-slate-500 text-sm py-6 text-center">Loading runs...</div>
              ) : runs.length === 0 ? (
                <div className="text-center py-8">
                  <p className="text-slate-500 text-sm">No agent runs yet.</p>
                  <p className="text-xs text-slate-600 mt-1">Launch a mission to get started.</p>
                </div>
              ) : (
                runs.slice(0, 8).map((run) => (
                  <div
                    key={run.run_id}
                    className="flex items-start gap-3 p-3 rounded-lg border border-slate-800/60 bg-slate-950/50 hover:bg-slate-800/30 transition-colors cursor-pointer group"
                    onClick={() => {
                      setTraceId(run.correlation_id);
                      setTimeout(handleTrace, 100);
                    }}
                  >
                    <StatusDot status={run.status} />
                    <div className="flex-1 min-w-0">
                      <p className="text-sm text-slate-200 truncate group-hover:text-white transition-colors">
                        {run.objective || "Untitled run"}
                      </p>
                      <div className="flex items-center gap-3 mt-1">
                        <StatusLabel status={run.status} />
                        <span className="text-xs text-slate-600">•</span>
                        <span className="text-xs text-slate-500">{timeAgo(run.updated_at || run.created_at)}</span>
                      </div>
                    </div>
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="text-slate-600 group-hover:text-slate-400 transition-colors mt-1 flex-shrink-0">
                      <polyline points="9 18 15 12 9 6" />
                    </svg>
                  </div>
                ))
              )}
            </CardContent>
          </Card>
        </div>

        {/* Right sidebar — takes 2 cols */}
        <div className="lg:col-span-2 flex flex-col gap-4">
          {/* Performance summary */}
          <Card className="bg-slate-900/80 border-slate-800/60 backdrop-blur-sm">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm flex items-center gap-2">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-emerald-400">
                  <path d="M22 12h-4l-3 9L9 3l-3 9H2"/>
                </svg>
                Pipeline Health
              </CardTitle>
            </CardHeader>
            <CardContent className="pt-0 space-y-3">
              {[
                { label: "Completed missions", value: completedRuns, total: runs.length, color: "bg-emerald-500" },
                { label: "Leads ingested", value: leadsIngested, total: Math.max(leadsIngested, 1), color: "bg-blue-500" },
                { label: "Messages generated", value: messagesGenerated, total: Math.max(messagesGenerated, 1), color: "bg-violet-500" },
              ].map((item) => (
                <div key={item.label}>
                  <div className="flex items-center justify-between mb-1">
                    <span className="text-xs text-slate-400">{item.label}</span>
                    <span className="text-xs font-mono text-slate-300">{item.value}</span>
                  </div>
                  <div className="h-1.5 bg-slate-800 rounded-full overflow-hidden">
                    <div
                      className={`h-full ${item.color} rounded-full transition-all duration-700`}
                      style={{ width: `${Math.min(100, (item.value / Math.max(item.total, 1)) * 100)}%` }}
                    />
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>

          {/* Quick trace */}
          <Card className="bg-slate-900/80 border-slate-800/60 backdrop-blur-sm">
            <CardHeader className="pb-3">
              <CardTitle className="text-sm flex items-center gap-2">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-indigo-400">
                  <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
                </svg>
                Trace Viewer
              </CardTitle>
            </CardHeader>
            <CardContent className="pt-0">
              <div className="flex gap-2">
                <Input
                  placeholder="Correlation ID..."
                  value={traceId}
                  onChange={(e) => setTraceId(e.target.value)}
                  className="bg-slate-950 border-slate-800 text-xs font-mono"
                  onKeyDown={(e) => e.key === "Enter" && handleTrace()}
                />
                <Button variant="outline" size="sm" onClick={handleTrace} disabled={traceLoading}>
                  {traceLoading ? "..." : "🔍"}
                </Button>
              </div>
              {traceError && (
                <p className="text-xs text-red-400 mt-2">{traceError}</p>
              )}
            </CardContent>
          </Card>
        </div>
      </div>

      {/* Trace results (inline, full-width) */}
      {traceData && traceData.length > 0 && (
        <Card className="bg-slate-900/80 border-slate-800/60 backdrop-blur-sm">
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-lg flex items-center gap-2">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-indigo-400">
                  <path d="M12 3v12"/><path d="m8 11 4 4 4-4"/><path d="M8 5H4a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-4"/>
                </svg>
                Event Timeline
              </CardTitle>
              <Button variant="outline" size="sm" onClick={() => setTraceData(null)}>Close</Button>
            </div>
            <CardDescription className="font-mono text-xs">{traceId}</CardDescription>
          </CardHeader>
          <CardContent className="pt-0">
            <div className="relative border-l-2 border-slate-800 ml-3 space-y-4">
              {traceData.map((evt, i) => (
                <div key={i} className="pl-6 relative">
                  <div className="absolute w-3 h-3 bg-indigo-500 rounded-full -left-[7px] top-1.5 ring-4 ring-slate-900" />
                  <div className="flex items-center gap-2 mb-1">
                    <span className="text-sm font-medium text-indigo-300">{evt.event_type}</span>
                    <span className="text-xs px-2 py-0.5 bg-slate-800 rounded-full text-slate-400">{evt.module}</span>
                    <span className="text-xs text-slate-600 ml-auto font-mono">{new Date(evt.timestamp).toLocaleString()}</span>
                  </div>
                  <pre className="text-xs text-slate-400 bg-slate-950/80 p-3 rounded-md border border-slate-800/60 overflow-x-auto max-h-32">
                    {JSON.stringify(evt.payload, null, 2)}
                  </pre>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
      {traceData && traceData.length === 0 && (
        <p className="text-sm text-slate-500 text-center">No events found for this correlation ID.</p>
      )}
    </div>
  );
}
