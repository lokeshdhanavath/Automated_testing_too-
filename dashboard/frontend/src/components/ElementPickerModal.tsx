import React, { useState, useEffect, useRef } from "react";
import {
  X,
  Search,
  MousePointer,
  Layers,
  Check,
  RefreshCw,
  LogIn,
  Compass,
  FormInput,
  MousePointerClick,
  ListFilter,
  AlertCircle,
  LoaderCircle,
  Sparkles,
  Power,
  RotateCcw,
} from "lucide-react";
import {
  inspectApplicationPage,
  interactWithInspector,
  replayInspectorSteps,
  closeInspectorSession,
  createElement,
} from "../services/api";
import type { InspectElement, InspectResponse, ScenarioStep } from "../services/api";

interface ElementPickerModalProps {
  projectId: string;
  projectName: string;
  actionType: string;
  initialPath?: string;
  precedingSteps?: ScenarioStep[];
  onSelectElement: (element: InspectElement) => void;
  onClose: () => void;
}

export const ElementPickerModal: React.FC<ElementPickerModalProps> = ({
  projectId,
  projectName,
  actionType,
  initialPath,
  precedingSteps,
  onSelectElement,
  onClose,
}) => {
  const [loading, setLoading] = useState(true);
  const [interactLoading, setInteractLoading] = useState(false);
  const [replayingSteps, setReplayingSteps] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [inspectData, setInspectData] = useState<InspectResponse | null>(null);

  // Filter & Search states
  const [categoryFilter, setCategoryFilter] = useState<string>("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [activeTab, setActiveTab] = useState<"visual" | "list">("visual");

  // Selection states
  const [selectedElement, setSelectedElement] = useState<InspectElement | null>(null);
  const [registryName, setRegistryName] = useState("");
  const [showRegistryForm, setShowRegistryForm] = useState(false);
  const [savingElement, setSavingElement] = useState(false);
  const [registryToast, setRegistryToast] = useState("");
  const [hoveredElement, setHoveredElement] = useState<InspectElement | null>(null);

  // Image scaling for visual overlay
  const imageRef = useRef<HTMLImageElement | null>(null);
  const [imageScale, setImageScale] = useState({ scaleX: 1, scaleY: 1 });

  // Auto-set initial category filter based on action type
  useEffect(() => {
    if (actionType === "navigate") {
      setCategoryFilter("link");
    } else if (actionType === "fill_input") {
      setCategoryFilter("input");
    } else if (actionType === "click_element") {
      setCategoryFilter("button");
    } else if (actionType === "select_option") {
      setCategoryFilter("select");
    } else {
      setCategoryFilter("all");
    }
  }, [actionType]);

  // Load page inspection preserving the live persistent browser session
  useEffect(() => {
    const shouldAutoLogin = actionType !== "login";
    void loadInspection(shouldAutoLogin, false);
    // DO NOT kill session on modal unmount so browser session persists across actions
  }, [projectId]);

  async function loadInspection(withLogin: boolean = false, forceRefresh: boolean = false) {
    setLoading(true);
    setError(null);
    try {
      const data = await inspectApplicationPage(projectId, {
        path: initialPath,
        with_login: withLogin,
        expand_navigation: true,
        force_refresh: forceRefresh,
        preserve_state: !forceRefresh,
      });
      setInspectData(data);
      // Select first matching element if none selected
      if (!selectedElement && data.elements.length > 0) {
        const preferred = data.elements.find((el) => {
          if (data.has_open_dialog && el.in_dialog) return true;
          if (actionType === "navigate") return el.category === "link";
          if (actionType === "fill_input") return el.category === "input";
          if (actionType === "click_element") return el.category === "button";
          if (actionType === "select_option") return el.category === "select";
          return true;
        });
        if (preferred) setSelectedElement(preferred);
      }
    } catch (err: any) {
      setError(err?.message || "Failed to inspect application page.");
    } finally {
      setLoading(false);
    }
  }

  async function saveSelectedElement() {
    if (!selectedElement || !inspectData) return;
    const name = registryName.trim();
    if (!/^[A-Za-z][A-Za-z0-9_]{0,119}$/.test(name)) {
      setError("Name must start with a letter and contain only letters, digits, or underscores.");
      return;
    }
    setSavingElement(true);
    setError(null);
    try {
      await createElement(projectId, {
        name,
        page_url: inspectData.page_url,
        element_kind: selectedElement.category,
        selector_type: selectedElement.locator_strategy === "smart" ? "css" : selectedElement.locator_strategy,
        selector_value: selectedElement.locator_value,
        description: selectedElement.friendly_name,
      });
      setRegistryToast("Saved '" + name + "' to registry.");
      window.setTimeout(onClose, 900);
    } catch (err: any) {
      setError(err?.message || "Failed to save element to registry.");
    } finally {
      setSavingElement(false);
    }
  }

  // Update scale factor whenever image loads or window resizes
  const handleImageLoad = () => {
    if (!imageRef.current || !inspectData) return;
    const rect = imageRef.current.getBoundingClientRect();
    const natWidth = inspectData.viewport.width || 1440;
    const natHeight = inspectData.viewport.height || 900;
    setImageScale({
      scaleX: rect.width / natWidth,
      scaleY: rect.height / natHeight,
    });
  };

  useEffect(() => {
    window.addEventListener("resize", handleImageLoad);
    return () => window.removeEventListener("resize", handleImageLoad);
  }, [inspectData]);

  // Execute interactive walkthrough step inside inspector
  async function handleInteractiveAction(action: "login" | "expand_nav" | "click" | "navigate" | "fill", target?: string) {
    setInteractLoading(true);
    setError(null);
    try {
      const updated = await interactWithInspector(projectId, { action, target });
      setInspectData(updated);
      setSelectedElement(null);
    } catch (err: any) {
      setError(err?.message || "Action in inspector failed.");
    } finally {
      setInteractLoading(false);
    }
  }

  // Replay preceding workflow steps to reach target modal/dialog state
  async function handleReplayPrecedingSteps() {
    if (!precedingSteps || precedingSteps.length === 0) return;
    setReplayingSteps(true);
    setError(null);
    try {
      const updated = await replayInspectorSteps(projectId, precedingSteps);
      setInspectData(updated);
      setSelectedElement(null);
    } catch (err: any) {
      setError(err?.message || "Failed to prepare page using preceding steps.");
    } finally {
      setReplayingSteps(false);
    }
  }

  // Explicit disconnect session
  async function handleDisconnectSession() {
    try {
      await closeInspectorSession(projectId);
    } catch {}
    onClose();
  }

  const hasDialogElements = (inspectData?.elements || []).some((e) => e.in_dialog);
  const dialogElementsCount = (inspectData?.elements || []).filter((e) => e.in_dialog).length;

  // Filter elements
  const filteredElements = (inspectData?.elements || []).filter((el) => {
    const matchesCategory =
      categoryFilter === "all" ||
      (categoryFilter === "dialog" && el.in_dialog) ||
      el.category === categoryFilter ||
      (categoryFilter === "button" && (el.category === "button" || el.role === "button")) ||
      (categoryFilter === "link" && (el.category === "link" || el.role === "link" || el.role === "treeitem" || el.role === "menuitem"));

    const q = searchQuery.toLowerCase().trim();
    const matchesQuery =
      !q ||
      el.friendly_name.toLowerCase().includes(q) ||
      el.text.toLowerCase().includes(q) ||
      el.label.toLowerCase().includes(q) ||
      el.placeholder.toLowerCase().includes(q) ||
      el.locator_value.toLowerCase().includes(q);

    return matchesCategory && matchesQuery;
  });

  const getCategoryIcon = (category: string) => {
    switch (category) {
      case "button":
        return <MousePointerClick size={14} />;
      case "link":
        return <Compass size={14} />;
      case "input":
        return <FormInput size={14} />;
      case "select":
        return <ListFilter size={14} />;
      default:
        return <Layers size={14} />;
    }
  };

  return (
    <div className="sb-modal-backdrop" style={{ zIndex: 9999 }}>
      <div
        className="sb-modal-card"
        style={{
          maxWidth: 1140,
          width: "95vw",
          height: "92vh",
          display: "flex",
          flexDirection: "column",
          padding: 0,
          overflow: "hidden",
        }}
      >
        {/* =========================================================================
            TOP HEADER
        ========================================================================= */}
        <div
          style={{
            padding: "12px 20px",
            borderBottom: "1px solid var(--v-border)",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            background: "var(--v-surface)",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <div
              style={{
                width: 36,
                height: 36,
                borderRadius: 8,
                background: "var(--v-accent-light)",
                color: "var(--v-accent)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
              }}
            >
              <MousePointer size={18} />
            </div>
            <div>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <h3 style={{ margin: 0, fontSize: "0.95rem", fontWeight: 700, color: "var(--v-text)" }}>
                  Select Element from {projectName}
                </h3>
                <span
                  style={{
                    fontSize: "0.7rem",
                    padding: "2px 8px",
                    borderRadius: 4,
                    background: "rgba(16, 185, 129, 0.12)",
                    color: "var(--v-emerald)",
                    fontWeight: 700,
                    display: "flex",
                    alignItems: "center",
                    gap: 4,
                  }}
                >
                  <span style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--v-emerald)" }} />
                  Persistent Browser Session
                </span>
              </div>
              <p style={{ margin: "2px 0 0 0", fontSize: "0.75rem", color: "var(--v-text-secondary)" }}>
                Inspect live application state, open modals/dialogs, or pick elements across actions without reconnecting.
              </p>
            </div>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            {/* Replay Preceding Steps Button */}
            {precedingSteps && precedingSteps.length > 0 && (
              <button
                type="button"
                className="button button-small"
                style={{
                  background: "linear-gradient(135deg, #4f46e5 0%, #7c3aed 100%)",
                  color: "#fff",
                  border: "none",
                  fontSize: "0.74rem",
                  padding: "4px 10px",
                  display: "flex",
                  alignItems: "center",
                  gap: 5,
                  fontWeight: 600,
                  boxShadow: "0 2px 6px rgba(79, 70, 229, 0.25)",
                }}
                onClick={() => void handleReplayPrecedingSteps()}
                disabled={loading || interactLoading || replayingSteps}
                title={`Run ${precedingSteps.length} earlier step(s) to automatically open dialogs or advance page`}
              >
                <Sparkles size={13} className={replayingSteps ? "spin" : ""} />
                {replayingSteps
                  ? `Preparing Page (${precedingSteps.length} steps)...`
                  : `⚡ Prepare Page (${precedingSteps.length} preceding step${precedingSteps.length > 1 ? "s" : ""})`}
              </button>
            )}

            {/* Refresh DOM Button */}
            <button
              type="button"
              className="button button-secondary button-small"
              onClick={() => void loadInspection(false, false)}
              disabled={loading || interactLoading || replayingSteps}
              title="Re-scan current page without reloading"
            >
              <RefreshCw size={13} className={loading ? "spin" : ""} /> Refresh
            </button>

            {/* Restart Browser Session Button */}
            <button
              type="button"
              className="button button-secondary button-small"
              onClick={() => void loadInspection(true, true)}
              disabled={loading || interactLoading || replayingSteps}
              title="Restart browser session from scratch"
            >
              <RotateCcw size={13} /> Reset
            </button>

            {/* Disconnect Session Button */}
            <button
              type="button"
              className="button button-secondary button-small"
              onClick={() => void handleDisconnectSession()}
              style={{ color: "var(--v-rose)", borderColor: "rgba(244, 63, 94, 0.3)" }}
              title="Disconnect Playwright browser session"
            >
              <Power size={13} /> Disconnect
            </button>

            <button type="button" onClick={onClose} className="sb-icon-btn" aria-label="Close">
              <X size={16} />
            </button>
          </div>
        </div>

        {/* =========================================================================
            PAGE CONTEXT & TOOLBAR
        ========================================================================= */}
        <div
          style={{
            padding: "7px 20px",
            background: "var(--v-surface-2)",
            borderBottom: "1px solid var(--v-border)",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            fontSize: "0.75rem",
            color: "var(--v-text-secondary)",
            gap: 16,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 8, overflow: "hidden" }}>
            <span style={{ fontWeight: 600, color: "var(--v-text-muted)" }}>LIVE PAGE:</span>
            <span
              style={{
                fontFamily: "monospace",
                color: "var(--v-text)",
                background: "var(--v-surface)",
                padding: "2px 8px",
                borderRadius: 4,
                border: "1px solid var(--v-border)",
                whiteSpace: "nowrap",
                overflow: "hidden",
                textOverflow: "ellipsis",
                maxWidth: 420,
              }}
              title={inspectData?.page_url}
            >
              {inspectData?.page_url || "Connecting..."}
            </span>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: 6, flexShrink: 0 }}>
            {/* Quick Page Jump buttons */}
            <div style={{ display: "flex", alignItems: "center", gap: 4, background: "var(--v-surface)", padding: "2px 6px", borderRadius: 6, border: "1px solid var(--v-border)" }}>
              <span style={{ fontSize: "0.68rem", fontWeight: 700, color: "var(--v-text-muted)", padding: "0 4px" }}>JUMP TO:</span>
              <button
                type="button"
                className="button button-small button-secondary"
                style={{
                  fontSize: "0.72rem",
                  padding: "3px 8px",
                  height: "auto",
                  background: inspectData?.page_url.includes("home") ? "var(--v-accent-light)" : undefined,
                  borderColor: inspectData?.page_url.includes("home") ? "var(--v-accent)" : undefined,
                  color: inspectData?.page_url.includes("home") ? "var(--v-accent)" : undefined,
                  fontWeight: inspectData?.page_url.includes("home") ? 700 : 500,
                }}
                onClick={() => void handleInteractiveAction("click", "Home")}
                disabled={interactLoading || loading || replayingSteps}
                title="Navigate to Home"
              >
                🏠 Home
              </button>
              <button
                type="button"
                className="button button-small button-secondary"
                style={{
                  fontSize: "0.72rem",
                  padding: "3px 8px",
                  height: "auto",
                  background: inspectData?.page_url.includes("timesheet") ? "var(--v-accent-light)" : undefined,
                  borderColor: inspectData?.page_url.includes("timesheet") ? "var(--v-accent)" : undefined,
                  color: inspectData?.page_url.includes("timesheet") ? "var(--v-accent)" : undefined,
                  fontWeight: inspectData?.page_url.includes("timesheet") ? 700 : 500,
                }}
                onClick={() => void handleInteractiveAction("click", "My Timesheet")}
                disabled={interactLoading || loading || replayingSteps}
                title="Navigate inside My Timesheet page"
              >
                📅 My Timesheet
              </button>
              <button
                type="button"
                className="button button-small button-secondary"
                style={{
                  fontSize: "0.72rem",
                  padding: "3px 8px",
                  height: "auto",
                  background: inspectData?.page_url.includes("whereabouts") ? "var(--v-accent-light)" : undefined,
                  borderColor: inspectData?.page_url.includes("whereabouts") ? "var(--v-accent)" : undefined,
                  color: inspectData?.page_url.includes("whereabouts") ? "var(--v-accent)" : undefined,
                  fontWeight: inspectData?.page_url.includes("whereabouts") ? 700 : 500,
                }}
                onClick={() => void handleInteractiveAction("click", "Whereabouts")}
                disabled={interactLoading || loading || replayingSteps}
                title="Navigate to Whereabouts"
              >
                📍 Whereabouts
              </button>
            </div>

            {/* Quick Login button if on login page */}
            {inspectData?.page_url.includes("login") && !inspectData?.authenticated && (
              <button
                type="button"
                onClick={() => void handleInteractiveAction("login")}
                disabled={interactLoading || loading || replayingSteps}
                className="button button-small"
                style={{
                  background: "var(--v-accent)",
                  color: "#fff",
                  fontSize: "0.74rem",
                  padding: "4px 10px",
                  display: "flex",
                  alignItems: "center",
                  gap: 5,
                }}
              >
                <LogIn size={13} /> Log In with Vault
              </button>
            )}

            {/* Expand Navigation Button */}
            <button
              type="button"
              onClick={() => void handleInteractiveAction("expand_nav")}
              disabled={interactLoading || loading || replayingSteps}
              className="button button-secondary button-small"
              style={{ fontSize: "0.74rem", padding: "4px 10px", display: "flex", alignItems: "center", gap: 5 }}
            >
              <Compass size={13} /> Expand Nav
            </button>
          </div>
        </div>

        {/* Dynamic Modal / Dialog Active Banner */}
        {inspectData?.has_open_dialog && (
          <div
            style={{
              padding: "7px 20px",
              background: "rgba(99, 102, 241, 0.08)",
              borderBottom: "1px solid rgba(99, 102, 241, 0.22)",
              display: "flex",
              alignItems: "center",
              justifyContent: "space-between",
              fontSize: "0.78rem",
              color: "var(--v-accent)",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <Sparkles size={14} style={{ color: "var(--v-accent)" }} />
              <span>
                <strong>Dynamic Dialog Active:</strong> &ldquo;{inspectData.active_dialog_title || "Modal Dialog"}&rdquo;
              </span>
              <span style={{ fontSize: "0.72rem", color: "var(--v-text-secondary)" }}>
                ({dialogElementsCount} field{dialogElementsCount === 1 ? "" : "s"} ready for selection)
              </span>
            </div>
            <button
              type="button"
              className="button button-small"
              style={{
                padding: "3px 10px",
                fontSize: "0.72rem",
                background: categoryFilter === "dialog" ? "var(--v-accent)" : "var(--v-surface)",
                color: categoryFilter === "dialog" ? "#fff" : "var(--v-accent)",
                borderColor: "var(--v-accent)",
                fontWeight: 600,
              }}
              onClick={() => setCategoryFilter(categoryFilter === "dialog" ? "all" : "dialog")}
            >
              {categoryFilter === "dialog" ? "Showing Dialog Only ✓" : "Filter to Dialog Fields"}
            </button>
          </div>
        )}

        {/* =========================================================================
            SEARCH & CATEGORY TABS
        ========================================================================= */}
        <div
          style={{
            padding: "8px 20px",
            borderBottom: "1px solid var(--v-border)",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 12,
            background: "var(--v-surface)",
          }}
        >
          {/* Categories */}
          <div style={{ display: "flex", gap: 6 }}>
            {[
              { id: "all", label: `All (${inspectData?.categories_count?.total || 0})` },
              ...(hasDialogElements
                ? [{ id: "dialog", label: `✨ Dialog Fields (${dialogElementsCount})` }]
                : []),
              { id: "button", label: `Buttons (${inspectData?.categories_count?.buttons || 0})` },
              { id: "link", label: `Navigation (${inspectData?.categories_count?.links || 0})` },
              { id: "input", label: `Inputs (${inspectData?.categories_count?.inputs || 0})` },
              { id: "select", label: `Dropdowns (${inspectData?.categories_count?.selects || 0})` },
            ].map((cat) => (
              <button
                key={cat.id}
                type="button"
                onClick={() => setCategoryFilter(cat.id)}
                style={{
                  padding: "4px 10px",
                  borderRadius: 6,
                  fontSize: "0.74rem",
                  fontWeight: categoryFilter === cat.id ? 700 : 500,
                  border: "none",
                  cursor: "pointer",
                  background: categoryFilter === cat.id ? "var(--v-accent)" : "transparent",
                  color: categoryFilter === cat.id ? "#fff" : "var(--v-text-secondary)",
                  transition: "all 0.15s ease",
                }}
              >
                {cat.label}
              </button>
            ))}
          </div>

          {/* Search box & View Mode toggle */}
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <div style={{ position: "relative" }}>
              <Search
                size={14}
                style={{ position: "absolute", left: 10, top: "50%", transform: "translateY(-50%)", color: "var(--v-text-muted)" }}
              />
              <input
                type="text"
                placeholder="Filter elements..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                style={{
                  padding: "5px 12px 5px 30px",
                  borderRadius: 6,
                  border: "1px solid var(--v-border)",
                  fontSize: "0.75rem",
                  width: 190,
                  background: "var(--v-surface-2)",
                  color: "var(--v-text)",
                  outline: "none",
                }}
              />
            </div>

            <div style={{ display: "flex", background: "var(--v-surface-2)", borderRadius: 6, padding: 2, border: "1px solid var(--v-border)" }}>
              <button
                type="button"
                onClick={() => setActiveTab("visual")}
                style={{
                  padding: "3px 8px",
                  borderRadius: 4,
                  fontSize: "0.72rem",
                  fontWeight: activeTab === "visual" ? 700 : 500,
                  border: "none",
                  cursor: "pointer",
                  background: activeTab === "visual" ? "var(--v-surface)" : "transparent",
                  color: activeTab === "visual" ? "var(--v-accent)" : "var(--v-text-secondary)",
                  boxShadow: activeTab === "visual" ? "0 1px 3px rgba(0,0,0,0.06)" : "none",
                }}
              >
                Visual View
              </button>
              <button
                type="button"
                onClick={() => setActiveTab("list")}
                style={{
                  padding: "3px 8px",
                  borderRadius: 4,
                  fontSize: "0.72rem",
                  fontWeight: activeTab === "list" ? 700 : 500,
                  border: "none",
                  cursor: "pointer",
                  background: activeTab === "list" ? "var(--v-surface)" : "transparent",
                  color: activeTab === "list" ? "var(--v-accent)" : "var(--v-text-secondary)",
                  boxShadow: activeTab === "list" ? "0 1px 3px rgba(0,0,0,0.06)" : "none",
                }}
              >
                List View
              </button>
            </div>
          </div>
        </div>

        {/* =========================================================================
            MAIN CONTENT AREA
        ========================================================================= */}
        <div style={{ flex: 1, overflow: "hidden", display: "flex", position: "relative" }}>
          {loading ? (
            <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 12 }}>
              <LoaderCircle size={32} className="spin" style={{ color: "var(--v-accent)" }} />
              <div style={{ fontSize: "0.85rem", fontWeight: 600, color: "var(--v-text)" }}>
                Connecting to Playwright browser & scanning {projectName}...
              </div>
              <p style={{ fontSize: "0.75rem", color: "var(--v-text-secondary)", margin: 0 }}>
                Extracting rendered interactive components, accessible roles, and bounding boxes.
              </p>
            </div>
          ) : error ? (
            <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 10, padding: 30 }}>
              <AlertCircle size={32} style={{ color: "var(--v-rose)" }} />
              <div style={{ fontSize: "0.9rem", fontWeight: 700, color: "var(--v-rose)" }}>Inspection Error</div>
              <p style={{ fontSize: "0.8rem", color: "var(--v-text-secondary)", textAlign: "center", maxWidth: 450, margin: 0 }}>
                {error}
              </p>
              <button type="button" className="button button-primary button-small" onClick={() => void loadInspection(false, true)}>
                Retry Inspection
              </button>
            </div>
          ) : (
            <div style={{ flex: 1, display: "flex", height: "100%", overflow: "hidden" }}>
              {/* Visual Interactive View */}
              {activeTab === "visual" ? (
                <div style={{ flex: 1, overflow: "auto", position: "relative", background: "#f1f5f9", display: "flex", justifyContent: "center", padding: 12 }}>
                  <div style={{ position: "relative", display: "inline-block", boxShadow: "0 4px 20px rgba(0,0,0,0.12)", borderRadius: 6, overflow: "hidden" }}>
                    <img
                      ref={imageRef}
                      src={inspectData?.screenshot}
                      alt="Rendered Application Page"
                      onLoad={handleImageLoad}
                      style={{ display: "block", maxWidth: "100%", height: "auto" }}
                    />

                    {/* Interactive Bounding Boxes Overlay */}
                    {filteredElements.map((el) => {
                      const isHovered = hoveredElement?.id === el.id;
                      const isSelected = selectedElement?.id === el.id;

                      const left = el.rect.x * imageScale.scaleX;
                      const top = el.rect.y * imageScale.scaleY;
                      const width = el.rect.width * imageScale.scaleX;
                      const height = el.rect.height * imageScale.scaleY;

                      return (
                        <div
                          key={el.id}
                          onClick={() => setSelectedElement(el)}
                          onMouseEnter={() => setHoveredElement(el)}
                          onMouseLeave={() => setHoveredElement(null)}
                          style={{
                            position: "absolute",
                            left,
                            top,
                            width,
                            height,
                            cursor: "pointer",
                            boxSizing: "border-box",
                            transition: "all 0.12s ease",
                            border: isSelected
                              ? "2px solid #10b981"
                              : isHovered
                              ? "2px solid #6366f1"
                              : el.in_dialog
                              ? "1px dashed #ec4899"
                              : "1px dashed rgba(99, 102, 241, 0.4)",
                            background: isSelected
                              ? "rgba(16, 185, 129, 0.22)"
                              : isHovered
                              ? "rgba(99, 102, 241, 0.2)"
                              : el.in_dialog
                              ? "rgba(236, 72, 153, 0.08)"
                              : "rgba(99, 102, 241, 0.04)",
                            borderRadius: 3,
                            zIndex: isSelected ? 30 : isHovered ? 25 : el.in_dialog ? 15 : 10,
                          }}
                          title={el.friendly_name}
                        >
                          {/* Floating badge label when hovered or selected */}
                          {(isHovered || isSelected) && (
                            <div
                              style={{
                                position: "absolute",
                                bottom: "100%",
                                left: 0,
                                marginBottom: 4,
                                background: isSelected ? "#059669" : el.in_dialog ? "#db2777" : "#4f46e5",
                                color: "#fff",
                                padding: "2px 7px",
                                borderRadius: 4,
                                fontSize: "0.68rem",
                                fontWeight: 700,
                                whiteSpace: "nowrap",
                                boxShadow: "0 2px 8px rgba(0,0,0,0.18)",
                                pointerEvents: "none",
                                display: "flex",
                                alignItems: "center",
                                gap: 4,
                              }}
                            >
                              {isSelected && <Check size={10} />}
                              {el.in_dialog && <span>[Dialog]</span>}
                              {el.friendly_name}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              ) : (
                /* List View */
                <div style={{ flex: 1, overflowY: "auto", padding: 16 }}>
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: 10 }}>
                    {filteredElements.map((el) => {
                      const isSelected = selectedElement?.id === el.id;
                      return (
                        <div
                          key={el.id}
                          onClick={() => setSelectedElement(el)}
                          style={{
                            padding: 12,
                            borderRadius: 8,
                            border: isSelected
                              ? "2px solid var(--v-emerald)"
                              : el.in_dialog
                              ? "1px solid rgba(236, 72, 153, 0.4)"
                              : "1px solid var(--v-border)",
                            background: isSelected
                              ? "rgba(16, 185, 129, 0.06)"
                              : el.in_dialog
                              ? "rgba(236, 72, 153, 0.03)"
                              : "var(--v-surface)",
                            cursor: "pointer",
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "space-between",
                            gap: 10,
                            transition: "all 0.15s ease",
                          }}
                        >
                          <div style={{ display: "flex", alignItems: "center", gap: 10, overflow: "hidden" }}>
                            <div
                              style={{
                                width: 28,
                                height: 28,
                                borderRadius: 6,
                                background: el.in_dialog ? "rgba(236, 72, 153, 0.1)" : "var(--v-surface-2)",
                                color: el.in_dialog ? "#db2777" : "var(--v-accent)",
                                display: "flex",
                                alignItems: "center",
                                justifyContent: "center",
                                flexShrink: 0,
                              }}
                            >
                              {getCategoryIcon(el.category)}
                            </div>
                            <div style={{ overflow: "hidden" }}>
                              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                                <span style={{ fontSize: "0.82rem", fontWeight: 700, color: "var(--v-text)", textOverflow: "ellipsis", overflow: "hidden", whiteSpace: "nowrap" }}>
                                  {el.friendly_name}
                                </span>
                                {el.in_dialog && (
                                  <span style={{ fontSize: "0.62rem", padding: "1px 5px", borderRadius: 3, background: "rgba(236, 72, 153, 0.15)", color: "#db2777", fontWeight: 700 }}>
                                    Dialog
                                  </span>
                                )}
                              </div>
                              <div style={{ fontSize: "0.72rem", color: "var(--v-text-muted)", fontFamily: "monospace" }}>
                                {el.locator_strategy}: &quot;{el.locator_value}&quot;
                              </div>
                            </div>
                          </div>
                          {isSelected && <Check size={16} style={{ color: "var(--v-emerald)", flexShrink: 0 }} />}
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Sidebar with Selected Element Details & Confirmation */}
              <div
                style={{
                  width: 330,
                  borderLeft: "1px solid var(--v-border)",
                  background: "var(--v-surface)",
                  display: "flex",
                  flexDirection: "column",
                  justifyContent: "space-between",
                  padding: 16,
                  overflowY: "auto",
                }}
              >
                <div>
                  <h4 style={{ margin: "0 0 12px 0", fontSize: "0.8rem", textTransform: "uppercase", color: "var(--v-text-muted)", fontWeight: 700 }}>
                    Selected Element
                  </h4>

                  {selectedElement ? (
                    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                      <div
                        style={{
                          background: "var(--v-surface-2)",
                          borderRadius: 8,
                          padding: 12,
                          border: "1px solid var(--v-border)",
                        }}
                      >
                        <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
                          <span
                            style={{
                              padding: "2px 6px",
                              borderRadius: 4,
                              background: selectedElement.in_dialog ? "rgba(236, 72, 153, 0.15)" : "rgba(99, 102, 241, 0.12)",
                              color: selectedElement.in_dialog ? "#db2777" : "var(--v-accent)",
                              fontSize: "0.68rem",
                              fontWeight: 700,
                              textTransform: "uppercase",
                            }}
                          >
                            {selectedElement.category}
                          </span>
                          {selectedElement.in_dialog && (
                            <span style={{ fontSize: "0.68rem", color: "#db2777", fontWeight: 600 }}>
                              Inside Dialog
                            </span>
                          )}
                          <span style={{ fontSize: "0.7rem", color: "var(--v-text-muted)", marginLeft: "auto" }}>
                            &lt;{selectedElement.tag || selectedElement.tag_name || "element"}&gt;
                          </span>
                        </div>
                        <div style={{ fontSize: "0.9rem", fontWeight: 700, color: "var(--v-text)", wordBreak: "break-word" }}>
                          {selectedElement.friendly_name}
                        </div>
                      </div>

                      {/* Element Properties */}
                      <div style={{ display: "flex", flexDirection: "column", gap: 8, fontSize: "0.75rem" }}>
                        <div>
                          <span style={{ color: "var(--v-text-muted)", display: "block" }}>RECOMMENDED LOCATOR</span>
                          <code
                            style={{
                              display: "block",
                              marginTop: 2,
                              background: "var(--v-surface-2)",
                              padding: "4px 8px",
                              borderRadius: 4,
                              fontFamily: "monospace",
                              color: "var(--v-text)",
                              fontSize: "0.73rem",
                              wordBreak: "break-all",
                            }}
                          >
                            {selectedElement.locator_strategy}: &quot;{selectedElement.locator_value}&quot;
                          </code>
                        </div>

                        {selectedElement.role && (
                          <div>
                            <span style={{ color: "var(--v-text-muted)" }}>Role: </span>
                            <span style={{ fontWeight: 600, color: "var(--v-text)" }}>{selectedElement.role}</span>
                          </div>
                        )}

                        {selectedElement.dialog_title && (
                          <div>
                            <span style={{ color: "var(--v-text-muted)" }}>Dialog Context: </span>
                            <span style={{ fontWeight: 600, color: "#db2777" }}>&ldquo;{selectedElement.dialog_title}&rdquo;</span>
                          </div>
                        )}

                        {selectedElement.label && (
                          <div>
                            <span style={{ color: "var(--v-text-muted)" }}>Associated Label: </span>
                            <span style={{ fontWeight: 600, color: "var(--v-text)" }}>&ldquo;{selectedElement.label}&rdquo;</span>
                          </div>
                        )}

                        {selectedElement.placeholder && (
                          <div>
                            <span style={{ color: "var(--v-text-muted)" }}>Placeholder: </span>
                            <span style={{ fontWeight: 600, color: "var(--v-text)" }}>&ldquo;{selectedElement.placeholder}&rdquo;</span>
                          </div>
                        )}

                        {selectedElement.options && selectedElement.options.length > 0 && (
                          <div>
                            <span style={{ color: "var(--v-text-muted)", display: "block", marginBottom: 4 }}>
                              AVAILABLE OPTIONS ({selectedElement.options.length})
                            </span>
                            <div style={{ maxHeight: 90, overflowY: "auto", border: "1px solid var(--v-border)", borderRadius: 4, padding: 4 }}>
                              {selectedElement.options.map((opt, i) => (
                                <div key={i} style={{ padding: "2px 4px", fontSize: "0.7rem", color: "var(--v-text)" }}>
                                  • {opt.label} <span style={{ color: "var(--v-text-muted)" }}>({opt.value})</span>
                                </div>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    </div>
                  ) : (
                    <div style={{ padding: "24px 12px", textAlign: "center", color: "var(--v-text-muted)", fontSize: "0.78rem" }}>
                      Click on any element in the page preview or choose from the list to inspect its properties.
                    </div>
                  )}
                </div>

                {/* Bottom confirmation & interactive navigation buttons */}
                <div style={{ borderTop: "1px solid var(--v-border)", paddingTop: 14, marginTop: 14, display: "flex", flexDirection: "column", gap: 8 }}>
                  {selectedElement && (selectedElement.category === "link" || selectedElement.category === "button" || selectedElement.role === "treeitem" || selectedElement.role === "button") && (
                    <button
                      type="button"
                      className="button button-secondary"
                      style={{
                        width: "100%",
                        justifyContent: "center",
                        padding: "8px 12px",
                        fontSize: "0.78rem",
                        display: "flex",
                        alignItems: "center",
                        gap: 6,
                        background: "var(--v-surface-2)",
                        borderColor: "var(--v-accent)",
                        color: "var(--v-accent)",
                        fontWeight: 600,
                      }}
                      disabled={interactLoading || loading || replayingSteps}
                      onClick={() => void handleInteractiveAction("click", selectedElement.locator_value || selectedElement.text)}
                    >
                      <Compass size={14} className={interactLoading ? "spin" : ""} />
                      {interactLoading ? "Opening in Live Browser..." : `👉 Click & Open in Live Browser`}
                    </button>
                  )}

                  <button
                    type="button"
                    disabled={!selectedElement}
                    onClick={() => {
                      if (selectedElement) {
                        onSelectElement(selectedElement);
                        onClose();
                      }
                    }}
                    className="button button-primary"
                    style={{
                      width: "100%",
                      justifyContent: "center",
                      padding: "9px 16px",
                      fontSize: "0.82rem",
                      fontWeight: 700,
                    }}
                  >
                    <Check size={16} /> Use Selected Element
                  </button>
                  <button type="button" className="button button-secondary" disabled={!selectedElement || savingElement} onClick={() => { setError(null); setRegistryName(""); setShowRegistryForm(true); }}>Save to registry</button>
                  {showRegistryForm && <div style={{display:"flex",gap:8,alignItems:"center"}}>
                    <input autoFocus aria-label="Registry element name" placeholder="Element name (e.g. apex_signin_btn)" maxLength={120} value={registryName} onChange={e=>setRegistryName(e.target.value)} onKeyDown={e=>{if(e.key==="Enter") void saveSelectedElement();if(e.key==="Escape")setShowRegistryForm(false);}} />
                    <button type="button" className="button button-primary" disabled={savingElement || !registryName.trim()} onClick={()=>void saveSelectedElement()}>{savingElement?"Saving...":"Save"}</button>
                    <button type="button" className="button button-secondary" disabled={savingElement} onClick={()=>setShowRegistryForm(false)}>Cancel</button>
                  </div>}
                  {registryToast && <div role="status" style={{color:"var(--v-emerald)",fontSize:"0.78rem",textAlign:"center"}}>{registryToast}</div>}
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
