import { useState, useRef, useCallback } from "react";
import { API_BASE } from "@/lib/api";
const POLL_INTERVAL_MS = 2000;

export interface ScratchpadEntry {
  thought: string;
  action: Record<string, any>;
  observation: string;
}

export interface AgentEvaluation {
  score?: number;
  reasoning?: string;
  status?: string;
  [key: string]: any;
}

export interface ToolLogEntry {
  tool: string;
  status?: string;
  started_at?: string;
  finished_at?: string;
  duration_ms?: number;
  result?: any;
  error?: string;
  [key: string]: any;
}

export interface AgentRunState {
  run_id: string;
  correlation_id: string;
  objective: string;
  step: number;
  status: string;
  sent_events: any[];
  tool_log: ToolLogEntry[];
  scratchpad: ScratchpadEntry[];
  errors: string[];
  evaluation?: AgentEvaluation;
}

export type RunPhase = "idle" | "submitting" | "running" | "awaiting_approval" | "completed" | "failed";

export interface UseAgentRunReturn {
  phase: RunPhase;
  runId: string | null;
  correlationId: string | null;
  steps: ScratchpadEntry[];
  currentStep: number;
  totalEventsGenerated: number;
  sentEvents: any[];
  toolLog: ToolLogEntry[];
  evaluation: AgentEvaluation | null;
  errors: string[];
  startRun: (objective: string) => Promise<void>;
  resumeRun: (actionType: string, payload?: any) => Promise<void>;
  reset: () => void;
}

export function useAgentRun(): UseAgentRunReturn {
  const [phase, setPhase] = useState<RunPhase>("idle");
  const [runId, setRunId] = useState<string | null>(null);
  const [correlationId, setCorrelationId] = useState<string | null>(null);
  const [steps, setSteps] = useState<ScratchpadEntry[]>([]);
  const [currentStep, setCurrentStep] = useState(0);
  const [totalEventsGenerated, setTotalEventsGenerated] = useState(0);
  const [sentEvents, setSentEvents] = useState<any[]>([]);
  const [toolLog, setToolLog] = useState<ToolLogEntry[]>([]);
  const [evaluation, setEvaluation] = useState<AgentEvaluation | null>(null);
  const [errors, setErrors] = useState<string[]>([]);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const updateFromRunState = useCallback((state: AgentRunState) => {
    setSteps(state.scratchpad || []);
    setCurrentStep(state.step || 0);
    setSentEvents(state.sent_events || []);
    setTotalEventsGenerated((state.sent_events || []).length);
    setToolLog(state.tool_log || []);
    setErrors(state.errors || []);
    if (state.evaluation) {
      setEvaluation(state.evaluation);
    }
  }, []);

  const pollRun = useCallback(
    async (id: string) => {
      try {
        const res = await fetch(`${API_BASE}/v1/agent/runs/${id}`);
        if (!res.ok) return;
        const data = await res.json();
        const state: AgentRunState | undefined = data.state;
        const status: string = data.status;

        if (state) {
          updateFromRunState(state);
        }

        if (status === "completed") {
          setPhase("completed");
          stopPolling();
        } else if (status === "failed") {
          setPhase("failed");
          stopPolling();
        } else if (status === "awaiting_approval") {
          setPhase("awaiting_approval");
          stopPolling(); // Pause polling while waiting for human
        } else if (status === "running" && phase !== "running") {
          setPhase("running");
        }
      } catch (err) {
        console.error("Poll error:", err);
      }
    },
    [updateFromRunState, stopPolling]
  );

  const startRun = useCallback(
    async (objective: string) => {
      stopPolling();
      setPhase("submitting");
      setSteps([]);
      setCurrentStep(0);
      setSentEvents([]);
      setTotalEventsGenerated(0);
      setToolLog([]);
      setEvaluation(null);
      setErrors([]);

      try {
        const res = await fetch(`${API_BASE}/v1/agent/runs/async`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ objective, max_steps: 20 }),
        });

        if (!res.ok) {
          const errBody = await res.json().catch(() => ({}));
          throw new Error(errBody.detail || `HTTP ${res.status}`);
        }

        const data = await res.json();
        const id = data.run_id;
        setRunId(id);
        setCorrelationId(data.correlation_id);

        // Run is starting in the background — start polling
        setPhase("running");
        pollRef.current = setInterval(() => pollRun(id), POLL_INTERVAL_MS);
        
      } catch (err: any) {
        setPhase("failed");
        setErrors([err.message || "Failed to start agent run"]);
      }
    },
    [stopPolling, pollRun, updateFromRunState, phase]
  );

  const resumeRun = useCallback(async (actionType: string, payload?: any) => {
    if (!runId || phase !== "awaiting_approval") return;
    
    setPhase("submitting"); // Show loading briefly
    
    try {
      const res = await fetch(`${API_BASE}/v1/agent/runs/${runId}/resume`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action_type: actionType, payload }),
      });
      
      if (!res.ok) {
        const errBody = await res.json().catch(() => ({}));
        throw new Error(errBody.detail || `HTTP ${res.status}`);
      }
      
      // Resume polling since it might take a moment to evaluate or run
      setPhase("running");
      pollRef.current = setInterval(() => pollRun(runId), POLL_INTERVAL_MS);
      
    } catch (err: any) {
      setPhase("failed");
      setErrors([err.message || `Failed to resume run (${actionType})`]);
    }
  }, [runId, phase, pollRun]);

  const reset = useCallback(() => {
    stopPolling();
    setPhase("idle");
    setRunId(null);
    setCorrelationId(null);
    setSteps([]);
    setCurrentStep(0);
    setSentEvents([]);
    setTotalEventsGenerated(0);
    setToolLog([]);
    setEvaluation(null);
    setErrors([]);
  }, [stopPolling]);

  return {
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
  };
}
