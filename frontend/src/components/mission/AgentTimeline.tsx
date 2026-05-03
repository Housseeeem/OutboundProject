"use client";

import React, { useState } from "react";
import type { ScratchpadEntry } from "@/lib/useAgentRun";

// Map tool names to user-friendly labels and emoji
function toolLabel(action: Record<string, any>): { icon: string; label: string; detail: string } {
  const tool = action?.tool || "unknown";
  switch (tool) {
    case "generate_and_ingest_event":
      return {
        icon: "📥",
        label: "Generate Event",
        detail: `${action.module || "?"}/${action.event_type || "?"}`,
      };
    case "sql_query":
      return { icon: "🗄️", label: "SQL Query", detail: action.query || "" };
    case "search_knowledge":
      return { icon: "🔍", label: "Knowledge Search", detail: action.query || "" };
    case "search_web":
      return { icon: "🌐", label: "Web Search", detail: action.query || "" };
    case "fetch_company_intelligence":
      return { icon: "🏢", label: "Company Intelligence", detail: action.domain || "" };
    case "finish":
      return { icon: "🏁", label: "Mission Complete", detail: action.reason || "" };
    default:
      return { icon: "⚙️", label: tool, detail: "" };
  }
}

function ParsedObservation({ action, observation }: { action: Record<string, any>; observation: string }) {
  let data: any = null;
  try {
    data = JSON.parse(observation);
  } catch {
    return <pre className="agent-step-json">{observation}</pre>;
  }

  const tool = action?.tool;

  // Handle message generation
  if (tool === "generate_and_ingest_event" && action?.event_type === "message_generated") {
    const payload = data?.payload;
    if (payload?.body) {
      return (
        <div className="mt-2 bg-indigo-500/10 border border-indigo-500/20 rounded-md p-4">
          <div className="text-xs text-indigo-400 font-semibold uppercase mb-2">Drafted Message:</div>
          {payload.subject && <div className="text-sm font-semibold text-slate-200 mb-2">Subject: {payload.subject}</div>}
          <div className="text-sm text-slate-300 whitespace-pre-wrap font-sans">{payload.body}</div>
        </div>
      );
    }
  }

  // Handle lead ingestion
  if (tool === "generate_and_ingest_event" && action?.event_type === "lead_ingested") {
    const payload = data?.payload;
    if (payload?.company) {
      return (
        <div className="mt-2 bg-slate-800/50 border border-slate-700 rounded-md p-3">
          <div className="text-xs text-slate-400 font-semibold mb-1">Lead Ingested:</div>
          <div className="text-sm font-medium text-blue-400">{payload.company}</div>
          {payload.contact?.name && <div className="text-xs text-slate-300 mt-1">{payload.contact.name} ({payload.contact.email})</div>}
        </div>
      );
    }
  }

  // Handle companies identified
  if (tool === "generate_and_ingest_event" && action?.event_type === "companies_identified") {
    const payload = data?.payload;
    if (payload?.companies && Array.isArray(payload.companies)) {
      return (
        <div className="mt-2 bg-emerald-500/10 border border-emerald-500/20 rounded-md p-4">
          <div className="text-xs text-emerald-400 font-semibold uppercase mb-2">Companies Identified:</div>
          <ul className="list-disc pl-5 text-sm text-slate-300 space-y-1">
            {payload.companies.map((c: any, i: number) => (
              <li key={i}>{typeof c === "string" ? c : JSON.stringify(c)}</li>
            ))}
          </ul>
        </div>
      );
    }
  }

  // Handle company intelligence
  if (tool === "fetch_company_intelligence" && data?.company_profile) {
    const profile = data.company_profile;
    const personasCount = data.personas?.length ?? 0;
    const discovered = data.personas_discovered === true;
    return (
      <div className="mt-2 bg-slate-800/50 border border-slate-700 rounded-md p-3">
        <div className="text-xs text-slate-400 font-semibold mb-1">Company Profile:</div>
        <div className="text-sm font-medium text-blue-400">{profile.name || profile.domain}</div>
        <div className="text-xs text-slate-300 mt-1">
          {profile.industry ? `${profile.industry} • ` : ""}
          {profile.estimated_num_employees ? `${profile.estimated_num_employees} employees` : "? employees"}
        </div>
        {personasCount > 0 ? (
          <div className="text-xs text-emerald-400 mt-1">
            Found {personasCount} relevant persona{personasCount !== 1 ? "s" : ""}
            {discovered ? " (discovered live)" : ""}.
          </div>
        ) : (
          <div className="text-xs text-slate-500 mt-1">No personas found.</div>
        )}
      </div>
    );
  }

  // Handle SQL queries / general lists
  if (tool === "sql_query" && Array.isArray(data) && data.length > 0) {
    return (
      <div className="mt-2 bg-slate-800/50 border border-slate-700 rounded-md p-3">
        <div className="text-xs text-slate-400 font-semibold mb-2">Query Results ({data.length} rows):</div>
        <div className="max-h-40 overflow-y-auto">
          <table className="w-full text-xs text-left">
            <thead>
              <tr className="text-slate-500 border-b border-slate-700">
                {Object.keys(data[0]).map((k) => <th key={k} className="pb-1 pr-2">{k}</th>)}
              </tr>
            </thead>
            <tbody>
              {data.map((row, idx) => (
                <tr key={idx} className="border-b border-slate-800/50 last:border-0">
                  {Object.values(row).map((v: any, i) => (
                    <td key={i} className="py-1 pr-2 text-slate-300 truncate max-w-[150px]">{String(v)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    );
  }

  // Fallback to JSON
  return <pre className="agent-step-json">{JSON.stringify(data, null, 2)}</pre>;
}

interface AgentTimelineProps {
  steps: ScratchpadEntry[];
  isRunning: boolean;
  currentStep: number;
}

export function AgentTimeline({ steps, isRunning, currentStep }: AgentTimelineProps) {
  const [expandedSteps, setExpandedSteps] = useState<Set<number>>(new Set());

  const toggleStep = (index: number) => {
    setExpandedSteps((prev) => {
      const next = new Set(prev);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  };

  return (
    <div className="agent-timeline">
      {/* Header */}
      <div className="agent-timeline-header">
        <h3 className="agent-timeline-title">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
          Agent Reasoning Steps
        </h3>
        {isRunning && (
          <span className="agent-timeline-running-badge">
            <span className="agent-timeline-pulse" />
            Processing Step {currentStep + 1}
          </span>
        )}
      </div>

      {/* Timeline */}
      <div className="agent-timeline-track">
        {steps.map((entry, i) => {
          const { icon, label, detail } = toolLabel(entry.action);
          const isFinish = entry.action?.tool === "finish";
          const isExpanded = expandedSteps.has(i);
          const isLast = i === steps.length - 1;

          return (
            <div
              key={i}
              className={`agent-step ${isFinish ? "agent-step--finish" : ""} ${isLast && isRunning ? "agent-step--active" : ""}`}
            >
              {/* Connector line */}
              {i < steps.length - 1 && <div className="agent-step-connector" />}
              {i === steps.length - 1 && isRunning && <div className="agent-step-connector agent-step-connector--dashed" />}

              {/* Node dot */}
              <div className={`agent-step-dot ${isFinish ? "agent-step-dot--finish" : ""}`}>
                <span className="agent-step-dot-label">{i + 1}</span>
              </div>

              {/* Content */}
              <div className="agent-step-content" onClick={() => toggleStep(i)}>
                <div className="agent-step-header">
                  <span className="agent-step-icon">{icon}</span>
                  <span className="agent-step-label">{label}</span>
                  {detail && <span className="agent-step-detail">{detail}</span>}
                  <button className="agent-step-expand" aria-label="Toggle details">
                    <svg
                      width="14"
                      height="14"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      style={{ transform: isExpanded ? "rotate(180deg)" : "rotate(0deg)", transition: "transform 0.2s" }}
                    >
                      <polyline points="6 9 12 15 18 9" />
                    </svg>
                  </button>
                </div>

                {/* Thought summary (always visible) */}
                <p className="agent-step-thought">
                  💭 {entry.thought?.slice(0, 150)}{entry.thought?.length > 150 ? "..." : ""}
                </p>

                {/* Expanded details */}
                {isExpanded && (
                  <div className="agent-step-details">
                    <div className="agent-step-section">
                      <span className="agent-step-section-label">Full Thought</span>
                      <p className="agent-step-section-text">{entry.thought}</p>
                    </div>
                    <div className="agent-step-section">
                      <span className="agent-step-section-label">Action</span>
                      <pre className="agent-step-json">{JSON.stringify(entry.action, null, 2)}</pre>
                    </div>
                    <div className="agent-step-section">
                      <span className="agent-step-section-label">Observation Output</span>
                      <ParsedObservation action={entry.action} observation={entry.observation} />
                    </div>
                  </div>
                )}
              </div>
            </div>
          );
        })}

        {/* Loading indicator when running with no steps yet */}
        {isRunning && steps.length === 0 && (
          <div className="agent-step agent-step--active">
            <div className="agent-step-dot agent-step-dot--pulse">
              <span className="agent-step-dot-label">?</span>
            </div>
            <div className="agent-step-content">
              <div className="agent-step-header">
                <span className="agent-step-icon">⏳</span>
                <span className="agent-step-label">Agent is thinking...</span>
              </div>
              <p className="agent-step-thought">💭 Analyzing your objective and planning the first action</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
