import React, { useEffect, useState } from "react";
import {
  listDiscoveredElements,
  listCapturedPages,
  discoverElements,
  type DiscoveredElement,
  type CapturedPage,
  type ScenarioStep,
} from "../services/api";

interface ElementCatalogProps {
  projectId: string;
  projectName?: string;
  isInline?: boolean;
  onSelectElement?: (el: DiscoveredElement) => void;
  onAddActionToWorkflow?: (step: ScenarioStep) => void;
  onClose?: () => void;
}

const CATEGORY_TABS = [
  { id: "all", label: "All Controls" },
  { id: "button", label: "Buttons" },
  { id: "link", label: "Links & Navigation" },
  { id: "input", label: "Text Fields" },
  { id: "select", label: "Dropdowns" },
  { id: "checkbox", label: "Checkboxes" },
];

export const ElementCatalog: React.FC<ElementCatalogProps> = ({
  projectId,
  projectName: _projectName = "Application",
  isInline = false,
  onSelectElement,
  onAddActionToWorkflow,
  onClose,
}) => {
  // Page states
  const [pages, setPages] = useState<CapturedPage[]>([]);
  const [selectedPageUrl, setSelectedPageUrl] = useState<string | null>(null);
  const [pagesLoading, setPagesLoading] = useState(true);

  // Element states
  const [elements, setElements] = useState<DiscoveredElement[]>([]);
  const [elementsLoading, setElementsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [categoryFilter, setCategoryFilter] = useState("all");
  const [expandedId, setExpandedId] = useState<string | null>(null);

  // Capture states
  const [capturing, setCapturing] = useState(false);
  const [captureMessage, setCaptureMessage] = useState<string | null>(null);

  // Action configuration modal states
  const [configElement, setConfigElement] = useState<DiscoveredElement | null>(null);
  const [selectedAction, setSelectedAction] = useState<string>("click_element");
  const [actionValue, setActionValue] = useState<string>("");
  const [actionSuccessMsg, setActionSuccessMsg] = useState<string | null>(null);

  // Initial load
  useEffect(() => {
    void loadPages(true);
  }, [projectId]);

  // Load elements when selected page changes
  useEffect(() => {
    if (selectedPageUrl) {
      void loadElementsForPage(selectedPageUrl);
    } else {
      setElements([]);
    }
  }, [selectedPageUrl, projectId]);

  async function loadPages(selectFirst = false) {
    setPagesLoading(true);
    setError(null);
    try {
      const pageList = await listCapturedPages(projectId);
      setPages(pageList);
      if (selectFirst && pageList.length > 0 && !selectedPageUrl) {
        setSelectedPageUrl(pageList[0].page_url);
      }
    } catch (err: any) {
      setError(err?.message || "Failed to load captured pages.");
    } finally {
      setPagesLoading(false);
    }
  }

  async function loadElementsForPage(pageUrl: string) {
    setElementsLoading(true);
    setError(null);
    try {
      const data = await listDiscoveredElements(projectId, pageUrl);
      setElements(data);
    } catch (err: any) {
      setError(err?.message || "Failed to load elements for this page.");
    } finally {
      setElementsLoading(false);
    }
  }

  async function handleCapturePage() {
    setCapturing(true);
    setError(null);
    setCaptureMessage(null);
    try {
      const result = await discoverElements(projectId, false);
      const pageName = result.page_name || "Captured Page";
      setCaptureMessage(
        `Captured "${pageName}": ${result.inserted} new, ${result.updated} updated (${result.elements.length} total unique elements).`
      );
      // Reload pages list and select this newly captured page
      await loadPages(false);
      setSelectedPageUrl(result.page_url);
      await loadElementsForPage(result.page_url);
      setTimeout(() => setCaptureMessage(null), 6000);
    } catch (err: any) {
      setError(err?.message || "Capture failed. Is the browser inspection session active?");
    } finally {
      setCapturing(false);
    }
  }

  // Filter elements
  const filtered = elements.filter((el) => {
    const matchesCategory =
      categoryFilter === "all" ||
      el.category.toLowerCase() === categoryFilter.toLowerCase();
    const matchesSearch =
      !search ||
      el.friendly_name.toLowerCase().includes(search.toLowerCase()) ||
      (el.description || "").toLowerCase().includes(search.toLowerCase()) ||
      el.locator_value.toLowerCase().includes(search.toLowerCase());
    return matchesCategory && matchesSearch;
  });

  const selectedPage = pages.find((p) => p.page_url === selectedPageUrl);

  // Open action configuration dialog for an element
  function openActionConfig(el: DiscoveredElement) {
    setConfigElement(el);
    setActionValue("");
    if (el.category === "input") {
      setSelectedAction("fill_input");
    } else if (el.category === "select") {
      setSelectedAction("select_option");
    } else if (el.category === "checkbox") {
      setSelectedAction("check");
    } else {
      setSelectedAction("click_element");
    }
  }

  // Confirm and add action to workflow
  function handleConfirmAction() {
    if (!configElement) return;

    let desc = "";
    const cleanName = configElement.friendly_name;

    if (selectedAction === "fill_input") {
      desc = `Enter "${actionValue}" into ${cleanName}`;
    } else if (selectedAction === "click_element") {
      desc = `Click ${cleanName}`;
    } else if (selectedAction === "select_option") {
      desc = `Select "${actionValue}" from ${cleanName}`;
    } else if (selectedAction === "check") {
      desc = `Check ${cleanName}`;
    } else if (selectedAction === "uncheck") {
      desc = `Uncheck ${cleanName}`;
    } else if (selectedAction === "verify_element") {
      desc = `Verify ${cleanName} is visible`;
    } else {
      desc = `Interact with ${cleanName}`;
    }

    const newStep: ScenarioStep = {
      step_order: 1, // Will be appended by parent
      action_type: selectedAction,
      locator_type: configElement.locator_strategy,
      locator_value: configElement.locator_value,
      description: desc,
      is_enabled: true,
      action_params: {
        value: actionValue,
        element_friendly_name: configElement.friendly_name,
        element_category: configElement.category,
        page_url: configElement.page_url,
      },
    };

    if (onAddActionToWorkflow) {
      onAddActionToWorkflow(newStep);
      setActionSuccessMsg(`Added action to workflow: ${desc}`);
      setTimeout(() => setActionSuccessMsg(null), 4000);
    } else if (onSelectElement) {
      onSelectElement(configElement);
    }

    setConfigElement(null);
  }

  // Render the core catalog interface
  const catalogContent = (
    <div
      style={{
        display: "flex",
        height: isInline ? "680px" : "80vh",
        maxHeight: isInline ? "none" : "85vh",
        background: "var(--v-surface, #1e2130)",
        borderRadius: isInline ? 12 : 14,
        border: "1px solid var(--v-border, #2e3347)",
        overflow: "hidden",
        boxShadow: isInline ? "none" : "0 25px 70px rgba(0,0,0,0.55)",
      }}
    >
      {/* =========================================================================
          LEFT SIDEBAR: CAPTURED PAGES
      ========================================================================= */}
      <div
        style={{
          width: 270,
          borderRight: "1px solid var(--v-border, #2e3347)",
          background: "var(--v-surface-2, #181b28)",
          display: "flex",
          flexDirection: "column",
          flexShrink: 0,
        }}
      >
        {/* Sidebar Header */}
        <div
          style={{
            padding: "16px 14px",
            borderBottom: "1px solid var(--v-border, #2e3347)",
            display: "flex",
            flexDirection: "column",
            gap: 10,
          }}
        >
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <span
              style={{
                fontSize: "0.76rem",
                fontWeight: 700,
                textTransform: "uppercase",
                letterSpacing: "0.06em",
                color: "var(--v-text-muted, #8892a4)",
              }}
            >
              Captured Pages ({pages.length})
            </span>
            <button
              type="button"
              onClick={() => void loadPages(false)}
              style={{
                background: "transparent",
                border: "none",
                color: "var(--v-text-secondary, #8892a4)",
                fontSize: "0.72rem",
                cursor: "pointer",
                padding: "2px 6px",
              }}
              title="Refresh pages list"
            >
              ↻ Refresh
            </button>
          </div>

          {/* Capture Current Page Button */}
          <button
            type="button"
            onClick={() => void handleCapturePage()}
            disabled={capturing}
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              gap: 8,
              padding: "9px 14px",
              borderRadius: 8,
              border: "none",
              background: capturing ? "var(--v-surface-3, #2e3347)" : "var(--v-accent, #6366f1)",
              color: "#ffffff",
              fontSize: "0.82rem",
              fontWeight: 700,
              cursor: capturing ? "not-allowed" : "pointer",
              boxShadow: "0 2px 8px rgba(99,102,241,0.35)",
              transition: "all 0.15s ease",
            }}
          >
            <span>{capturing ? "⏳ Capturing Page..." : "📷 Capture This Page"}</span>
          </button>
        </div>

        {/* Pages List */}
        <div style={{ flex: 1, overflowY: "auto", padding: "8px 6px" }}>
          {pagesLoading && (
            <div style={{ padding: 24, textAlign: "center", color: "var(--v-text-muted, #8892a4)", fontSize: "0.78rem" }}>
              Loading pages...
            </div>
          )}

          {!pagesLoading && pages.length === 0 && (
            <div style={{ padding: 20, textAlign: "center", color: "var(--v-text-muted, #8892a4)" }}>
              <p style={{ margin: "0 0 6px 0", fontSize: "0.82rem", fontWeight: 600 }}>No pages captured yet</p>
              <p style={{ margin: 0, fontSize: "0.74rem", lineHeight: 1.4 }}>
                Navigate to your application page and click <strong>Capture This Page</strong> above.
              </p>
            </div>
          )}

          {!pagesLoading &&
            pages.map((p) => {
              const isSelected = selectedPageUrl === p.page_url;
              const shortPath = p.page_url.replace(/^https?:\/\/[^/]+/, "") || "/";
              return (
                <div
                  key={p.page_url}
                  onClick={() => setSelectedPageUrl(p.page_url)}
                  style={{
                    padding: "10px 12px",
                    borderRadius: 8,
                    marginBottom: 4,
                    cursor: "pointer",
                    background: isSelected ? "var(--v-accent-light, rgba(99,102,241,0.14))" : "transparent",
                    border: isSelected ? "1px solid var(--v-accent, #6366f1)" : "1px solid transparent",
                    transition: "all 0.12s ease",
                  }}
                >
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 3 }}>
                    <span
                      style={{
                        fontWeight: 700,
                        fontSize: "0.82rem",
                        color: isSelected ? "var(--v-accent, #818cf8)" : "var(--v-text, #e2e8f0)",
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                        maxWidth: 160,
                      }}
                      title={p.page_name}
                    >
                      {p.page_name}
                    </span>
                    <span
                      style={{
                        fontSize: "0.68rem",
                        padding: "2px 6px",
                        borderRadius: 10,
                        background: isSelected ? "var(--v-accent, #6366f1)" : "var(--v-surface, #252b3b)",
                        color: isSelected ? "#fff" : "var(--v-text-muted, #8892a4)",
                        fontWeight: 700,
                      }}
                    >
                      {p.element_count}
                    </span>
                  </div>
                  <div
                    style={{
                      fontSize: "0.7rem",
                      color: "var(--v-text-muted, #6b7280)",
                      fontFamily: "monospace",
                      overflow: "hidden",
                      textOverflow: "ellipsis",
                      whiteSpace: "nowrap",
                    }}
                    title={p.page_url}
                  >
                    {shortPath}
                  </div>
                  {p.last_captured_at && (
                    <div style={{ fontSize: "0.65rem", color: "var(--v-text-muted, #525a6c)", marginTop: 2 }}>
                      Captured {new Date(p.last_captured_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                    </div>
                  )}
                </div>
              );
            })}
        </div>
      </div>

      {/* =========================================================================
          RIGHT MAIN PANEL: ELEMENTS CATALOG FOR SELECTED PAGE
      ========================================================================= */}
      <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", minWidth: 0 }}>
        {/* Main Header */}
        <div
          style={{
            padding: "14px 20px",
            borderBottom: "1px solid var(--v-border, #2e3347)",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            flexShrink: 0,
            gap: 12,
          }}
        >
          <div>
            <h2 style={{ margin: 0, fontSize: "0.95rem", fontWeight: 700, color: "var(--v-text, #e2e8f0)" }}>
              {selectedPage ? `Controls on "${selectedPage.page_name}"` : "Pages & Elements"}
            </h2>
            <p style={{ margin: "2px 0 0 0", fontSize: "0.74rem", color: "var(--v-text-secondary, #8892a4)" }}>
              {selectedPage
                ? `${elements.length} unique interactive controls available on this page`
                : "Select or capture a page to view its catalog of controls"}
            </p>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            {selectedPage && (
              <button
                type="button"
                onClick={() => void handleCapturePage()}
                disabled={capturing}
                style={{
                  padding: "6px 12px",
                  borderRadius: 6,
                  border: "1px solid var(--v-border, #2e3347)",
                  background: "var(--v-surface-2, #252b3b)",
                  color: "var(--v-text, #e2e8f0)",
                  fontSize: "0.76rem",
                  fontWeight: 600,
                  cursor: capturing ? "not-allowed" : "pointer",
                }}
                title="Rescan this page to update controls"
              >
                {capturing ? "⏳ Rescanning..." : "🔄 Recapture Page"}
              </button>
            )}

            {!isInline && onClose && (
              <button
                type="button"
                onClick={onClose}
                style={{
                  background: "transparent",
                  border: "none",
                  color: "var(--v-text-muted, #6b7280)",
                  cursor: "pointer",
                  fontSize: "1.2rem",
                  lineHeight: 1,
                  padding: 4,
                }}
                title="Close catalog"
              >
                ✕
              </button>
            )}
          </div>
        </div>

        {/* Feedback Messages */}
        {captureMessage && (
          <div
            style={{
              padding: "10px 20px",
              background: "rgba(16,185,129,0.12)",
              borderBottom: "1px solid rgba(16,185,129,0.3)",
              color: "#34d399",
              fontSize: "0.78rem",
              fontWeight: 600,
            }}
          >
            ✓ {captureMessage}
          </div>
        )}

        {actionSuccessMsg && (
          <div
            style={{
              padding: "10px 20px",
              background: "rgba(99,102,241,0.12)",
              borderBottom: "1px solid rgba(99,102,241,0.3)",
              color: "#818cf8",
              fontSize: "0.78rem",
              fontWeight: 600,
            }}
          >
            ✓ {actionSuccessMsg}
          </div>
        )}

        {error && (
          <div
            style={{
              padding: "10px 20px",
              background: "rgba(239,68,68,0.12)",
              borderBottom: "1px solid rgba(239,68,68,0.3)",
              color: "#fca5a5",
              fontSize: "0.78rem",
            }}
          >
            ⚠️ {error}
          </div>
        )}

        {/* Search & Filter Bar */}
        <div
          style={{
            padding: "10px 20px",
            borderBottom: "1px solid var(--v-border, #2e3347)",
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 12,
            flexWrap: "wrap",
            flexShrink: 0,
            background: "var(--v-surface, #1e2130)",
          }}
        >
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search controls by name, description or role..."
            style={{
              flex: 1,
              minWidth: 220,
              padding: "7px 12px",
              borderRadius: 6,
              border: "1px solid var(--v-border, #2e3347)",
              background: "var(--v-surface-2, #252b3b)",
              color: "var(--v-text, #e2e8f0)",
              fontSize: "0.8rem",
              outline: "none",
            }}
          />

          {/* Category Tabs */}
          <div style={{ display: "flex", gap: 4, overflowX: "auto" }}>
            {CATEGORY_TABS.map((tab) => {
              const active = categoryFilter === tab.id;
              return (
                <button
                  key={tab.id}
                  type="button"
                  onClick={() => setCategoryFilter(tab.id)}
                  style={{
                    padding: "5px 10px",
                    borderRadius: 6,
                    border: "none",
                    fontSize: "0.74rem",
                    fontWeight: active ? 700 : 500,
                    background: active ? "var(--v-accent, #6366f1)" : "var(--v-surface-2, #252b3b)",
                    color: active ? "#ffffff" : "var(--v-text-secondary, #8892a4)",
                    cursor: "pointer",
                    whiteSpace: "nowrap",
                    transition: "all 0.1s ease",
                  }}
                >
                  {tab.label}
                </button>
              );
            })}
          </div>
        </div>

        {/* Elements List Area */}
        <div style={{ flex: 1, overflowY: "auto", padding: 16 }}>
          {elementsLoading && (
            <div style={{ padding: 48, textAlign: "center", color: "var(--v-text-muted, #8892a4)", fontSize: "0.82rem" }}>
              Loading controls for this page...
            </div>
          )}

          {!elementsLoading && !selectedPageUrl && (
            <div style={{ padding: 48, textAlign: "center", color: "var(--v-text-muted, #8892a4)" }}>
              <span style={{ fontSize: "2rem", display: "block", marginBottom: 8 }}>📄</span>
              <p style={{ margin: 0, fontWeight: 600, color: "var(--v-text, #e2e8f0)" }}>Select a captured page</p>
              <p style={{ margin: "4px 0 0 0", fontSize: "0.78rem" }}>
                Choose a page from the left to view its controls, or capture a new page above.
              </p>
            </div>
          )}

          {!elementsLoading && selectedPageUrl && elements.length === 0 && (
            <div style={{ padding: 48, textAlign: "center", color: "var(--v-text-muted, #8892a4)" }}>
              <span style={{ fontSize: "2rem", display: "block", marginBottom: 8 }}>🔍</span>
              <p style={{ margin: 0, fontWeight: 600, color: "var(--v-text, #e2e8f0)" }}>No controls recorded on this page</p>
              <p style={{ margin: "4px 0 0 0", fontSize: "0.78rem" }}>
                Click <strong>Recapture Page</strong> to scan the rendered DOM.
              </p>
            </div>
          )}

          {!elementsLoading && selectedPageUrl && elements.length > 0 && filtered.length === 0 && (
            <div style={{ padding: 32, textAlign: "center", color: "var(--v-text-muted, #8892a4)", fontSize: "0.82rem" }}>
              No controls match your filter.
            </div>
          )}

          {/* Cards for each element */}
          {!elementsLoading &&
            filtered.map((el) => {
              const isExpanded = expandedId === el.id;
              const catBadge = getCategoryBadge(el.category);
              return (
                <div
                  key={el.id}
                  style={{
                    background: "var(--v-surface-2, #252b3b)",
                    border: "1px solid var(--v-border, #2e3347)",
                    borderRadius: 8,
                    marginBottom: 10,
                    padding: "12px 16px",
                    transition: "all 0.12s ease",
                  }}
                >
                  <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 12 }}>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginBottom: 4 }}>
                        <span style={{ fontWeight: 700, fontSize: "0.86rem", color: "var(--v-text, #e2e8f0)" }}>
                          {el.friendly_name}
                        </span>
                        <span
                          style={{
                            fontSize: "0.66rem",
                            fontWeight: 700,
                            padding: "2px 8px",
                            borderRadius: 10,
                            background: catBadge.bg,
                            color: catBadge.text,
                          }}
                        >
                          {catBadge.label}
                        </span>
                        {el.in_dialog && (
                          <span
                            style={{
                              fontSize: "0.66rem",
                              fontWeight: 600,
                              padding: "2px 6px",
                              borderRadius: 4,
                              background: "rgba(245,158,11,0.15)",
                              color: "#fbbf24",
                            }}
                          >
                            Modal Dialog
                          </span>
                        )}
                      </div>

                      {/* Plain-language description */}
                      <p style={{ margin: "2px 0 6px 0", fontSize: "0.76rem", color: "var(--v-text-secondary, #94a3b8)" }}>
                        {el.description || getDefaultDescription(el)}
                      </p>

                      {/* Expandable technical details toggle */}
                      <button
                        type="button"
                        onClick={() => setExpandedId(isExpanded ? null : el.id)}
                        style={{
                          background: "transparent",
                          border: "none",
                          color: "var(--v-text-muted, #6b7280)",
                          fontSize: "0.7rem",
                          fontWeight: 600,
                          cursor: "pointer",
                          padding: 0,
                          display: "inline-flex",
                          alignItems: "center",
                          gap: 4,
                        }}
                      >
                        <span>{isExpanded ? "▲ Hide Technical Details" : "▼ Technical Details"}</span>
                      </button>
                    </div>

                    {/* Action Buttons */}
                    <div style={{ display: "flex", gap: 6, flexShrink: 0 }}>
                      {onAddActionToWorkflow ? (
                        <button
                          type="button"
                          onClick={() => openActionConfig(el)}
                          style={{
                            padding: "6px 14px",
                            borderRadius: 6,
                            border: "none",
                            background: "var(--v-accent, #6366f1)",
                            color: "#ffffff",
                            fontSize: "0.76rem",
                            fontWeight: 700,
                            cursor: "pointer",
                            transition: "all 0.12s",
                          }}
                        >
                          + Add Action
                        </button>
                      ) : (
                        <button
                          type="button"
                          onClick={() => onSelectElement && onSelectElement(el)}
                          style={{
                            padding: "6px 14px",
                            borderRadius: 6,
                            border: "1px solid var(--v-accent, #6366f1)",
                            background: "transparent",
                            color: "var(--v-accent, #6366f1)",
                            fontSize: "0.76rem",
                            fontWeight: 700,
                            cursor: "pointer",
                          }}
                        >
                          Select
                        </button>
                      )}
                    </div>
                  </div>

                  {/* Expanded Technical Details */}
                  {isExpanded && (
                    <div
                      style={{
                        marginTop: 10,
                        paddingTop: 10,
                        borderTop: "1px solid var(--v-border, #2e3347)",
                        display: "grid",
                        gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))",
                        gap: "8px 12px",
                        fontSize: "0.72rem",
                      }}
                    >
                      <div>
                        <span style={{ color: "var(--v-text-muted, #6b7280)", display: "block" }}>Locator Strategy</span>
                        <span style={{ color: "var(--v-accent, #818cf8)", fontFamily: "monospace" }}>{el.locator_strategy}</span>
                      </div>
                      <div style={{ gridColumn: "span 2" }}>
                        <span style={{ color: "var(--v-text-muted, #6b7280)", display: "block" }}>Locator Value</span>
                        <span style={{ color: "var(--v-text, #e2e8f0)", fontFamily: "monospace", wordBreak: "break-all" }}>
                          {el.locator_value}
                        </span>
                      </div>
                      <div>
                        <span style={{ color: "var(--v-text-muted, #6b7280)", display: "block" }}>HTML Tag</span>
                        <span style={{ color: "var(--v-text, #e2e8f0)" }}>&lt;{el.tag_name}&gt;</span>
                      </div>
                      {el.role && (
                        <div>
                          <span style={{ color: "var(--v-text-muted, #6b7280)", display: "block" }}>ARIA Role</span>
                          <span style={{ color: "var(--v-text, #e2e8f0)" }}>{el.role}</span>
                        </div>
                      )}
                      {el.in_dialog && (
                        <div>
                          <span style={{ color: "var(--v-text-muted, #6b7280)", display: "block" }}>Modal Scope</span>
                          <span style={{ color: "#fbbf24" }}>{el.dialog_title || "Active Dialog"}</span>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              );
            })}
        </div>
      </div>

      {/* =========================================================================
          COMPACT ACTION CONFIGURATION POPUP
      ========================================================================= */}
      {configElement && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            zIndex: 1100,
            background: "rgba(0,0,0,0.65)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: 20,
          }}
          onClick={(e) => {
            if (e.target === e.currentTarget) setConfigElement(null);
          }}
        >
          <div
            style={{
              background: "var(--v-surface, #1e2130)",
              border: "1px solid var(--v-border, #2e3347)",
              borderRadius: 12,
              padding: 24,
              width: "100%",
              maxWidth: 460,
              boxShadow: "0 20px 50px rgba(0,0,0,0.6)",
            }}
          >
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
              <h3 style={{ margin: 0, fontSize: "0.95rem", fontWeight: 700, color: "var(--v-text, #e2e8f0)" }}>
                Configure Workflow Action
              </h3>
              <button
                type="button"
                onClick={() => setConfigElement(null)}
                style={{ background: "transparent", border: "none", color: "var(--v-text-muted, #6b7280)", cursor: "pointer", fontSize: "1.1rem" }}
              >
                ✕
              </button>
            </div>

            {/* Target Element Summary */}
            <div
              style={{
                background: "var(--v-surface-2, #252b3b)",
                borderRadius: 8,
                padding: "10px 14px",
                marginBottom: 16,
                border: "1px solid var(--v-border, #2e3347)",
              }}
            >
              <div style={{ fontSize: "0.7rem", color: "var(--v-text-muted, #6b7280)", textTransform: "uppercase", fontWeight: 700 }}>
                Target Control
              </div>
              <div style={{ fontSize: "0.88rem", fontWeight: 700, color: "var(--v-accent, #818cf8)", marginTop: 2 }}>
                {configElement.friendly_name}
              </div>
              <div style={{ fontSize: "0.72rem", color: "var(--v-text-secondary, #94a3b8)", marginTop: 2 }}>
                Page: {configElement.page_name || "Current Page"}
              </div>
            </div>

            {/* Action Type Dropdown */}
            <div style={{ marginBottom: 14 }}>
              <label style={{ display: "block", fontSize: "0.76rem", fontWeight: 700, color: "var(--v-text, #e2e8f0)", marginBottom: 6 }}>
                Action to Perform
              </label>
              <select
                value={selectedAction}
                onChange={(e) => setSelectedAction(e.target.value)}
                style={{
                  width: "100%",
                  padding: "8px 12px",
                  borderRadius: 6,
                  border: "1px solid var(--v-border, #2e3347)",
                  background: "var(--v-surface-2, #252b3b)",
                  color: "var(--v-text, #e2e8f0)",
                  fontSize: "0.82rem",
                  outline: "none",
                }}
              >
                {getActionOptionsForCategory(configElement.category).map((opt) => (
                  <option key={opt.action} value={opt.action}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </div>

            {/* Value input for text fields or dropdowns */}
            {(selectedAction === "fill_input" || selectedAction === "select_option") && (
              <div style={{ marginBottom: 16 }}>
                <label style={{ display: "block", fontSize: "0.76rem", fontWeight: 700, color: "var(--v-text, #e2e8f0)", marginBottom: 6 }}>
                  {selectedAction === "fill_input" ? "Text Value to Enter" : "Option to Select"}
                </label>
                <input
                  type="text"
                  value={actionValue}
                  onChange={(e) => setActionValue(e.target.value)}
                  placeholder={selectedAction === "fill_input" ? 'e.g. "8", "Project Alpha"' : 'e.g. "Approved"'}
                  autoFocus
                  style={{
                    width: "100%",
                    padding: "8px 12px",
                    borderRadius: 6,
                    border: "1px solid var(--v-border, #2e3347)",
                    background: "var(--v-surface-2, #252b3b)",
                    color: "var(--v-text, #e2e8f0)",
                    fontSize: "0.82rem",
                    outline: "none",
                    boxSizing: "border-box",
                  }}
                />
              </div>
            )}

            {/* Action Summary Preview */}
            <div
              style={{
                padding: "8px 12px",
                borderRadius: 6,
                background: "var(--v-surface-2, #252b3b)",
                marginBottom: 18,
                fontSize: "0.75rem",
                color: "var(--v-text-secondary, #94a3b8)",
              }}
            >
              <strong>Summary:</strong>{" "}
              {selectedAction === "fill_input"
                ? `Enter "${actionValue || "..."}" into ${configElement.friendly_name}`
                : selectedAction === "click_element"
                ? `Click ${configElement.friendly_name}`
                : selectedAction === "select_option"
                ? `Select "${actionValue || "..."}" from ${configElement.friendly_name}`
                : selectedAction === "check"
                ? `Check ${configElement.friendly_name}`
                : selectedAction === "uncheck"
                ? `Uncheck ${configElement.friendly_name}`
                : `Verify ${configElement.friendly_name} is visible`}
            </div>

            {/* Action Buttons */}
            <div style={{ display: "flex", justifyContent: "flex-end", gap: 10 }}>
              <button
                type="button"
                onClick={() => setConfigElement(null)}
                style={{
                  padding: "7px 16px",
                  borderRadius: 6,
                  border: "1px solid var(--v-border, #2e3347)",
                  background: "transparent",
                  color: "var(--v-text-secondary, #8892a4)",
                  fontSize: "0.8rem",
                  cursor: "pointer",
                }}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleConfirmAction}
                style={{
                  padding: "7px 18px",
                  borderRadius: 6,
                  border: "none",
                  background: "var(--v-accent, #6366f1)",
                  color: "#ffffff",
                  fontSize: "0.8rem",
                  fontWeight: 700,
                  cursor: "pointer",
                  boxShadow: "0 2px 8px rgba(99,102,241,0.35)",
                }}
              >
                Add Action to Workflow
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );

  // If inline, render directly
  if (isInline) {
    return catalogContent;
  }

  // If modal, wrap in overlay
  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        zIndex: 1000,
        background: "rgba(0,0,0,0.65)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        padding: 20,
      }}
      onClick={(e) => {
        if (e.target === e.currentTarget && onClose) onClose();
      }}
    >
      <div style={{ width: "100%", maxWidth: 1050 }}>{catalogContent}</div>
    </div>
  );
};

