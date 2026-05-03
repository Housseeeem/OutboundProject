"use client";

import React, { useState } from "react";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import type { AgentEvaluation, ToolLogEntry } from "@/lib/useAgentRun";

interface ResultsPanelProps {
  sentEvents: any[];
  toolLog: ToolLogEntry[];
  evaluation: AgentEvaluation | null;
  totalSteps: number;
  correlationId: string | null;
}

function EventTypeBadge({ type }: { type: string }) {
  const colorMap: Record<string, string> = {
    lead_ingested: "badge--blue",
    lead_scored: "badge--indigo",
    message_generated: "badge--purple",
    message_sent: "badge--emerald",
    reply_received: "badge--amber",
    conversion: "badge--green",
  };
  return (
    <span className={`results-badge ${colorMap[type] || "badge--slate"}`}>
      {type}
    </span>
  );
}

function ModuleBadge({ module }: { module: string }) {
  const colorMap: Record<string, string> = {
    inject: "module--cyan",
    detective: "module--violet",
    writer: "module--rose",
    worker: "module--slate",
  };
  return (
    <span className={`results-module-badge ${colorMap[module] || "module--slate"}`}>
      {module}
    </span>
  );
}

function ParsedPayload({ eventType, payload }: { eventType: string; payload: any }) {
  if (!payload) return <div className="p-4 text-slate-500">No payload</div>;

  if (eventType === "message_generated" || eventType === "message_sent") {
    return (
      <div className="p-4 bg-indigo-500/5 border-t border-indigo-500/20">
        <div className="text-xs text-indigo-400 font-semibold uppercase mb-2">Drafted Message:</div>
        {payload.subject && <div className="text-sm font-semibold text-slate-200 mb-2">Subject: {payload.subject}</div>}
        <div className="text-sm text-slate-300 whitespace-pre-wrap font-sans">{payload.body}</div>
      </div>
    );
  }

  if (eventType === "lead_ingested") {
    return (
      <div className="p-4 bg-slate-800/20 border-t border-slate-800">
        <div className="text-xs text-slate-400 font-semibold mb-1">Lead Ingested:</div>
        <div className="text-sm font-medium text-blue-400">{payload.company}</div>
        {payload.contact?.name && <div className="text-xs text-slate-300 mt-1">{payload.contact.name} ({payload.contact.email})</div>}
        {payload.intelligence_summary && (
          <div className="mt-3 pt-3 border-t border-slate-700/50">
            <div className="text-xs text-slate-500 mb-1">Intelligence Summary:</div>
            <pre className="text-xs text-slate-400 font-sans whitespace-pre-wrap">{JSON.stringify(payload.intelligence_summary, null, 2)}</pre>
          </div>
        )}
      </div>
    );
  }

  if (eventType === "lead_scored") {
    return (
      <div className="p-4 bg-slate-800/20 border-t border-slate-800">
        <div className="flex items-center gap-3 mb-2">
          <div className="text-xs text-slate-400 font-semibold">Score:</div>
          <div className={`text-sm font-bold ${payload.score >= 80 ? 'text-green-400' : payload.score >= 50 ? 'text-amber-400' : 'text-slate-400'}`}>
            {payload.score}/100
          </div>
        </div>
        <div className="text-sm text-slate-300">{payload.reason}</div>
      </div>
    );
  }

  return (
    <pre className="results-event-json border-t border-slate-800">
      {JSON.stringify(payload, null, 2)}
    </pre>
  );
}

