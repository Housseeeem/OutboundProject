"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { Space_Grotesk } from "next/font/google";

import "./orchestrate.css";
import { API_BASE } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";

const headingFont = Space_Grotesk({ subsets: ["latin"] });

type RunPhase = "idle" | "submitting" | "completed" | "failed";

type OrchestrateResponse = {
  accepted: boolean;
  correlation_id: string;
  lead_ingested_event_id: string;
  detective?: any;
  writer?: any;
};

type TraceEvent = {
  event_type: string;
  module: string;
  timestamp: string;
  payload: any;
};

const SAMPLE = {
  lead: {
    companyId: "acme-001",
    companyName: "Acme Logistics",
    companyDomain: "acme-logistics.com",
    prospectName: "Jade Carter",
    prospectRole: "VP Operations",
    readyForOutreach: true,
  },
  writer: {
    targetProspect: "Jade Carter",
    targetCompany: "Acme Logistics",
    senderCompany: "Atlas DevTools",
    offerName: "Workflow Audit",
    offerCta: "Open to a 15-minute call?",
    offerPainPoints: "manual ops, data silos, slow handoffs",
  },
};

export default function OrchestratePage() {
  const [phase, setPhase] = useState<RunPhase>("idle");
  const [error, setError] = useState("");
  const [result, setResult] = useState<OrchestrateResponse | null>(null);
  const [trace, setTrace] = useState<TraceEvent[] | null>(null);
  const [traceLoading, setTraceLoading] = useState(false);
  const [correlationId, setCorrelationId] = useState("");

  const [lead, setLead] = useState({
    companyId: "",
    companyName: "",
    companyDomain: "",
    prospectName: "",
    prospectRole: "",
    readyForOutreach: true,
  });

  const [writer, setWriter] = useState({
    targetProspect: "",
    targetCompany: "",
    senderCompany: "",
    offerName: "",
    offerCta: "",
    offerPainPoints: "",
  });

  const canSubmit =
    lead.companyName.trim().length > 0 &&
    writer.targetProspect.trim().length > 0 &&
    (writer.targetCompany.trim().length > 0 || lead.companyName.trim().length > 0) &&
    writer.senderCompany.trim().length > 0 &&
    writer.offerName.trim().length > 0 &&
    phase !== "submitting";

  const requestPayload = useMemo(() => {
    const leadPayload: Record<string, any> = {
      company_id: lead.companyId || lead.companyDomain || lead.companyName,
      company_data: {
        name: lead.companyName,
        domain: lead.companyDomain,
      },
      personas: lead.prospectName
        ? [
            {
              name: lead.prospectName,
              title: lead.prospectRole || "",
            },
          ]
        : [],
      enrichment_data: {},
      intent_signals: {},
      readiness_flags: {
        ready_for_outreach: lead.readyForOutreach,
      },
      event_type: "lead_ingested",
      timestamp: new Date().toISOString(),
    };

    const writerRequest = {
      target_prospect: writer.targetProspect,
      target_company: writer.targetCompany || lead.companyName,
      prospect_role: lead.prospectRole || undefined,
      company_details: {
        company_name: writer.senderCompany,
      },
      selected_offer: {
        offer_name: writer.offerName,
        pain_points: writer.offerPainPoints
          ? writer.offerPainPoints
              .split(",")
              .map((item) => item.trim())
              .filter(Boolean)
          : [],
        cta: writer.offerCta || undefined,
      },
    };

    const payload: Record<string, any> = {
      lead: leadPayload,
      writer_request: writerRequest,
    };

    if (correlationId.trim()) {
      payload.correlation_id = correlationId.trim();
    }

    return payload;
  }, [lead, writer, correlationId]);

  const handleSubmit = async () => {
    if (!canSubmit) return;
    setPhase("submitting");
    setError("");
    setResult(null);
    setTrace(null);

    try {
      const res = await fetch(`${API_BASE}/v1/orchestrate/generate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(requestPayload),
      });

      if (!res.ok) {
        const errBody = await res.json().catch(() => ({}));
        throw new Error(errBody.detail || `HTTP ${res.status}`);
      }

      const data = (await res.json()) as OrchestrateResponse;
      setResult(data);
      setPhase("completed");
      if (data.correlation_id) {
        setCorrelationId(data.correlation_id);
      }
    } catch (err: any) {
      setError(err.message || "Failed to orchestrate run");
      setPhase("failed");
    }
  };

  const loadTrace = async () => {
    const id = result?.correlation_id || correlationId;
    if (!id) return;
    setTraceLoading(true);
    try {
      const res = await fetch(`${API_BASE}/v1/events/trace/${id}`);
      if (!res.ok) {
        throw new Error("Trace not found or server error");
      }
      const data = (await res.json()) as TraceEvent[];
      setTrace(data);
    } catch (err: any) {
      setError(err.message || "Failed to load trace");
    }
    setTraceLoading(false);
  };

  const resetForm = () => {
    setPhase("idle");
    setError("");
    setResult(null);
    setTrace(null);
    setCorrelationId("");
    setLead({
      companyId: "",
      companyName: "",
      companyDomain: "",
      prospectName: "",
      prospectRole: "",
      readyForOutreach: true,
    });
    setWriter({
      targetProspect: "",
      targetCompany: "",
      senderCompany: "",
      offerName: "",
      offerCta: "",
      offerPainPoints: "",
    });
  };

  return (
    <div className="orchestrate-page">
      <div className="orchestrate-shell">
        <div className="orchestrate-hero">
          <h1 className={`${headingFont.className} orchestrate-hero-title`}>
            Orchestration Console
          </h1>
          <p className="orchestrate-hero-subtitle">
            Trigger the Worker control-plane: ingest a lead, score it, and draft outreach in one run.
          </p>
        </div>
      </div>

      {error && (
        <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-200">
          {error}
        </div>
      )}

      <div className="orchestrate-grid">
        <Card className="orchestrate-card">
          <CardHeader>
            <CardTitle>Lead + Writer Inputs</CardTitle>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="orchestrate-label">Lead Payload</span>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    setLead(SAMPLE.lead);
                    setWriter(SAMPLE.writer);
                  }}
                >
                  Load Sample
                </Button>
              </div>
              <div className="grid gap-3 md:grid-cols-2">
                <div className="space-y-2">
                  <Label>Company Name</Label>
                  <Input
                    value={lead.companyName}
                    onChange={(e) => setLead({ ...lead, companyName: e.target.value })}
                    placeholder="Acme Logistics"
                  />
                </div>
                <div className="space-y-2">
                  <Label>Company Domain</Label>
                  <Input
                    value={lead.companyDomain}
                    onChange={(e) => setLead({ ...lead, companyDomain: e.target.value })}
                    placeholder="acme-logistics.com"
                  />
                </div>
                <div className="space-y-2">
                  <Label>Prospect Name</Label>
                  <Input
                    value={lead.prospectName}
                    onChange={(e) => setLead({ ...lead, prospectName: e.target.value })}
                    placeholder="Jade Carter"
                  />
                </div>
                <div className="space-y-2">
                  <Label>Prospect Role</Label>
                  <Input
                    value={lead.prospectRole}
                    onChange={(e) => setLead({ ...lead, prospectRole: e.target.value })}
                    placeholder="VP Operations"
                  />
                </div>
              </div>
              <div className="flex items-center justify-between rounded-lg border border-slate-800 bg-slate-900/60 px-3 py-2">
                <div>
                  <div className="text-sm text-slate-200">Ready for outreach</div>
                  <div className="orchestrate-hint">Detective skips leads marked not ready.</div>
                </div>
                <input
                  type="checkbox"
                  checked={lead.readyForOutreach}
                  onChange={(e) => setLead({ ...lead, readyForOutreach: e.target.checked })}
                  className="h-4 w-4 accent-emerald-400"
                />
              </div>
            </div>

            <Separator className="bg-slate-800" />

            <div className="space-y-3">
              <span className="orchestrate-label">Writer Request</span>
              <div className="grid gap-3 md:grid-cols-2">
                <div className="space-y-2">
                  <Label>Target Prospect</Label>
                  <Input
                    value={writer.targetProspect}
                    onChange={(e) => setWriter({ ...writer, targetProspect: e.target.value })}
                    placeholder="Jade Carter"
                  />
                </div>
                <div className="space-y-2">
                  <Label>Target Company</Label>
                  <Input
                    value={writer.targetCompany}
                    onChange={(e) => setWriter({ ...writer, targetCompany: e.target.value })}
                    placeholder={lead.companyName || "Acme Logistics"}
                  />
                </div>
                <div className="space-y-2">
                  <Label>Sender Company</Label>
                  <Input
                    value={writer.senderCompany}
                    onChange={(e) => setWriter({ ...writer, senderCompany: e.target.value })}
                    placeholder="Atlas DevTools"
                  />
                </div>
                <div className="space-y-2">
                  <Label>Offer Name</Label>
                  <Input
                    value={writer.offerName}
                    onChange={(e) => setWriter({ ...writer, offerName: e.target.value })}
                    placeholder="Workflow Audit"
                  />
                </div>
                <div className="space-y-2 md:col-span-2">
                  <Label>Offer Pain Points (comma-separated)</Label>
                  <Input
                    value={writer.offerPainPoints}
                    onChange={(e) => setWriter({ ...writer, offerPainPoints: e.target.value })}
                    placeholder="manual ops, data silos, slow handoffs"
                  />
                </div>
                <div className="space-y-2 md:col-span-2">
                  <Label>CTA</Label>
                  <Input
                    value={writer.offerCta}
                    onChange={(e) => setWriter({ ...writer, offerCta: e.target.value })}
                    placeholder="Open to a 15-minute call?"
                  />
                </div>
              </div>
            </div>

            <Separator className="bg-slate-800" />

            <div className="space-y-2">
              <Label>Correlation ID (optional)</Label>
              <Input
                value={correlationId}
                onChange={(e) => setCorrelationId(e.target.value)}
                placeholder="Leave blank to auto-generate"
              />
            </div>

            <div className="flex flex-wrap items-center gap-3">
              <Button onClick={handleSubmit} disabled={!canSubmit}>
                {phase === "submitting" ? "Launching..." : "Run Orchestration"}
              </Button>
              <Button variant="outline" onClick={resetForm}>
                Reset
              </Button>
              {result?.correlation_id && (
                <Link
                  href={`/traces?correlation_id=${encodeURIComponent(result.correlation_id)}`}
                  className="text-sm text-emerald-300 hover:text-emerald-200"
                >
                  Open trace view
                </Link>
              )}
            </div>
          </CardContent>
        </Card>

        <div className="space-y-4">
          <Card className="orchestrate-card">
            <CardHeader>
              <CardTitle>Run Summary</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {result ? (
                <>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="orchestrate-badge">Correlation</span>
                    <span className="text-xs font-mono text-slate-300 break-all">
                      {result.correlation_id}
                    </span>
                  </div>
                  <div className="space-y-2">
                    <div className="text-xs uppercase tracking-widest text-slate-400">Detective Artifact</div>
                    <pre className="orchestrate-json">
                      {JSON.stringify(result.detective || {}, null, 2)}
                    </pre>
                  </div>
                  <div className="space-y-2">
                    <div className="text-xs uppercase tracking-widest text-slate-400">Writer Artifact</div>
                    <pre className="orchestrate-json">
                      {JSON.stringify(result.writer || {}, null, 2)}
                    </pre>
                  </div>
                </>
              ) : (
                <div className="orchestrate-hint">
                  Submit a lead to see the immediate Detective + Writer artifacts here.
                </div>
              )}
            </CardContent>
          </Card>

          <Card className="orchestrate-card">
            <CardHeader>
              <CardTitle>Trace Timeline</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="orchestrate-hint">Load recent events for this correlation.</span>
                <Button variant="outline" size="sm" onClick={loadTrace} disabled={!result?.correlation_id || traceLoading}>
                  {traceLoading ? "Loading..." : "Refresh Trace"}
                </Button>
              </div>
              {trace && trace.length > 0 ? (
                <div className="orchestrate-trace-list">
                  {trace.map((evt, idx) => (
                    <div key={idx} className="orchestrate-trace-item">
                      <div className="orchestrate-trace-meta">
                        <span className="orchestrate-trace-type">{evt.event_type}</span>
                        <span>{new Date(evt.timestamp).toLocaleString()}</span>
                      </div>
                      <div className="text-xs text-slate-400 mb-2">Module: {evt.module}</div>
                      <pre className="orchestrate-json">{JSON.stringify(evt.payload, null, 2)}</pre>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="orchestrate-hint">No trace loaded yet.</div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>

      <Card className="orchestrate-card">
        <CardHeader>
          <CardTitle>Request Preview</CardTitle>
        </CardHeader>
        <CardContent>
          <pre className="orchestrate-json">{JSON.stringify(requestPayload, null, 2)}</pre>
        </CardContent>
      </Card>
    </div>
  );
}
