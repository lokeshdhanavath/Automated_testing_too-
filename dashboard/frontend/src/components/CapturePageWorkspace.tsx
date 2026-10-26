import React, { useEffect, useState, useRef } from "react";
import {
  Camera,
  Crosshair,
  Play,
  CheckCircle2,
  CircleAlert,
  Globe,
  RefreshCw,
  Square,
  Save,
  ChevronDown,
  ChevronUp,
  Layers,
  ShieldCheck,
  Sparkles,
  X,
  LoaderCircle,
  FolderKanban,
  Check,
} from "lucide-react";
import {
  startInspectorBrowser,
  getInspectorBrowserStatus,
  closeInspectorSession,
  startElementPicker,
  getElementPickerStatus,
  cancelElementPicker,
  saveSelectedElement,
  captureCurrentPage,
  type ProjectConfig,
  type BrowserStatus,
  type DiscoveredElement,
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

  // Whole-page capture state
  const [capturingPage, setCapturingPage] = useState(false);
  const [captureFeedback, setCaptureFeedback] = useState<{
    type: "success" | "error" | "info";
    text: string;
  } | null>(null);

  // Picker mode state
  const [pickerActive, setPickerActive] = useState(false);
  const [pickerStatus, setPickerStatus] = useState<"idle" | "picking" | "selected">("idle");
  const [selectedCandidate, setSelectedCandidate] = useState<DiscoveredElement | null>(null);
  const [candidateFriendlyName, setCandidateFriendlyName] = useState("");
  const [candidateDescription, setCandidateDescription] = useState("");
  const [savingCandidate, setSavingCandidate] = useState(false);
  const [showTechnicalDetails, setShowTechnicalDetails] = useState(false);

  // Catalog refresh trigger
  const [catalogRefreshKey, setCatalogRefreshKey] = useState(0);

  // Step added toast
  const [stepAddedToast, setStepAddedToast] = useState<string | null>(null);

  const pollingRef = useRef<number | null>(null);

  // Poll browser status periodically
  useEffect(() => {
    if (!activeProject?.id) return;

    void refreshStatus();

    // Setup polling every 3 seconds
    const interval = window.setInterval(() => {
      void refreshStatus(false);
    }, 3000);
    pollingRef.current = interval;

    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current);
    };
  }, [activeProject?.id]);

  // Poll picker status frequently while picker mode is active
  useEffect(() => {
    if (!pickerActive || !activeProject?.id) return;

    const pickerInterval = window.setInterval(async () => {
      try {
        const res = await getElementPickerStatus(activeProject.id);
        if (res.status === "selected" && res.element) {
          setPickerActive(false);
          setPickerStatus("selected");
          setSelectedCandidate(res.element);
          setCandidateFriendlyName(res.element.friendly_name || "");
          setCandidateDescription(res.element.description || "");
        } else if (res.status === "picking") {
          setPickerStatus("picking");
        } else if (!res.active && pickerStatus === "picking") {
          setPickerActive(false);
          setPickerStatus("idle");
        }
      } catch (err) {
        // Picker check failed gracefully
      }
    }, 900);

    return () => clearInterval(pickerInterval);
  }, [pickerActive, pickerStatus, activeProject?.id]);

  async function refreshStatus(showLoading = false) {
    if (!activeProject?.id) return;
    if (showLoading) setBrowserLoading(true);
    setBrowserError(null);
    try {
      const status = await getInspectorBrowserStatus(activeProject.id);
      setBrowserStatus(status);
      if (status.picker_active && !pickerActive) {
        setPickerActive(true);
        setPickerStatus("picking");
      }
    } catch (err: any) {
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
        text: `Browser launched successfully! Navigating to ${status.page_title || activeProject.name}.`,
      });
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
      setPickerActive(false);
      setPickerStatus("idle");
      setSelectedCandidate(null);
      setCaptureFeedback({ type: "info", text: "Browser session closed." });
    } catch (err: any) {
      setBrowserError(err?.message || "Failed to close browser session.");
    } finally {
      setBrowserLoading(false);
    }
  }

  async function handleCapturePage() {
    if (!activeProject?.id) return;
    setCapturingPage(true);
    setCaptureFeedback(null);
    try {
      const res = await captureCurrentPage(activeProject.id);
      setCaptureFeedback({
        type: "success",
        text: `Captured ${res.total_scanned} elements on "${res.page_name || "Current Page"}" (${res.inserted} new, ${res.updated} updated).`,
      });
      // Refresh browser status and catalog
      await refreshStatus();
      setCatalogRefreshKey((k) => k + 1);
    } catch (err: any) {
      setCaptureFeedback({
        type: "error",
        text: err?.message || "Failed to capture current page elements.",
      });
    } finally {
      setCapturingPage(false);
    }
  }

  async function handleStartPicker() {
    if (!activeProject?.id) return;
    setCaptureFeedback(null);
    setSelectedCandidate(null);
    setPickerActive(true);
    setPickerStatus("picking");
    try {
      await startElementPicker(activeProject.id);
      setCaptureFeedback({
        type: "info",
        text: "🎯 Element selection active! Move your mouse and click any element in the visible browser window.",
      });
    } catch (err: any) {
      setPickerActive(false);
      setPickerStatus("idle");
      setCaptureFeedback({
        type: "error",
        text: err?.message || "Could not activate element selection mode.",
      });
    }
  }

  async function handleCancelPicker() {
    if (!activeProject?.id) return;
    setPickerActive(false);
    setPickerStatus("idle");
    setSelectedCandidate(null);
    try {
      await cancelElementPicker(activeProject.id);
    } catch (err) {
      // Ignore
    }
  }

  async function handleSavePickedElement() {
    if (!activeProject?.id || !selectedCandidate) return;
    setSavingCandidate(true);
    try {
      await saveSelectedElement(activeProject.id, {
        friendly_name: candidateFriendlyName.trim() || selectedCandidate.friendly_name,
        description: candidateDescription.trim() || selectedCandidate.description || "",
        category: selectedCandidate.category,
        tag_name: selectedCandidate.tag_name,
        role: selectedCandidate.role,
        label: selectedCandidate.label,
        placeholder: selectedCandidate.placeholder,
        locator_strategy: selectedCandidate.locator_strategy,
        locator_value: selectedCandidate.locator_value,
        in_dialog: selectedCandidate.in_dialog,
        dialog_title: selectedCandidate.dialog_title,
        page_url: selectedCandidate.page_url,
        page_name: selectedCandidate.page_name,
      });

      setCaptureFeedback({
        type: "success",
        text: `Element "${candidateFriendlyName.trim() || selectedCandidate.friendly_name}" saved to page catalog!`,
      });

      // Clear candidate and refresh
      setSelectedCandidate(null);
      setPickerStatus("idle");
      setCatalogRefreshKey((k) => k + 1);
    } catch (err: any) {
      setCaptureFeedback({
        type: "error",
        text: err?.message || "Failed to save selected element.",
      });
    } finally {
      setSavingCandidate(false);
    }
  }

  function handleAddAction(step: ScenarioStep) {
    if (!activeProject?.id) return;

    // Persist to localStorage workflow steps for this project so ScenarioBuilder picks it up
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
          Please select or register an application first to open the Capture Page workspace.
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
            <Crosshair size={24} color="#06b6d4" />
            Capture Page & Element Discovery
          </h1>
          <p>
            Interact directly with <strong>{activeProject.name}</strong> in a real browser, capture whole pages, or pick individual elements without manual selectors.
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
            <Sparkles size={16} />
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

      {/* Section 1: Observable Browser Control Center */}
      <section className="card capture-browser-card">
        <div className="capture-browser-header">
          <div className="capture-status-indicator">
            <span
              className={`status-dot ${
                pickerActive ? "pulse-cyan" : isBrowserConnected ? "active-green" : "idle-gray"
              }`}
            />
            <div className="capture-status-copy">
              <strong>
                {pickerActive
                  ? "Element Picker Active"
                  : isBrowserConnected
                  ? "Interactive Browser Active (Visible Window)"
                  : "Browser Session Disconnected"}
              </strong>
              <span>
                {isBrowserConnected
                  ? `Observing "${browserStatus?.page_name || "Application"}" · PID: ${activeProject.name}`
                  : "Start the visible browser to interact with the actual application."}
              </span>
            </div>
          </div>

          <div className="capture-browser-actions">
            {!isBrowserConnected ? (
              <button
                className="button button-primary"
                onClick={() => void handleLaunchBrowser()}
                disabled={browserLoading}
              >
                {browserLoading ? (
                  <>
                    <LoaderCircle size={15} className="spinner spin" />
                    Opening Browser...
                  </>
                ) : (
                  <>
                    <Play size={15} />
                    Open Application in Browser
                  </>
                )}
              </button>
            ) : (
              <div style={{ display: "flex", gap: 8 }}>
                <button
                  className="button button-secondary"
                  onClick={() => void refreshStatus(true)}
                  disabled={browserLoading}
                  title="Refresh observable page title and URL"
                >
                  <RefreshCw size={14} className={browserLoading ? "spin" : ""} />
                  Refresh
                </button>
                <button
                  className="button button-secondary"
                  style={{ color: "#ef4444" }}
                  onClick={() => void handleCloseBrowser()}
                  disabled={browserLoading}
                >
                  <Square size={14} />
                  Close Browser
                </button>
              </div>
            )}
          </div>
        </div>

        {/* Live Observability Info Box */}
        <div className="capture-meta-grid">
          <div className="capture-meta-cell">
            <small>TARGET APPLICATION</small>
            <div className="capture-meta-val">
              <Globe size={14} color="#06b6d4" />
              <span>{activeProject.name}</span>
            </div>
          </div>

          <div className="capture-meta-cell">
            <small>CURRENT PAGE TITLE</small>
            <div className="capture-meta-val" title={browserStatus?.page_title || "None"}>
              <strong>{browserStatus?.page_title || (isBrowserConnected ? "Loading page..." : "—")}</strong>
            </div>
          </div>

          <div className="capture-meta-cell full-width">
            <small>OBSERVED URL (CREDENTIALS &amp; TOKENS REDACTED)</small>
            <div className="capture-meta-val url-val">
              <span title="Security Redaction Active" style={{ display: "inline-flex", alignItems: "center" }}>
                <ShieldCheck size={14} color="#10b981" />
              </span>
              <code>
                {browserStatus?.display_url || activeProject.base_url || "—"}
              </code>
            </div>
          </div>
        </div>

        {/* Architecture Note */}
        <div className="capture-notice-footer">
          <CircleAlert size={14} color="#06b6d4" />
          <span>
            Veriqon runs an authentic desktop Chromium browser. Click links, open menus, and navigate freely in that browser. Veriqon automatically captures the rendered state without frame-busting or token expiration issues.
          </span>
        </div>
      </section>

      {/* Section 2: Capture Command Bar */}
      <section className="card capture-command-bar">
        <div className="command-bar-left">
          <button
            className="button button-primary"
            style={{ minWidth: 170, backgroundColor: "#0284c7" }}
            onClick={() => void handleCapturePage()}
            disabled={capturingPage || browserLoading}
          >
            {capturingPage ? (
              <>
                <LoaderCircle size={15} className="spinner spin" />
                Scanning DOM...
              </>
            ) : (
              <>
                <Camera size={15} />
                Capture This Page
              </>
            )}
          </button>

          {!pickerActive ? (
            <button
              className="button button-secondary"
              style={{ minWidth: 200, borderColor: "#06b6d4", color: "#06b6d4" }}
              onClick={() => void handleStartPicker()}
              disabled={!isBrowserConnected || capturingPage}
              title={!isBrowserConnected ? "Please open the browser first" : "Click to highlight and select an element"}
            >
              <Crosshair size={15} />
              Select Element to Capture
            </button>
          ) : (
            <button
              className="button button-secondary"
              style={{ backgroundColor: "#ef44441a", color: "#ef4444", borderColor: "#ef4444" }}
              onClick={() => void handleCancelPicker()}
            >
              <X size={15} />
              Cancel Element Picker
            </button>
          )}
        </div>

        <div className="command-bar-right">
          {pickerActive && (
            <div className="picker-active-badge">
              <span className="picker-pulse-dot" />
              <span>Click any element in the visible browser to inspect</span>
            </div>
          )}
        </div>
      </section>

      {/* Section 3: Visual Element Picker Result Preview Card */}
      {selectedCandidate && (
        <section className="card element-preview-card">
          <div className="preview-card-header">
            <div className="preview-card-title">
              <CheckCircle2 size={18} color="#10b981" />
              <div>
                <strong>Selected Element Preview</strong>
                <span>Confirm or customize before saving to the page catalog</span>
              </div>
            </div>
            <button
              className="button button-secondary"
              style={{ padding: "4px 8px" }}
              onClick={() => setSelectedCandidate(null)}
            >
              <X size={14} />
            </button>
          </div>

          <div className="preview-form-grid">
            <div className="preview-field">
              <label>Friendly Name</label>
              <input
                type="text"
                className="input"
                value={candidateFriendlyName}
                onChange={(e) => setCandidateFriendlyName(e.target.value)}
                placeholder="e.g. Save Timesheet button"
              />
            </div>

            <div className="preview-field">
              <label>Plain-Language Description</label>
              <input
                type="text"
                className="input"
                value={candidateDescription}
                onChange={(e) => setCandidateDescription(e.target.value)}
                placeholder="e.g. Saves the current timesheet"
              />
            </div>

            <div className="preview-meta-row">
              <span className="badge category-badge">{selectedCandidate.category}</span>
              <span className="badge tag-badge">&lt;{selectedCandidate.tag_name}&gt;</span>
              {selectedCandidate.role && (
                <span className="badge role-badge">role="{selectedCandidate.role}"</span>
              )}
              {selectedCandidate.in_dialog && (
                <span className="badge dialog-badge">
                  In Modal: {selectedCandidate.dialog_title || "Dialog"}
                </span>
              )}
              <span className="page-pill">
                Page: {selectedCandidate.page_name || "Current Page"}
              </span>
            </div>

            {/* Collapsible Technical Details */}
            <div className="technical-expander">
              <button
                type="button"
                className="technical-toggle-btn"
                onClick={() => setShowTechnicalDetails(!showTechnicalDetails)}
              >
                <span>Technical Locator Information</span>
                {showTechnicalDetails ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
              </button>

              {showTechnicalDetails && (
                <div className="technical-details-box">
                  <div className="tech-row">
                    <span className="tech-label">Strategy:</span>
                    <code>{selectedCandidate.locator_strategy}</code>
                  </div>
                  <div className="tech-row">
                    <span className="tech-label">Locator Value:</span>
                    <code>{selectedCandidate.locator_value}</code>
                  </div>
                  {selectedCandidate.label && (
                    <div className="tech-row">
                      <span className="tech-label">Associated Label:</span>
                      <span>{selectedCandidate.label}</span>
                    </div>
                  )}
                  {selectedCandidate.placeholder && (
                    <div className="tech-row">
                      <span className="tech-label">Placeholder:</span>
                      <span>{selectedCandidate.placeholder}</span>
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Action confirmation buttons */}
            <div className="preview-actions">
              <button
                className="button button-primary"
                style={{ backgroundColor: "#10b981" }}
                onClick={() => void handleSavePickedElement()}
                disabled={savingCandidate}
              >
                {savingCandidate ? (
                  <>
                    <LoaderCircle size={15} className="spinner spin" />
                    Saving Element...
                  </>
                ) : (
                  <>
                    <Save size={15} />
                    Save Element to Catalog
                  </>
                )}
              </button>
              <button
                className="button button-secondary"
                onClick={() => handleCancelPicker()}
                disabled={savingCandidate}
              >
                Cancel Selection
              </button>
            </div>
          </div>
        </section>
      )}

      {/* Section 4: Page-wise Organization & Elements Catalog */}
      <section className="capture-catalog-section">
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
