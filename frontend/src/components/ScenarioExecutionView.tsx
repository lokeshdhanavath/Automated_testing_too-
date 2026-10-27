import React, { useState } from "react";
import {
  CheckCircle2,
  XCircle,
  Clock,
  Camera,
  AlertCircle,
  Maximize2,
  Film,
  Square,
} from "lucide-react";
import type { StepExecutionResult, ArtifactItem } from "../services/api";

interface ScenarioExecutionViewProps {
  runId?: string;
  stepResults: StepExecutionResult[];
  status: string;
  runSummary?: { total?: number; passed?: number; failed?: number; skipped?: number } | null;
  videoArtifact?: ArtifactItem | null;
  onPreviewImage?: (item: ArtifactItem) => void;
  onStopRun?: () => void;
}

export const ScenarioExecutionView: React.FC<ScenarioExecutionViewProps> = ({
  stepResults,
  status,
  videoArtifact,
  onStopRun,
}) => {
  const [modalImage, setModalImage] = useState<string | null>(null);

  const isRunning = status.toLowerCase() === "running" || status.toLowerCase() === "queued";
  if (stepResults.length === 0 && !isRunning) {
    return null;
  }

  return (
    <div className="scenario-execution-view-wrap" style={{ marginTop: 20 }}>
      <div className="card">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
          <div>
            <h3 style={{ margin: 0, fontSize: "1.1rem", fontWeight: 700, color: "var(--v-text)" }}>
              Step-by-Step Scenario Execution
            </h3>
            <span style={{ fontSize: "0.82rem", color: "var(--v-text-secondary)" }}>
              Detailed step outcomes, durations, assertions, and captured failure artifacts.
            </span>
          </div>

          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            {(status.toLowerCase() === "running" || status.toLowerCase() === "queued") && onStopRun && (
              <button
                type="button"
                onClick={onStopRun}
                className="button button-danger button-small"
                style={{
                  background: "#dc2626",
                  borderColor: "#b91c1c",
                  color: "#ffffff",
                  fontWeight: 600,
                  display: "flex",
                  alignItems: "center",
                  gap: 6,
                  fontSize: "0.78rem",
                  padding: "4px 10px",
                }}
              >
                <Square size={13} fill="currentColor" />
                Stop Execution
              </button>
            )}
            <span
              className="badge"
              style={{
                background:
                  status.toLowerCase() === "passed"
                    ? "#DEF7EC"
                    : status.toLowerCase() === "failed" || status.toLowerCase() === "error"
                    ? "#FDE8E8"
                    : "#EFF6FF",
                color:
                  status.toLowerCase() === "passed"
                    ? "#03543F"
                    : status.toLowerCase() === "failed" || status.toLowerCase() === "error"
                    ? "#9B1C1C"
                    : "#1D4ED8",
                padding: "4px 10px",
                borderRadius: 6,
                fontWeight: 700,
                fontSize: "0.8rem",
              }}
            >
              {status.toUpperCase()}
            </span>
          </div>
        </div>

        {/* Step-by-Step Timeline Cards */}
        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          {stepResults.map((step) => {
            const isPass = step.status === "passed";
            const isFail = step.status === "failed";
            const isSkip = step.status === "skipped";

            return (
              <div
                key={step.id}
                style={{
                  padding: "12px 16px",
                  borderRadius: 8,
                  background: isFail
                    ? "#FEF2F2"
                    : isPass
                    ? "#F0FDF4"
                    : "var(--v-surface-2)",
                  border: isFail
                    ? "1px solid #FCA5A5"
                    : isPass
                    ? "1px solid #86EFAC"
                    : "1px solid var(--v-border)",
                  display: "flex",
                  flexDirection: "column",
                  gap: 8,
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    {isPass && <CheckCircle2 size={18} style={{ color: "#16A34A", flexShrink: 0 }} />}
                    {isFail && <XCircle size={18} style={{ color: "#DC2626", flexShrink: 0 }} />}
                    {isSkip && <Clock size={18} style={{ color: "var(--v-text-muted)", flexShrink: 0 }} />}

                    <span
                      style={{
                        background: "var(--v-surface)",
                        border: "1px solid var(--v-border)",
                        padding: "2px 7px",
                        borderRadius: 4,
                        fontSize: "0.75rem",
                        fontFamily: "monospace",
                        fontWeight: 700,
                        color: "var(--v-text)",
                      }}
                    >
                      {step.action_type.toUpperCase()}
                    </span>

                    <span style={{ fontWeight: 600, color: "var(--v-text)", fontSize: "0.92rem" }}>
                      {step.description || `Step ${step.step_order}`}
                    </span>
                  </div>

                  <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                    <span style={{ fontSize: "0.8rem", color: "var(--v-text-secondary)", fontFamily: "monospace" }}>
                      {step.duration_ms}ms
                    </span>

                    <span
                      className="badge"
                      style={{
                        background: isPass
                          ? "#DEF7EC"
                          : isFail
                          ? "#FDE8E8"
                          : "#F1F5F9",
                        color: isPass ? "#03543F" : isFail ? "#9B1C1C" : "var(--v-text-secondary)",
                        padding: "2px 8px",
                        borderRadius: 4,
                        fontSize: "0.75rem",
                        fontWeight: 700,
                      }}
                    >
                      {step.status.toUpperCase()}
                    </span>
                  </div>
                </div>

                {/* Error Callout */}
                {step.error_message && (
                  <div
                    style={{
                      background: "#FEE2E2",
                      border: "1px solid #FCA5A5",
                      borderRadius: 6,
                      padding: "8px 12px",
                      fontSize: "0.85rem",
                      color: "#991B1B",
                      display: "flex",
                      alignItems: "flex-start",
                      gap: 8,
                      fontFamily: "monospace",
                    }}
                  >
                    <AlertCircle size={15} style={{ marginTop: 2, flexShrink: 0 }} />
                    <div style={{ wordBreak: "break-word" }}>{step.error_message}</div>
                  </div>
                )}

                {/* Failure or Step Screenshot Thumbnail */}
                {step.screenshot_url && (
                  <div style={{ marginTop: 4, display: "flex", alignItems: "center", gap: 12 }}>
                    <div
                      style={{
                        position: "relative",
                        cursor: "pointer",
                        borderRadius: 6,
                        overflow: "hidden",
                        border: "1px solid var(--vq-border)",
                        width: 140,
                        height: 80,
                        background: "#000",
                      }}
                      onClick={() => setModalImage(step.screenshot_url!)}
                    >
                      <img
                        src={step.screenshot_url}
                        alt="Step Screenshot"
                        style={{ width: "100%", height: "100%", objectFit: "cover" }}
                      />
                      <div
                        style={{
                          position: "absolute",
                          inset: 0,
                          background: "rgba(0,0,0,0.3)",
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                          color: "#fff",
                        }}
                      >
                        <Camera size={18} />
                      </div>
                    </div>

                    <div style={{ fontSize: "0.82rem" }}>
                      <div style={{ fontWeight: 600, color: "var(--vq-text)" }}>
                        {isFail ? "Failure Screenshot Captured" : "Step Screenshot"}
                      </div>
                      <button
                        type="button"
                        style={{
                          background: "transparent",
                          border: "none",
                          color: "var(--v-accent)",
                          padding: 0,
                          cursor: "pointer",
                          display: "inline-flex",
                          alignItems: "center",
                          gap: 4,
                          marginTop: 4,
                          fontSize: "0.8rem",
                          fontWeight: 600,
                        }}
                        onClick={() => setModalImage(step.screenshot_url!)}
                      >
                        <Maximize2 size={12} /> View Full Size
                      </button>
                    </div>
                  </div>
                )}
              </div>
            );
          })}

          {isRunning && (
            <div
              className="vq-live-step-active"
              style={{
                padding: "14px 18px",
                borderRadius: 8,
                border: "1px solid rgba(37, 99, 235, 0.3)",
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                <div className="vq-live-pulse-dot" />
                <div>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <span
                      style={{
                        background: "#2563eb",
                        color: "#ffffff",
                        padding: "2px 8px",
                        borderRadius: 4,
                        fontSize: "0.74rem",
                        fontFamily: "monospace",
                        fontWeight: 700,
                      }}
                    >
                      STEP {stepResults.length + 1}
                    </span>
                    <span style={{ fontWeight: 700, color: "var(--v-text)", fontSize: "0.92rem" }}>
                      Executing live step in Playwright...
                    </span>
                  </div>
                  <div style={{ fontSize: "0.75rem", color: "var(--v-text-secondary)", marginTop: 4 }}>
                    Continuously running actions and resolving selectors in browser
                  </div>
                </div>
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <div className="vq-spinner-sm" style={{ width: 16, height: 16, borderWidth: 2 }} />
                <span style={{ fontSize: "0.78rem", fontWeight: 700, color: "#2563eb", fontFamily: "monospace" }}>
                  IN PROGRESS
                </span>
              </div>
            </div>
          )}
        </div>

        {/* Embedded HTML5 Video Player if video was recorded for this run */}
        {videoArtifact && (
          <div style={{ marginTop: 24, padding: 16, background: "var(--v-surface-2)", borderRadius: 8, border: "1px solid var(--v-border)" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
              <Film size={18} style={{ color: "var(--v-accent)" }} />
              <h4 style={{ margin: 0, fontSize: "1rem", fontWeight: 700, color: "var(--v-text)" }}>
                Playwright Execution Video Recording
              </h4>
            </div>
            <video
              controls
              style={{ width: "100%", maxHeight: 420, borderRadius: 6, background: "#000" }}
              src={videoArtifact.url}
            >
              Your browser does not support the video tag.
            </video>
          </div>
        )}
      </div>

      {/* Screenshot Lightbox Modal */}
      {modalImage && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0, 0, 0, 0.85)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 10000,
            padding: 24,
          }}
          onClick={() => setModalImage(null)}
        >
          <div style={{ position: "relative", maxWidth: "90vw", maxHeight: "90vh" }} onClick={(e) => e.stopPropagation()}>
            <img
              src={modalImage}
              alt="Screenshot preview"
              style={{ maxWidth: "100%", maxHeight: "85vh", borderRadius: 8, boxShadow: "0 10px 40px rgba(0,0,0,0.8)" }}
            />
            <button
              className="button button-secondary button-small"
              onClick={() => setModalImage(null)}
              style={{ position: "absolute", top: -14, right: -14, background: "#111", color: "#fff", borderRadius: "50%", padding: 6 }}
            >
              ✕
            </button>
          </div>
        </div>
      )}
    </div>
  );
};
