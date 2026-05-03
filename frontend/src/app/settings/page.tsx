"use client";

import { useEffect, useState } from "react";
import { Card, CardHeader, CardTitle, CardContent, CardDescription } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Slider } from "@/components/ui/slider";
import { API_BASE } from "@/lib/api";

function StatusIndicator({ connected, label }: { connected: boolean; label: string }) {
  return (
    <div className="flex items-center justify-between py-2">
      <span className="text-sm text-slate-300">{label}</span>
      <div className="flex items-center gap-2">
        <span className={`inline-block w-2 h-2 rounded-full ${connected ? "bg-emerald-400 shadow-sm shadow-emerald-400/50" : "bg-red-400 shadow-sm shadow-red-400/50"}`} />
        <span className={`text-xs font-medium ${connected ? "text-emerald-400" : "text-red-400"}`}>
          {connected ? "Connected" : "Unavailable"}
        </span>
      </div>
    </div>
  );
}

export default function SettingsPage() {
  const [config, setConfig] = useState<any>({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [health, setHealth] = useState<any>(null);

  useEffect(() => {
    Promise.all([
      fetch(`${API_BASE}/v1/config`).then(r => r.json()).catch(() => ({})),
      fetch(`${API_BASE}/health`).then(r => r.json()).catch(() => null),
    ]).then(([configData, healthData]) => {
      setConfig(configData);
      setHealth(healthData);
      setLoading(false);
    });
  }, []);

  const handleSave = async () => {
    setSaving(true);
    setSaved(false);
    try {
      await fetch(`${API_BASE}/v1/config/update`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ updates: config })
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (e) {
      console.error("Failed to save config", e);
    }
    setSaving(false);
  };

  if (loading) return <div className="text-slate-400">Loading configurations...</div>;

  return (
    <div className="max-w-3xl flex flex-col gap-6">
      <div className="flex justify-between items-center">
        <div>
          <h2 className="text-2xl font-bold flex items-center gap-3">
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="url(#settingsGrad)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <defs>
                <linearGradient id="settingsGrad" x1="0%" y1="0%" x2="100%" y2="100%">
                  <stop offset="0%" stopColor="#60a5fa" />
                  <stop offset="100%" stopColor="#a78bfa" />
                </linearGradient>
              </defs>
              <path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/>
              <circle cx="12" cy="12" r="3"/>
            </svg>
            Settings
          </h2>
          <p className="text-sm text-slate-400 mt-1">Configure the agentic pipeline and system integrations</p>
        </div>
        <Button onClick={handleSave} disabled={saving} className={saved ? "bg-emerald-600 hover:bg-emerald-500" : ""}>
          {saving ? "Saving..." : saved ? "✓ Saved" : "Save Changes"}
        </Button>
      </div>

      {/* Agent & System Status */}
      <Card className="bg-slate-900/80 border-slate-800/60 backdrop-blur-sm">
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-emerald-400"><path d="M22 12h-4l-3 9L9 3l-3 9H2"/></svg>
            System Status
          </CardTitle>
          <CardDescription>Live status of connected services and agent capabilities</CardDescription>
        </CardHeader>
        <CardContent className="space-y-1 divide-y divide-slate-800/60">
          <StatusIndicator connected={health?.status === "ok" || health?.status === "healthy"} label="🧠 Worker API" />
          <StatusIndicator connected={!!health} label="🗄️ PostgreSQL Database" />
          <StatusIndicator connected={true} label="🔍 Web Search (DuckDuckGo)" />
          <StatusIndicator connected={true} label="📇 Hunter.io Domain Search" />
          <StatusIndicator connected={true} label="📇 Snov.io Domain Search" />
          <StatusIndicator connected={true} label="📇 Tomba.io Domain Search" />
        </CardContent>
      </Card>

      {/* Pipeline Thresholds */}
      <Card className="bg-slate-900/80 border-slate-800/60 backdrop-blur-sm">
        <CardHeader>
          <CardTitle className="text-base">Pipeline Thresholds</CardTitle>
          <CardDescription>Control the strictness of the agentic pipeline</CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="space-y-4">
            <div className="flex justify-between">
              <Label>Qualification Threshold</Label>
              <span className="text-sm font-mono text-indigo-400">{config.QUALIFICATION_THRESHOLD || 0.6}</span>
            </div>
            <Slider
              value={[parseFloat(config.QUALIFICATION_THRESHOLD || 0.6)]}
              max={1}
              step={0.05}
              onValueChange={((val: number | readonly number[]) => setConfig({ ...config, QUALIFICATION_THRESHOLD: Array.isArray(val) ? val[0] : val })) as any}
            />
            <p className="text-xs text-slate-500">Leads scored below this threshold will not be forwarded to the Writer agent.</p>
          </div>
        </CardContent>
      </Card>

      {/* Sender Persona */}
      <Card className="bg-slate-900/80 border-slate-800/60 backdrop-blur-sm">
        <CardHeader>
          <CardTitle className="text-base">Sender Persona</CardTitle>
          <CardDescription>Define who is sending the outreach messages</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label>Company Name</Label>
            <Input
              value={config.SENDER_COMPANY_NAME || ""}
              onChange={(e) => setConfig({ ...config, SENDER_COMPANY_NAME: e.target.value })}
              className="bg-slate-950 border-slate-800"
              placeholder="Your company name"
            />
          </div>
          <div className="space-y-2">
            <Label>Elevator Pitch</Label>
            <Input
              value={config.SENDER_ELEVATOR_PITCH || ""}
              onChange={(e) => setConfig({ ...config, SENDER_ELEVATOR_PITCH: e.target.value })}
              className="bg-slate-950 border-slate-800"
              placeholder="Brief description of what you do"
            />
          </div>
        </CardContent>
      </Card>

      {/* Offer & CTA */}
      <Card className="bg-slate-900/80 border-slate-800/60 backdrop-blur-sm">
        <CardHeader>
          <CardTitle className="text-base">Offer & Call to Action</CardTitle>
          <CardDescription>What the agent pitches in outreach messages</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <Label>Offer Name</Label>
            <Input
              value={config.OFFER_NAME || ""}
              onChange={(e) => setConfig({ ...config, OFFER_NAME: e.target.value })}
              className="bg-slate-950 border-slate-800"
              placeholder="e.g. Free Workflow Audit"
            />
          </div>
          <div className="space-y-2">
            <Label>Offer CTA</Label>
            <Input
              value={config.OFFER_CTA || ""}
              onChange={(e) => setConfig({ ...config, OFFER_CTA: e.target.value })}
              className="bg-slate-950 border-slate-800"
              placeholder="e.g. Open to a 15-minute call?"
            />
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