export function ResultsPanel({
  sentEvents,
  toolLog,
  evaluation,
  totalSteps,
  correlationId,
}: ResultsPanelProps) {
  const [expandedEvent, setExpandedEvent] = useState<number | null>(null);

  // Compute stats
  const toolDurations = toolLog
    .filter((t) => t.duration_ms != null)
    .map((t) => t.duration_ms as number);
  const totalDurationMs = toolDurations.reduce((a, b) => a + b, 0);
  const avgDurationMs = toolDurations.length > 0 ? Math.round(totalDurationMs / toolDurations.length) : 0;

  const evalScore = evaluation?.score ?? evaluation?.overall_score;
  const evalReasoning = evaluation?.reasoning ?? evaluation?.summary ?? evaluation?.explanation;

  return (
    <div className="results-panel">
      {/* Summary Stats */}
      <div className="results-stats-grid">
        <Card className="results-stat-card">
          <CardContent className="results-stat-content">
            <div className="results-stat-value results-stat-value--blue">{sentEvents.length}</div>
            <div className="results-stat-label">Events Generated</div>
          </CardContent>
        </Card>
        <Card className="results-stat-card">
          <CardContent className="results-stat-content">
            <div className="results-stat-value results-stat-value--indigo">{totalSteps}</div>
            <div className="results-stat-label">Reasoning Steps</div>
          </CardContent>
        </Card>
        <Card className="results-stat-card">
          <CardContent className="results-stat-content">
            <div className="results-stat-value results-stat-value--purple">
              {totalDurationMs > 1000 ? `${(totalDurationMs / 1000).toFixed(1)}s` : `${totalDurationMs}ms`}
            </div>
            <div className="results-stat-label">Total Duration</div>
          </CardContent>
        </Card>
        <Card className="results-stat-card">
          <CardContent className="results-stat-content">
            <div className={`results-stat-value ${evalScore != null && evalScore >= 70 ? "results-stat-value--green" : evalScore != null ? "results-stat-value--amber" : "results-stat-value--slate"}`}>
              {evalScore != null ? `${evalScore}%` : "--"}
            </div>
            <div className="results-stat-label">Quality Score</div>
          </CardContent>
        </Card>
      </div>

      {/* Evaluation Card */}
      {evaluation && (
        <Card className="results-eval-card">
          <CardHeader>
            <CardTitle className="results-eval-title">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 20h9"/><path d="M16.376 3.622a1 1 0 0 1 3.002 3.002L7.368 18.635a2 2 0 0 1-.855.506l-2.872.838a.5.5 0 0 1-.62-.62l.838-2.872a2 2 0 0 1 .506-.854z"/></svg>
              Agent Self-Evaluation
            </CardTitle>
          </CardHeader>
          <CardContent>
            {evalScore != null && (
              <div className="results-eval-score-bar">
                <div className="results-eval-score-track">
                  <div
                    className={`results-eval-score-fill ${evalScore >= 70 ? "fill--green" : evalScore >= 40 ? "fill--amber" : "fill--red"}`}
                    style={{ width: `${Math.min(100, evalScore)}%` }}
                  />
                </div>
                <span className="results-eval-score-label">{evalScore}%</span>
              </div>
            )}
            {evalReasoning && (
              <p className="results-eval-reasoning">{evalReasoning}</p>
            )}
          </CardContent>
        </Card>
      )}

      {/* Generated Events Table */}
      {sentEvents.length > 0 && (
        <Card className="results-events-card">
          <CardHeader>
            <CardTitle className="results-events-title">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 3v12"/><path d="m8 11 4 4 4-4"/><path d="M8 5H4a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-4"/></svg>
              Generated Pipeline Events
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <table className="results-events-table">
              <thead>
                <tr>
                  <th>#</th>
                  <th>Module</th>
                  <th>Event Type</th>
                  <th>Details</th>
                </tr>
              </thead>
              <tbody>
                {sentEvents.map((evt, i) => (
                  <React.Fragment key={i}>
                    <tr
                      className="results-event-row"
                      onClick={() => setExpandedEvent(expandedEvent === i ? null : i)}
                    >
                      <td className="results-event-idx">{i + 1}</td>
                      <td><ModuleBadge module={evt.module} /></td>
                      <td><EventTypeBadge type={evt.event_type} /></td>
                      <td className="results-event-expand-cell">
                        <svg
                          width="14"
                          height="14"
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="2"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          style={{
                            transform: expandedEvent === i ? "rotate(180deg)" : "rotate(0deg)",
                            transition: "transform 0.2s",
                          }}
                        >
                          <polyline points="6 9 12 15 18 9" />
                        </svg>
                      </td>
                    </tr>
                    {expandedEvent === i && (
                      <tr className="results-event-detail-row">
                        <td colSpan={4}>
                          <ParsedPayload eventType={evt.event_type} payload={evt.payload} />
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}

      {/* Tool Execution Log */}
      {toolLog.length > 0 && (
        <Card className="results-toollog-card">
          <CardHeader>
            <CardTitle className="results-toollog-title">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/></svg>
              Tool Execution Log
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="results-toollog-list">
              {toolLog.map((entry, i) => (
                <div key={i} className="results-toollog-entry">
                  <div className="results-toollog-entry-header">
                    <span className={`results-toollog-status ${entry.status === "ok" ? "status--ok" : entry.status === "error" ? "status--error" : "status--neutral"}`}>
                      {entry.status === "ok" ? "✓" : entry.status === "error" ? "✗" : "•"}
                    </span>
                    <span className="results-toollog-name">{entry.tool}</span>
                    {entry.duration_ms != null && (
                      <span className="results-toollog-duration">{entry.duration_ms}ms</span>
                    )}
                  </div>
                  {entry.duration_ms != null && (
                    <div className="results-toollog-bar-track">
                      <div
                        className="results-toollog-bar-fill"
                        style={{
                          width: `${Math.min(100, (entry.duration_ms / Math.max(1, ...toolDurations)) * 100)}%`,
                        }}
                      />
                    </div>
                  )}
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Correlation ID */}
      {correlationId && (
        <div className="results-correlation">
          <span className="results-correlation-label">Correlation ID:</span>
          <code className="results-correlation-value">{correlationId}</code>
        </div>
      )}
    </div>
  );
}