// Helper for type badges
function getCategoryBadge(category: string): { label: string; bg: string; text: string } {
  switch (category.toLowerCase()) {
    case "button":
      return { label: "Button", bg: "rgba(99,102,241,0.15)", text: "#818cf8" };
    case "input":
      return { label: "Input Field", bg: "rgba(16,185,129,0.15)", text: "#34d399" };
    case "link":
      return { label: "Link", bg: "rgba(245,158,11,0.15)", text: "#fbbf24" };
    case "select":
      return { label: "Dropdown", bg: "rgba(139,92,246,0.15)", text: "#c4b5fd" };
    case "checkbox":
      return { label: "Checkbox", bg: "rgba(236,72,153,0.15)", text: "#f9a8d4" };
    case "radio":
      return { label: "Radio", bg: "rgba(236,72,153,0.15)", text: "#f9a8d4" };
    default:
      return { label: "Control", bg: "rgba(107,114,128,0.15)", text: "#9ca3af" };
  }
}

function getDefaultDescription(el: DiscoveredElement): string {
  if (el.category === "button") return `Clicks the ${el.friendly_name}`;
  if (el.category === "input") return el.placeholder ? `Enter ${el.placeholder}` : `Text input field`;
  if (el.category === "link") return `Navigates to ${el.friendly_name}`;
  if (el.category === "select") return `Select an option`;
  if (el.category === "checkbox") return `Toggles checkbox`;
  return "Interactive user control";
}

function getActionOptionsForCategory(category: string): { action: string; label: string }[] {
  switch (category.toLowerCase()) {
    case "button":
      return [
        { action: "click_element", label: "Click Button" },
        { action: "verify_element", label: "Verify Button is Visible" },
      ];
    case "input":
      return [
        { action: "fill_input", label: "Enter Text Value" },
        { action: "verify_element", label: "Verify Field is Visible" },
      ];
    case "select":
      return [
        { action: "select_option", label: "Select Option" },
        { action: "verify_element", label: "Verify Dropdown is Visible" },
      ];
    case "checkbox":
      return [
        { action: "check", label: "Check (Select)" },
        { action: "uncheck", label: "Uncheck (Deselect)" },
        { action: "verify_element", label: "Verify Checkbox is Visible" },
      ];
    case "link":
      return [
        { action: "click_element", label: "Click / Open Link" },
        { action: "verify_element", label: "Verify Link is Visible" },
      ];
    default:
      return [
        { action: "click_element", label: "Click Element" },
        { action: "verify_element", label: "Verify Element is Visible" },
      ];
  }
}
