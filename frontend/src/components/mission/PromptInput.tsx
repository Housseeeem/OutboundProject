"use client";

import React, { useState } from "react";
import { Button } from "@/components/ui/button";

const EXAMPLE_PROMPTS = [
  "Find me B2B SaaS companies in Europe to sell my dev-tools product",
  "Discover AI startups in the US hiring aggressively for sales roles",
  "Target fintech companies with 50-500 employees using modern tech stacks",
  "Find logistics companies in Germany that recently raised funding",
];

interface PromptInputProps {
  onSubmit: (prompt: string) => void;
  disabled?: boolean;
  loading?: boolean;
}

export function PromptInput({ onSubmit, disabled, loading }: PromptInputProps) {
  const [value, setValue] = useState("");

  const handleSubmit = () => {
    if (value.trim().length < 3) return;
    onSubmit(value.trim());
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <div className="mission-prompt-wrapper">
      {/* Prompt Input */}
      <div className="mission-prompt-container">
        <div className="mission-prompt-glow" />
        <textarea
          id="mission-prompt-input"
          className="mission-prompt-textarea"
          placeholder="Describe what you're looking for... e.g. 'Find me businesses to sell my product to'"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={disabled}
          rows={3}
        />
        <div className="mission-prompt-footer">
          <span className="mission-prompt-charcount">
            {value.length} characters
          </span>
          <Button
            id="mission-launch-btn"
            onClick={handleSubmit}
            disabled={disabled || loading || value.trim().length < 3}
            className="mission-launch-btn"
          >
            {loading ? (
              <>
                <span className="mission-spinner" />
                Launching...
              </>
            ) : (
              <>
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 0 0-2.91-.09z"/><path d="m12 15-3-3a22 22 0 0 1 2-3.95A12.88 12.88 0 0 1 22 2c0 2.72-.78 7.5-6 11a22.35 22.35 0 0 1-4 2z"/><path d="M9 12H4s.55-3.03 2-4c1.62-1.08 5 0 5 0"/><path d="M12 15v5s3.03-.55 4-2c1.08-1.62 0-5 0-5"/></svg>
                Launch Mission
              </>
            )}
          </Button>
        </div>
      </div>

      {/* Example Chips */}
      <div className="mission-examples">
        <span className="mission-examples-label">Try an example:</span>
        <div className="mission-examples-grid">
          {EXAMPLE_PROMPTS.map((prompt, i) => (
            <button
              key={i}
              className="mission-example-chip"
              onClick={() => setValue(prompt)}
              disabled={disabled}
            >
              {prompt}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
