import React, { useEffect, useState, useRef } from "react";
import {
  Play,
  CheckCircle2,
  CircleAlert,
  Globe,
  RefreshCw,
  Square,
  Layers,
  X,
  LoaderCircle,
  FolderKanban,
  Check,
  ExternalLink,
} from "lucide-react";
import {
  startInspectorBrowser,
  getInspectorBrowserStatus,
  closeInspectorSession,
  type ProjectConfig,
  type BrowserStatus,
  type ScenarioStep,
} from "../services/api";
import { ElementCatalog } from "./ElementCatalog";

interface CapturePageWorkspaceProps {
  activeProject: ProjectConfig | null;
  onNavigateToWorkflow?: () => void;
  onAddActionToWorkflow?: (step: ScenarioStep) => void;
}

export const CapturePageWorkspace: React.FC<CapturePageWorkspaceProps> = ({
  activeProject,
  onNavigateToWorkflow,
  onAddActionToWorkflow,
}) => {
  // Browser state
  const [browserStatus, setBrowserStatus] = useState<BrowserStatus | null>(null);
  const [browserLoading, setBrowserLoading] = useState(false);
  const [browserError, setBrowserError] = useState<string | null>(null);
  const [captureFeedback, setCaptureFeedback] = useState<{
    type: "success" | "error" | "info";
    text: string;
  } | null>(null);

  // Catalog refresh trigger
  const [catalogRefreshKey, setCatalogRefreshKey] = useState(0);

  // Step added toast
  const [stepAddedToast, setStepAddedToast] = useState<string | null>(null);

  const pollingRef = useRef<number | null>(null);

  // Poll browser status periodically & refresh catalog when returning to tab
  useEffect(() => {
    if (!activeProject?.id) return;

    void refreshStatus();

    // Poll status every 3 seconds while active
    const interval = window.setInterval(() => {
      void refreshStatus(false);
    }, 3000);
    pollingRef.current = interval;

    // Auto-refresh catalog when tab regains focus (user returns from browser)
    const onWindowFocus = () => {
      setCatalogRefreshKey((k) => k + 1);
      void refreshStatus(false);
    };
    window.addEventListener("focus", onWindowFocus);

    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current);
      window.removeEventListener("focus", onWindowFocus);
    };
  }, [activeProject?.id]);

  async function refreshStatus(showLoading = false) {
    if (!activeProject?.id) return;
    if (showLoading) setBrowserLoading(true);
    try {
      const status = await getInspectorBrowserStatus(activeProject.id);
      setBrowserStatus(status);
    } catch {
      setBrowserStatus(null);
    } finally {
      if (showLoading) setBrowserLoading(false);
    }
  }

  async function handleLaunchBrowser() {
    if (!activeProject?.id) return;
    setBrowserLoading(true);
    setBrowserError(null);
    setCaptureFeedback(null);
    try {
      const status = await startInspectorBrowser(activeProject.id, true, true);
      setBrowserStatus(status);
      setCaptureFeedback({
        type: "success",
        text: `Browser active! Use the floating Veriqon dock inside the browser to capture pages or elements with custom mapped names.`,
      });
      // Refresh catalog after launching
      setCatalogRefreshKey((k) => k + 1);
    } catch (err: any) {
      setBrowserError(err?.message || "Failed to launch visible browser.");
    } finally {
      setBrowserLoading(false);
    }
  }

  async function handleCloseBrowser() {
    if (!activeProject?.id) return;
    setBrowserLoading(true);
    try {
      await closeInspectorSession(activeProject.id);
      setBrowserStatus(null);
      setCaptureFeedback({ type: "info", text: "Browser session closed." });
      setCatalogRefreshKey((k) => k + 1);
    } catch (err: any) {
      setBrowserError(err?.message || "Failed to close browser session.");
    } finally {
      setBrowserLoading(false);
    }
  }

  function handleAddAction(step: ScenarioStep) {
    if (!activeProject?.id) return;

    try {
      const storageKey = `veriqon_steps_${activeProject.id}`;
      const existingRaw = localStorage.getItem(storageKey);
      let existingSteps: ScenarioStep[] = [];
      if (existingRaw) {
        try {
          existingSteps = JSON.parse(existingRaw);
        } catch {}
      }
      if (!Array.isArray(existingSteps)) existingSteps = [];

      const newStep = {
        ...step,
        step_order: existingSteps.length + 1,
      };

      const nextSteps = [...existingSteps, newStep];
      localStorage.setItem(storageKey, JSON.stringify(nextSteps));
    } catch (e) {
      console.warn("Could not sync step to localStorage:", e);
    }

    if (onAddActionToWorkflow) {
      onAddActionToWorkflow(step);
    }

    setStepAddedToast(`Added "${step.description || step.action_type}" to workflow!`);
    setTimeout(() => setStepAddedToast(null), 3500);
  }

  if (!activeProject) {
    return (
      <div className="card" style={{ padding: 32, textAlign: "center" }}>
        <FolderKanban size={36} color="var(--vq-muted)" style={{ marginBottom: 12 }} />
        <h3 style={{ margin: "0 0 8px 0" }}>No Application Selected</h3>
        <p style={{ color: "var(--vq-muted)", margin: 0 }}>
          Please select or register an application first to open the Capture workspace.
        </p>
      </div>
    );
  }

  const isBrowserConnected = !!browserStatus?.active;

  return (
    <div className="capture-workspace">
      {/* Header */}
      <div className="page-heading">
        <div>
          <div className="eyebrow">CAPTURE WORKSPACE</div>
          <h1 style={{ display: "flex", alignItems: "center", gap: 10 }}>
            Capture Application &amp; Elements
          </h1>
          <p>
            Launch <strong>{activeProject.name}</strong> in the browser and use the in-browser capture bar to capture whole pages or select elements with mapped names.
          </p>
        </div>
        {onNavigateToWorkflow && (
          <div className="page-heading-action">
            <button className="button button-secondary" onClick={onNavigateToWorkflow}>
              <Layers size={15} />
              Open Workflow Studio
            </button>
          </div>
        )}
      </div>

      {/* Step added toast banner */}
      {stepAddedToast && (
        <div className="capture-toast-banner">
          <Check size={16} />
          <span>{stepAddedToast}</span>
          {onNavigateToWorkflow && (
            <button className="toast-link-btn" onClick={onNavigateToWorkflow}>
              View in Workflow Studio →
            </button>
          )}
        </div>
      )}

      {/* Feedback banner */}
      {captureFeedback && (
        <div className={`capture-banner-msg ${captureFeedback.type}`}>
          {captureFeedback.type === "success" ? (
            <CheckCircle2 size={16} />
          ) : captureFeedback.type === "error" ? (
            <CircleAlert size={16} />
          ) : (
            <Check size={16} />
          )}
          <span>{captureFeedback.text}</span>
          <button className="close-banner-btn" onClick={() => setCaptureFeedback(null)}>
            <X size={14} />
          </button>
        </div>
      )}

      {browserError && (
        <div className="capture-banner-msg error">
          <CircleAlert size={16} />
          <span>{browserError}</span>
          <button className="close-banner-btn" onClick={() => setBrowserError(null)}>
            <X size={14} />
          </button>
        </div>
      )}

      {/* Main Single Action Section: Capture Application */}
      <section className="card capture-launch-card">
        <div className="capture-launch-content">
          <div className="capture-launch-info">
            <div className="capture-app-indicator">
              <Globe size={20} color="#06b6d4" />
              <span className="capture-app-name">{activeProject.name}</span>
              <span className="capture-app-url">{activeProject.base_url}</span>
            </div>
            <p className="capture-launch-hint">
              When you click <strong>Capture Application</strong>, Veriqon opens the application in a real browser with a floating in-browser capture bar. From there, you can click <strong>Capture This Page</strong> or <strong>Capture Any Element</strong> to name and save them directly.
            </p>
          </div>

          <div className="capture-launch-buttons">
            {!isBrowserConnected ? (
              <button
                className="button button-primary capture-main-btn"
                onClick={() => void handleLaunchBrowser()}
                disabled={browserLoading}
              >
                {browserLoading ? (
                  <>
                    <LoaderCircle size={18} className="spinner spin" />
                    Opening Application...
                  </>
                ) : (
                  <>
                    <Play size={18} />
                    Capture Application
                  </>
                )}
              </button>
            ) : (
              <div className="capture-connected-group">
                <div className="capture-live-badge">
                  <span className="status-dot active-green" />
                  <span>Browser Active: {browserStatus?.page_title || "Application"}</span>
                </div>
                <div style={{ display: "flex", gap: 10 }}>
                  <button
                    className="button button-primary"
                    onClick={() => void handleLaunchBrowser()}
                    disabled={browserLoading}
                    title="Bring open browser to the front"
                  >
                    <ExternalLink size={16} />
                    Switch to Browser
                  </button>
                  <button
                    className="button button-secondary"
                    style={{ color: "#ef4444" }}
                    onClick={() => void handleCloseBrowser()}
                    disabled={browserLoading}
                    title="Close browser session"
                  >
                    <Square size={14} />
                    Close Browser
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </section>

      {/* Saved / Captured Elements Catalog */}
      <section className="capture-catalog-section">
        <div className="catalog-section-header">
          <div className="catalog-header-left">
            <h2>Saved &amp; Captured Elements</h2>
            <p>
              Elements saved from the application browser appear here with their mapped names, ready to perform actions in workflows.
            </p>
          </div>
          <button
            className="button button-secondary"
            onClick={() => setCatalogRefreshKey((k) => k + 1)}
            title="Refresh elements from database"
          >
            <RefreshCw size={14} />
            Refresh Elements
          </button>
        </div>

        <ElementCatalog
          key={catalogRefreshKey}
          projectId={activeProject.id}
          projectName={activeProject.name}
          isInline={true}
          onAddActionToWorkflow={handleAddAction}
        />
      </section>
    </div>
  );
};
