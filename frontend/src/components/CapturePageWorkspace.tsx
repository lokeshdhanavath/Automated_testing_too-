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
  Camera,
  Navigation,
  Bookmark,
  Laptop,
  Crosshair,
} from "lucide-react";
import {
  startInspectorBrowser,
  navigateInspectorBrowser,
  captureActivePageFromDashboard,
  getInspectorBrowserStatus,
  closeInspectorSession,
  updateProject,
  startElementPicker,
  type ProjectConfig,
  type BrowserStatus,
  type ScenarioStep,
} from "../services/api";
import { ElementCatalog } from "./ElementCatalog";

interface CapturePageWorkspaceProps {
  activeProject: ProjectConfig | null;
  onNavigateToWorkflow?: () => void;
  onAddActionToWorkflow?: (step: ScenarioStep) => void;
  onProjectUpdated?: (updated: ProjectConfig) => void;
}

export const CapturePageWorkspace: React.FC<CapturePageWorkspaceProps> = ({
  activeProject,
  onNavigateToWorkflow,
  onAddActionToWorkflow,
  onProjectUpdated,
}) => {
  // Browser state
  const [browserStatus, setBrowserStatus] = useState<BrowserStatus | null>(null);
  const [browserLoading, setBrowserLoading] = useState(false);
  const [browserError, setBrowserError] = useState<string | null>(null);
  const [captureFeedback, setCaptureFeedback] = useState<{
    type: "success" | "error" | "info";
    text: string;
  } | null>(null);

  // Browser engine choice: chromium, chrome, firefox, webkit
  const [selectedBrowser, setSelectedBrowser] = useState<string>(
    activeProject?.browser || "chromium"
  );

  // Target URL input
  const [targetUrl, setTargetUrl] = useState<string>(
    activeProject?.base_url || ""
  );
  const [isSavingUrl, setIsSavingUrl] = useState(false);
  const [isCapturing, setIsCapturing] = useState(false);

  // Catalog refresh trigger
  const [catalogRefreshKey, setCatalogRefreshKey] = useState(0);

  // Step added toast
  const [stepAddedToast, setStepAddedToast] = useState<string | null>(null);

  const pollingRef = useRef<number | null>(null);

  // Keep target URL in sync when activeProject changes
  useEffect(() => {
    if (activeProject?.base_url) {
      setTargetUrl(activeProject.base_url);
    }
    if (activeProject?.browser) {
      setSelectedBrowser(activeProject.browser);
    }
  }, [activeProject?.id, activeProject?.base_url, activeProject?.browser]);

  // Poll browser status periodically & refresh catalog when returning to tab
  useEffect(() => {
    if (!activeProject?.id) return;

    void refreshStatus();

    const interval = window.setInterval(() => {
      void refreshStatus(false);
    }, 2500);
    pollingRef.current = interval;

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

  async function handleLaunchBrowser(urlOverride?: string) {
    if (!activeProject?.id) return;
    const urlToOpen = (urlOverride || targetUrl || activeProject.base_url).trim();
    if (!urlToOpen) {
      setBrowserError("Please enter a valid URL to open.");
      return;
    }

    setBrowserLoading(true);
    setBrowserError(null);
    setCaptureFeedback(null);
    try {
      const status = await startInspectorBrowser(
        activeProject.id,
        true,
        true,
        selectedBrowser,
        urlToOpen
      );
      setBrowserStatus(status);
      setCaptureFeedback({
        type: "success",
        text: `Browser active (${selectedBrowser.toUpperCase()})! Use the floating dock inside the browser or the "Capture Active Page" button below to extract elements.`,
      });
      setCatalogRefreshKey((k) => k + 1);
    } catch (err: any) {
      setBrowserError(err?.message || `Failed to launch ${selectedBrowser} browser.`);
    } finally {
      setBrowserLoading(false);
    }
  }

  async function handleNavigateBrowser() {
    if (!activeProject?.id) return;
    const cleanUrl = targetUrl.trim();
    if (!cleanUrl) {
      setBrowserError("Please enter a valid URL to navigate to.");
      return;
    }

    setBrowserLoading(true);
    setBrowserError(null);
    setCaptureFeedback(null);
    try {
      const status = await navigateInspectorBrowser(
        activeProject.id,
        cleanUrl,
        false,
        selectedBrowser
      );
      setBrowserStatus(status);
      setCaptureFeedback({
        type: "success",
        text: `Navigated browser to ${cleanUrl}!`,
      });
      setCatalogRefreshKey((k) => k + 1);
    } catch (err: any) {
      setBrowserError(err?.message || "Failed to navigate browser to URL.");
    } finally {
      setBrowserLoading(false);
    }
  }

  async function handleSaveAsDefaultUrl() {
    if (!activeProject?.id) return;
    const cleanUrl = targetUrl.trim();
    if (!cleanUrl) return;

    setIsSavingUrl(true);
    try {
      const updated = await updateProject(activeProject.id, {
        ...activeProject,
        base_url: cleanUrl,
        browser: selectedBrowser as any,
      });
      if (onProjectUpdated) {
        onProjectUpdated(updated);
      }
      setCaptureFeedback({
        type: "success",
        text: `Application URL saved as default: ${cleanUrl}`,
      });
    } catch (err: any) {
      setBrowserError(err?.message || "Could not save URL to application settings.");
    } finally {
      setIsSavingUrl(false);
    }
  }

  async function handleDirectCapture() {
    if (!activeProject?.id) return;
    setIsCapturing(true);
    setBrowserError(null);
    setCaptureFeedback(null);
    try {
      const data = await captureActivePageFromDashboard(activeProject.id);
      setCaptureFeedback({
        type: "success",
        text: `✓ Successfully captured ${data.total_scanned} elements on "${data.page_name || 'Active Page'}"!`,
      });
      setCatalogRefreshKey((k) => k + 1);
    } catch (err: any) {
      setBrowserError(err?.message || "Failed to capture elements from active page.");
    } finally {
      setIsCapturing(false);
    }
  }

  async function handleStartPicker() {
    if (!activeProject?.id) return;
    setBrowserError(null);
    try {
      await startElementPicker(activeProject.id);
      setCaptureFeedback({
        type: "success",
        text: "🎯 Element Picker activated in your browser! Click any element to capture and save it.",
      });
      setCatalogRefreshKey((k) => k + 1);
    } catch (err: any) {
      setBrowserError(err?.message || "Failed to start element picker. Ensure browser is open.");
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
  const isErrorPage = !!browserStatus?.is_error_page || (browserStatus?.current_url?.includes("chrome-error") ?? false);

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
            Launch any application URL in your preferred browser (Chromium, Chrome, Firefox, WebKit) and capture elements seamlessly.
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

      {/* URL Navigation Warning */}
      {isBrowserConnected && isErrorPage && (
        <div className="capture-banner-msg error" style={{ background: "#fef2f2", borderColor: "#fecaca", color: "#991b1b" }}>
          <CircleAlert size={18} color="#dc2626" />
          <div style={{ flex: 1 }}>
            <strong>The target URL could not be reached by the browser.</strong>
            <div style={{ fontSize: "0.85rem", marginTop: 4 }}>
              If your application requires an active session or VPN, copy the exact live URL from your open browser tab (including the <code>?session=...</code> token) and paste it into the URL field below, then click <strong>Navigate</strong>.
            </div>
          </div>
        </div>
      )}

      {/* Main Action & URL Controller Section */}
      <section className="card capture-launch-card">
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          {/* Top Row: App Name & Browser Selector */}
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 12 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <Globe size={22} color="#06b6d4" />
              <div>
                <span style={{ fontWeight: 700, fontSize: "1.05rem", color: "var(--text-color, #0f172a)" }}>
                  {activeProject.name}
                </span>
                <span style={{ fontSize: "0.8rem", color: "var(--vq-muted, #64748b)", marginLeft: 8 }}>
                  ({activeProject.project_type})
                </span>
              </div>
            </div>

            {/* Browser Selection */}
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <Laptop size={15} color="var(--vq-muted)" />
              <label style={{ fontSize: "0.85rem", fontWeight: 600, color: "var(--vq-muted)" }}>
                Browser Engine:
              </label>
              <select
                className="select"
                style={{ padding: "6px 12px", fontSize: "0.88rem", minWidth: 150 }}
                value={selectedBrowser}
                onChange={(e) => setSelectedBrowser(e.target.value)}
                disabled={browserLoading}
              >
                <option value="chromium">Chromium</option>
                <option value="chrome">Google Chrome</option>
                <option value="chrome-cdp">Connect to Open Chrome (Port 9222)</option>
                <option value="firefox">Firefox</option>
                <option value="webkit">WebKit (Safari)</option>
              </select>
            </div>
          </div>

          {/* Interactive URL Bar */}
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <div style={{ position: "relative", flex: 1, minWidth: 280 }}>
              <Globe size={16} style={{ position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)", color: "var(--vq-muted)" }} />
              <input
                type="text"
                className="input"
                style={{ width: "100%", paddingLeft: 36, paddingRight: 12, fontFamily: "monospace", fontSize: "0.9rem" }}
                value={targetUrl}
                onChange={(e) => setTargetUrl(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    if (isBrowserConnected) void handleNavigateBrowser();
                    else void handleLaunchBrowser();
                  }
                }}
                placeholder="https://your-application-url.com"
              />
            </div>

            {isBrowserConnected ? (
              <button
                className="button button-secondary"
                onClick={() => void handleNavigateBrowser()}
                disabled={browserLoading}
                title="Navigate the running browser to this URL"
              >
                <Navigation size={15} />
                Navigate
              </button>
            ) : null}

            <button
              className="button button-secondary"
              onClick={() => void handleSaveAsDefaultUrl()}
              disabled={isSavingUrl || !targetUrl.trim() || targetUrl.trim() === activeProject.base_url}
              title="Save this URL as the default application URL in database"
            >
              <Bookmark size={14} />
              {isSavingUrl ? "Saving..." : "Save Default"}
            </button>
          </div>

          {/* Live Action Bar */}
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", paddingTop: 12, borderTop: "1px solid var(--border-color, #e2e8f0)", flexWrap: "wrap", gap: 12 }}>
            <div>
              {isBrowserConnected ? (
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  <span className="status-dot active-green" />
                  <span style={{ fontSize: "0.88rem", fontWeight: 600, color: "var(--text-color, #0f172a)" }}>
                    {selectedBrowser.toUpperCase()} Active:
                  </span>
                  <span
                    style={{
                      fontSize: "0.82rem",
                      fontFamily: "monospace",
                      background: "#f1f5f9",
                      padding: "2px 8px",
                      borderRadius: 4,
                      maxWidth: 360,
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                      display: "inline-block",
                    }}
                    title={browserStatus?.current_url}
                  >
                    {browserStatus?.page_title ? `${browserStatus.page_title} - ` : ""}
                    {browserStatus?.current_url || "about:blank"}
                  </span>
                </div>
              ) : (
                <span style={{ fontSize: "0.85rem", color: "var(--vq-muted, #64748b)" }}>
                  Browser is not running. Click below to launch.
                </span>
              )}
            </div>

            <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
              {!isBrowserConnected ? (
                <button
                  className="button button-primary capture-main-btn"
                  onClick={() => void handleLaunchBrowser()}
                  disabled={browserLoading}
                >
                  {browserLoading ? (
                    <>
                      <LoaderCircle size={18} className="spinner spin" />
                      Opening in {selectedBrowser}...
                    </>
                  ) : (
                    <>
                      <Play size={18} />
                      Open in {selectedBrowser.toUpperCase()}
                    </>
                  )}
                </button>
              ) : (
                <>
                  {/* DIRECT DASHBOARD CAPTURE BUTTON */}
                  <button
                    className="button button-primary"
                    style={{ background: "#06b6d4", borderColor: "#06b6d4", fontWeight: 700 }}
                    onClick={() => void handleDirectCapture()}
                    disabled={isCapturing || browserLoading}
                    title="Capture all interactive elements from the current browser page directly"
                  >
                    {isCapturing ? (
                      <>
                        <LoaderCircle size={16} className="spinner spin" />
                        Scanning Page...
                      </>
                    ) : (
                      <>
                        <Camera size={16} />
                        Capture Active Page
                      </>
                    )}
                  </button>

                  {/* INTERACTIVE PICKER BUTTON */}
                  <button
                    className="button button-secondary"
                    style={{ border: "1px solid rgba(6, 182, 212, 0.5)", color: "#0891b2", fontWeight: 700 }}
                    onClick={() => void handleStartPicker()}
                    disabled={browserLoading}
                    title="Click any element in the open browser to capture and name it"
                  >
                    <Crosshair size={15} />
                    Capture Element
                  </button>

                  <button
                    className="button button-secondary"
                    onClick={() => void handleLaunchBrowser()}
                    disabled={browserLoading}
                    title="Bring open browser window to the front"
                  >
                    <ExternalLink size={15} />
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
                </>
              )}
            </div>
          </div>
        </div>
      </section>

      {/* Saved / Captured Elements Catalog */}
      <section className="capture-catalog-section">
        <div className="catalog-section-header">
          <div className="catalog-header-left">
            <h2>Saved &amp; Captured Elements</h2>
            <p>
              Review and manage captured elements, or add them directly to automated workflow steps.
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
