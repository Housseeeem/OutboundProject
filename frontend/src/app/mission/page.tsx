"use client";

import { useState } from "react";
import "./mission.css";
import { useAgentRun } from "@/lib/useAgentRun";
import { PromptInput } from "@/components/mission/PromptInput";
import { AgentTimeline } from "@/components/mission/AgentTimeline";
import { ResultsPanel } from "@/components/mission/ResultsPanel";
import { Button } from "@/components/ui/button";

export default function MissionPage() {
  const {
    phase,
    runId,
    correlationId,
    steps,
    currentStep,
    totalEventsGenerated,
    sentEvents,
    toolLog,
    evaluation,
    errors,
    startRun,
    resumeRun,
    reset,
  } = useAgentRun();

  const [selectedCompanies, setSelectedCompanies] = useState<string[]>([]);
  const [selectedPersonas, setSelectedPersonas] = useState<string[]>([]);

  return (
    <div className="mission-page">
      {/* Page Header */}
      <div className="mission-header">
        <div className="mission-header-text">
          <h2 className="mission-title">
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="url(#rocketGrad)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <defs>
                <linearGradient id="rocketGrad" x1="0%" y1="0%" x2="100%" y2="100%">
                  <stop offset="0%" stopColor="#60a5fa" />
                  <stop offset="100%" stopColor="#a78bfa" />
                </linearGradient>
              </defs>
              <path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 0 0-2.91-.09z"/>
              <path d="m12 15-3-3a22 22 0 0 1 2-3.95A12.88 12.88 0 0 1 22 2c0 2.72-.78 7.5-6 11a22.35 22.35 0 0 1-4 2z"/>
              <path d="M9 12H4s.55-3.03 2-4c1.62-1.08 5 0 5 0"/>
              <path d="M12 15v5s3.03-.55 4-2c1.08-1.62 0-5 0-5"/>
            </svg>
            Mission Control
          </h2>
          <p className="mission-subtitle">
            Describe your outreach objective and watch the AI agents work in real-time
          </p>
        </div>
        {phase !== "idle" && (
          <Button
            id="mission-reset-btn"
            variant="outline"
            onClick={reset}
            className="mission-reset-btn"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/></svg>
            New Mission
          </Button>
        )}
      </div>

      {/* Error Banner */}
      {errors.length > 0 && (
        <div className="mission-error-banner">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
          <div>
            {errors.map((err, i) => (
              <p key={i}>{err}</p>
            ))}
          </div>
        </div>
      )}

      {/* Phase: Idle — Show Prompt Input */}
      {phase === "idle" && (
        <PromptInput
          onSubmit={startRun}
          disabled={false}
          loading={false}
        />
      )}

      {/* Phase: Submitting */}
      {phase === "submitting" && (
        <div className="mission-submitting">
          <div className="mission-submitting-spinner" />
          <h3 className="mission-submitting-text">Initializing agents...</h3>
          <p className="mission-submitting-sub">Setting up the agentic pipeline for your objective</p>
        </div>
      )}

      {/* Phase: Running or Awaiting Approval — Show Timeline */}
      {(phase === "running" || phase === "awaiting_approval" || phase === "completed" || phase === "failed") && (
        <>
          {/* Objective reminder */}
          {steps.length > 0 && (
            <div className="mission-objective-banner">
              <span className="mission-objective-label">Objective:</span>
              <span className="mission-objective-text">
                {steps[0]?.action?.reason || "Processing your request..."}
              </span>
            </div>
          )}

          {/* Agent Timeline */}
          <AgentTimeline
            steps={steps}
            isRunning={phase === "running" || phase === "awaiting_approval"}
            currentStep={currentStep}
          />

          {/* Awaiting Approval Banner */}
          {phase === "awaiting_approval" && steps.length > 0 && (
            (() => {
              // The last step is always the "pause" step — look back through recent
              // steps to find the actual event_type that triggered the pause.
              const recentSteps = steps.slice(-3);
              const eventType = recentSteps
                .map(s => s?.action?.event_type)
                .filter(Boolean)
                .pop();

              if (eventType === "companies_identified") {
                // Find the companies_identified event payload from sentEvents
                const companiesEvent = sentEvents
                  .slice()
                  .reverse()
                  .find((e: any) => e.event_type === "companies_identified");
                const companies: Array<{ name: string; domain?: string; [key: string]: any }> =
                  companiesEvent?.payload?.companies || [];

                const toggleCompany = (name: string) => {
                  setSelectedCompanies((prev) =>
                    prev.includes(name) ? prev.filter((c) => c !== name) : [...prev, name]
                  );
                };

                return (
                  <div className="mission-approval-banner mt-4 p-4 rounded-xl border border-emerald-500/30 bg-emerald-500/10 flex flex-col gap-3">
                    <div className="flex items-start gap-3">
                      <span className="text-emerald-400 mt-1">🏢</span>
                      <div className="w-full">
                        <h3 className="text-emerald-300 font-semibold mb-1">Company Selection Required</h3>
                        <p className="text-sm text-emerald-200/70 mb-3">
                          The agent found {companies.length > 0 ? companies.length : "the following"} potential companies. Select the ones you want to target.
                        </p>

                        {companies.length > 0 ? (
                          <ul className="flex flex-col gap-2">
                            {companies.map((c: any, i: number) => {
                              const name = typeof c === "string" ? c : c.name || c.domain || `Company ${i + 1}`;
                              const domain = typeof c === "string" ? null : c.domain;
                              const detail = typeof c === "string" ? null : [c.industry, c.funding].filter(Boolean).join(" · ");
                              const checked = selectedCompanies.includes(name);
                              return (
                                <li
                                  key={i}
                                  onClick={() => toggleCompany(name)}
                                  className={`flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${
                                    checked
                                      ? "border-emerald-400/60 bg-emerald-500/20"
                                      : "border-slate-600/40 bg-slate-800/40 hover:border-emerald-500/40"
                                  }`}
                                >
                                  <div className={`w-4 h-4 rounded border flex-shrink-0 flex items-center justify-center transition-colors ${
                                    checked ? "bg-emerald-500 border-emerald-400" : "border-slate-500"
                                  }`}>
                                    {checked && (
                                      <svg width="10" height="10" viewBox="0 0 12 12" fill="none" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                                        <polyline points="2 6 5 9 10 3" />
                                      </svg>
                                    )}
                                  </div>
                                  <div className="flex flex-col min-w-0">
                                    <span className="text-sm font-medium text-white truncate">{name}</span>
                                    {(domain || detail) && (
                                      <span className="text-xs text-slate-400 truncate">
                                        {[domain, detail].filter(Boolean).join(" · ")}
                                      </span>
                                    )}
                                  </div>
                                </li>
                              );
                            })}
                          </ul>
                        ) : (
                          // Fallback: free-text input if no structured companies in payload
                          <input
                            id="company-selection-input"
                            type="text"
                            placeholder="e.g. Sennder, Forto"
                            className="mt-1 w-full bg-slate-800/50 border border-emerald-500/30 outline-none focus:border-emerald-400 rounded p-2 text-sm text-white placeholder:text-slate-500"
                            onChange={(e) =>
                              setSelectedCompanies(e.target.value.split(",").map((s) => s.trim()).filter(Boolean))
                            }
                          />
                        )}
                      </div>
                    </div>
                    <div className="flex items-center justify-between mt-2">
                      <span className="text-xs text-emerald-300/60">
                        {selectedCompanies.length > 0
                          ? `${selectedCompanies.length} selected`
                          : "Select at least one company"}
                      </span>
                      <div className="flex gap-3">
                        <Button variant="outline" onClick={reset}>Cancel Mission</Button>
                        <Button
                          disabled={selectedCompanies.length === 0}
                          onClick={() => {
                            resumeRun("select_companies", { selected_companies: selectedCompanies });
                            setSelectedCompanies([]);
                          }}
                          className="bg-emerald-600 hover:bg-emerald-500 text-white border-0 disabled:opacity-40"
                        >
                          Confirm Selection
                        </Button>
                      </div>
                    </div>
                  </div>
                );
              }

              if (eventType === "personas_identified") {
                // Find the personas_identified event payload from sentEvents
                const personasEvent = sentEvents
                  .slice()
                  .reverse()
                  .find((e: any) => e.event_type === "personas_identified");
                const personas: Array<{ full_name: string; title?: string; email?: string; company_domain?: string; [key: string]: any }> =
                  personasEvent?.payload?.personas || [];

                const togglePersona = (name: string) => {
                  setSelectedPersonas((prev) =>
                    prev.includes(name) ? prev.filter((p) => p !== name) : [...prev, name]
                  );
                };

                return (
                  <div className="mission-approval-banner mt-4 p-4 rounded-xl border border-violet-500/30 bg-violet-500/10 flex flex-col gap-3">
                    <div className="flex items-start gap-3">
                      <span className="text-violet-400 mt-1">👤</span>
                      <div className="w-full">
                        <h3 className="text-violet-300 font-semibold mb-1">Persona Selection Required</h3>
                        <p className="text-sm text-violet-200/70 mb-3">
                          The agent found {personas.length > 0 ? personas.length : "the following"} personas. Select the ones you want to contact.
                        </p>

                        {personas.length > 0 ? (
                          <ul className="flex flex-col gap-2">
                            {personas.map((p: any, i: number) => {
                              const name = p.full_name || `Persona ${i + 1}`;
                              const title = p.title;
                              const company = p.company_domain || p.company_name;
                              const email = p.email;
                              const checked = selectedPersonas.includes(name);
                              return (
                                <li
                                  key={i}
                                  onClick={() => togglePersona(name)}
                                  className={`flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition-colors ${
                                    checked
                                      ? "border-violet-400/60 bg-violet-500/20"
                                      : "border-slate-600/40 bg-slate-800/40 hover:border-violet-500/40"
                                  }`}
                                >
                                  <div className={`w-4 h-4 rounded border flex-shrink-0 flex items-center justify-center transition-colors ${
                                    checked ? "bg-violet-500 border-violet-400" : "border-slate-500"
                                  }`}>
                                    {checked && (
                                      <svg width="10" height="10" viewBox="0 0 12 12" fill="none" stroke="white" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
                                        <polyline points="2 6 5 9 10 3" />
                                      </svg>
                                    )}
                                  </div>
                                  <div className="flex flex-col min-w-0">
                                    <span className="text-sm font-medium text-white truncate">{name}</span>
                                    {(title || company || email) && (
                                      <span className="text-xs text-slate-400 truncate">
                                        {[title, company, email].filter(Boolean).join(" · ")}
                                      </span>
                                    )}
                                  </div>
                                </li>
                              );
                            })}
                          </ul>
                        ) : (
                          <div className="text-sm text-violet-300/60">No personas found. The agent will continue without persona selection.</div>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center justify-between mt-2">
                      <span className="text-xs text-violet-300/60">
                        {selectedPersonas.length > 0
                          ? `${selectedPersonas.length} selected`
                          : personas.length > 0 ? "Select at least one persona" : ""}
                      </span>
                      <div className="flex gap-3">
                        <Button variant="outline" onClick={reset}>Cancel Mission</Button>
                        <Button
                          disabled={personas.length > 0 && selectedPersonas.length === 0}
                          onClick={() => {
                            resumeRun("select_personas", { selected_personas: selectedPersonas });
                            setSelectedPersonas([]);
                          }}
                          className="bg-violet-600 hover:bg-violet-500 text-white border-0 disabled:opacity-40"
                        >
                          {personas.length > 0 ? "Confirm Selection" : "Continue Without Personas"}
                        </Button>
                      </div>
                    </div>
                  </div>
                );
              }

              return (
                (() => {
                  // Find the message_generated event payload
                  const msgEvent = sentEvents
                    .slice()
                    .reverse()
                    .find((e: any) => e.event_type === "message_generated");
                  const messages: Array<{
                    persona_name?: string;
                    company?: string;
                    channel?: string;
                    subject?: string;
                    body?: string;
                  }> = msgEvent?.payload?.messages || [];

                  // Group by persona so we can show email + linkedin together
                  const byPersona: Record<string, typeof messages> = {};
                  for (const m of messages) {
                    const key = m.persona_name || "Unknown";
                    if (!byPersona[key]) byPersona[key] = [];
                    byPersona[key].push(m);
                  }

                  // Channel icon + label helpers
                  const channelIcon = (ch: string) =>
                    ch === "email" ? "✉️" : ch === "linkedin" ? "💼" : "📨";
                  const channelLabel = (ch: string) =>
                    ch === "email" ? "Email" : ch === "linkedin" ? "LinkedIn" : ch;
                  const channelColor = (ch: string) =>
                    ch === "email"
                      ? "border-blue-500/40 bg-blue-500/10"
                      : "border-sky-500/40 bg-sky-500/10";
                  const channelBadge = (ch: string) =>
                    ch === "email"
                      ? "bg-blue-500/20 text-blue-300 border border-blue-500/30"
                      : "bg-sky-500/20 text-sky-300 border border-sky-500/30";

                  return (
                    <div className="mission-approval-banner mt-4 p-4 rounded-xl border border-indigo-500/30 bg-indigo-500/10 flex flex-col gap-4">
                      {/* Header */}
                      <div className="flex items-start gap-3">
                        <span className="text-indigo-400 mt-1">
                          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                            <path d="M14.5 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7.5L14.5 2z"/>
                            <polyline points="14 2 14 8 20 8"/>
                            <path d="m9 15 2 2 4-4"/>
                          </svg>
                        </span>
                        <div>
                          <h3 className="text-indigo-300 font-semibold mb-0.5">Review Outreach Messages</h3>
                          <p className="text-xs text-indigo-200/60">
                            {messages.length} message{messages.length !== 1 ? "s" : ""} drafted across{" "}
                            {Object.keys(byPersona).length} persona{Object.keys(byPersona).length !== 1 ? "s" : ""}.
                            Approve to send all, or cancel to abort.
                          </p>
                        </div>
                      </div>

                      {/* Send sequence legend */}
                      <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-800/60 border border-slate-700/50">
                        <span className="text-xs text-slate-400 font-semibold uppercase tracking-wide">Send sequence:</span>
                        {["email", "linkedin"].map((ch, i) => (
                          <span key={ch} className="flex items-center gap-1">
                            {i > 0 && <span className="text-slate-600 text-xs">→</span>}
                            <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${channelBadge(ch)}`}>
                              {channelIcon(ch)} {channelLabel(ch)}
                            </span>
                          </span>
                        ))}
                        <span className="text-xs text-slate-500 ml-1">· sent simultaneously per persona</span>
                      </div>

                      {/* Per-persona message cards */}
                      {messages.length === 0 ? (
                        <div className="text-center py-4">
                          <p className="text-sm text-indigo-300/60 italic mb-2">No messages were generated.</p>
                          <p className="text-xs text-slate-400">
                            The agent couldn&apos;t find enough persona data to draft messages. Try restarting with a different objective or company.
                          </p>
                        </div>
                      ) : (
                        <div className="flex flex-col gap-4">
                          {Object.entries(byPersona).map(([persona, msgs]) => (
                            <div key={persona} className="rounded-lg border border-slate-700/60 bg-slate-900/40 overflow-hidden">
                              {/* Persona header */}
                              <div className="flex items-center gap-2 px-3 py-2 bg-slate-800/60 border-b border-slate-700/40">
                                <span className="text-base">👤</span>
                                <span className="text-sm font-semibold text-white">{persona}</span>
                                {msgs[0]?.company && (
                                  <span className="text-xs text-slate-400">@ {msgs[0].company}</span>
                                )}
                                <div className="ml-auto flex gap-1">
                                  {msgs.map((m) => (
                                    <span key={m.channel} className={`text-xs px-2 py-0.5 rounded-full font-medium ${channelBadge(m.channel || "")}`}>
                                      {channelIcon(m.channel || "")} {channelLabel(m.channel || "")}
                                    </span>
                                  ))}
                                </div>
                              </div>

                              {/* Channel messages */}
                              <div className="divide-y divide-slate-800/60">
                                {msgs.map((m, mi) => (
                                  <div key={mi} className={`p-3 ${channelColor(m.channel || "")}`}>
                                    <div className="flex items-center gap-2 mb-2">
                                      <span className="text-sm">{channelIcon(m.channel || "")}</span>
                                      <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${channelBadge(m.channel || "")}`}>
                                        {channelLabel(m.channel || "")}
                                      </span>
                                      {m.subject && (
                                        <span className="text-xs text-slate-300 font-medium truncate">
                                          Subject: {m.subject}
                                        </span>
                                      )}
                                    </div>
                                    <p className="text-sm text-slate-200 whitespace-pre-wrap font-sans leading-relaxed">
                                      {m.body}
                                    </p>
                                  </div>
                                ))}
                              </div>
                            </div>
                          ))}
                        </div>
                      )}

                      {/* Action buttons */}
                      <div className="flex justify-end gap-3 pt-1">
                        <Button variant="outline" onClick={reset}>Cancel Mission</Button>
                        <Button
                          disabled={messages.length === 0}
                          onClick={() => resumeRun("approve_message")}
                          className="bg-indigo-600 hover:bg-indigo-500 text-white border-0 disabled:opacity-40 disabled:cursor-not-allowed"
                        >
                          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className="mr-1.5">
                            <polyline points="22 2 11 13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/>
                          </svg>
                          Approve & Send All
                        </Button>
                      </div>
                    </div>
                  );
                })()
              );
            })()
          )}

          {/* Completion banner */}
          {phase === "completed" && (
            <div className="mission-complete-banner mt-4">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
              <div>
                <h3>Mission Completed Successfully</h3>
                <p>Generated {totalEventsGenerated} pipeline events across {currentStep} reasoning steps</p>
              </div>
            </div>
          )}

          {phase === "failed" && (
            <div className="mission-failed-banner mt-4">
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>
              <div>
                <h3>Mission Failed</h3>
                <p>The agent encountered an error. Check the details below.</p>
              </div>
            </div>
          )}

          {/* Results Panel (show after completion) */}
          {(phase === "completed" || phase === "failed") && (
            <ResultsPanel
              sentEvents={sentEvents}
              toolLog={toolLog}
              evaluation={evaluation}
              totalSteps={currentStep}
              correlationId={correlationId}
            />
          )}
        </>
      )}
    </div>
  );
}
