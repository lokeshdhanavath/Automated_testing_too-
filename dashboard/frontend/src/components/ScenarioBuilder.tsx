import React, { useEffect, useState } from "react";
import {
  Globe,
  LogIn,
  Compass,
  FormInput,
  MousePointerClick,
  ListFilter,
  CheckCircle2,
  Clock,
  Play,
  Plus,
  Pencil,
  Trash2,
  Copy,
  ArrowUp,
  ArrowDown,
  RefreshCw,
  Eye,
  EyeOff,
  Settings2,
  ChevronDown,
  ChevronUp,
  Sparkles,
  Layers,
  Check,
  X,
  FileCode,
  Bookmark,
  AlertCircle,
  Square,
  MousePointer,
  FileSpreadsheet,
  Upload,
} from "lucide-react";
import {
  getProjectScenarios,
  createScenario,
  getProjectCredentials,
  runDynamicWorkflow,
} from "../services/api";
import type {
  ScenarioItem,
  ScenarioStep,
  CredentialItem,
  ProjectConfig,
  InspectElement,
} from "../services/api";
import { ElementPickerModal } from "./ElementPickerModal";

interface ScenarioBuilderProps {
  projectId: string;
  projectName: string;
  baseUrl?: string;
  projects?: ProjectConfig[];
  onSelectProject?: (projectId: string) => void;
  onNavigateToCredentials?: () => void;
  onNavigateToApplications?: () => void;
  onRunTriggered: (runId: string) => void;
  running?: boolean;
  onStopRun?: () => void;
}

export interface ActionDef {
  type: string;
  name: string;
  shortDesc: string;
  icon: React.ElementType;
}

export const REUSABLE_ACTIONS: ActionDef[] = [
  {
    type: "open_app",
    name: "Open Application",
    shortDesc: "Opens the application's base URL automatically.",
    icon: Globe,
  },
  {
    type: "login",
    name: "Login",
    shortDesc: "Authenticates using saved vault credentials without re-entering passwords.",
    icon: LogIn,
  },
  {
    type: "navigate",
    name: "Navigate",
    shortDesc: "Navigates to a page path or clicks an in-app menu item.",
    icon: Compass,
  },
  {
    type: "fill_input",
    name: "Fill Input",
    shortDesc: "Enters text or data into a form input or search field.",
    icon: FormInput,
  },
  {
    type: "click_element",
    name: "Click Element",
    shortDesc: "Clicks a button, link, checkbox, or tab control.",
    icon: MousePointerClick,
  },
  {
    type: "select_option",
    name: "Select Option",
    shortDesc: "Selects an item from a dropdown list by label or value.",
    icon: ListFilter,
  },
  {
    type: "verify_element",
    name: "Verify Element",
    shortDesc: "Asserts element visibility, text, input value, or URL.",
    icon: CheckCircle2,
  },
  {
    type: "wait_for_element",
    name: "Wait for Element",
    shortDesc: "Pauses for element state (visible/hidden) or duration.",
    icon: Clock,
  },
];

const LOCATOR_STRATEGIES = [
  { value: "smart", label: "Smart Dynamic (Auto-Detect Role/Label/Selector)" },
  { value: "role", label: "Accessible Role & Name (e.g. textbox:Username, button:Submit)" },
  { value: "label", label: "Field Label (e.g. Username, Email, Password)" },
  { value: "placeholder", label: "Placeholder Text (e.g. Enter your name)" },
  { value: "text", label: "Visible Button/Link Text" },
  { value: "css", label: "CSS Selector" },
  { value: "xpath", label: "XPath Expression" },
];

export const ScenarioBuilder: React.FC<ScenarioBuilderProps> = ({
  projectId,
  projectName,
  baseUrl,
  projects = [],
  onSelectProject,
  onNavigateToCredentials,
  onNavigateToApplications,
  onRunTriggered,
  running = false,
  onStopRun,
}) => {
  // Application credentials & status
  const [credentials, setCredentials] = useState<CredentialItem[]>([]);
  const [credentialsLoading, setCredentialsLoading] = useState(false);
  const [savedWorkflows, setSavedWorkflows] = useState<ScenarioItem[]>([]);

  // Workflow builder state
  const [workflowName, setWorkflowName] = useState("Dynamic Browser Workflow");
  const [workflowSteps, setWorkflowSteps] = useState<ScenarioStep[]>([
    {
      step_order: 1,
      action_type: "open_app",
      description: "Open application base URL",
      locator_value: "",
      action_params: {},
      is_enabled: true,
    },
    {
      step_order: 2,
      action_type: "login",
      description: "Login with vault credentials",
      locator_value: "",
      action_params: {},
      is_enabled: true,
    },
  ]);

  // Modal / Editing states
  const [editingStepIndex, setEditingStepIndex] = useState<number | null>(null);
  const [stepModalOpen, setStepModalOpen] = useState(false);
  const [modalStepData, setModalStepData] = useState<ScenarioStep>({
    step_order: 1,
    action_type: "open_app",
    locator_type: "smart",
    locator_value: "",
    action_params: {},
    description: "",
    is_enabled: true,
  });
  const [showAdvancedLocators, setShowAdvancedLocators] = useState(false);

  // Tab: "steps" vs "csv"
  const [builderTab, setBuilderTab] = useState<"steps" | "csv">("steps");

  // CSV Data inputs state
  const [csvColumns, setCsvColumns] = useState<string[]>(["Hours", "Task_Name", "Project", "Comments"]);
  const [csvRows, setCsvRows] = useState<Record<string, string>[]>([
    { Hours: "8.0", Task_Name: "Frontend Development", Project: "Timesheet App", Comments: "Dynamic action tests" },
    { Hours: "7.5", Task_Name: "Backend Automation", Project: "Veriqon Core", Comments: "Fast Playwright execution" },
    { Hours: "6.0", Task_Name: "Documentation & Release", Project: "Platform", Comments: "End-to-end verification" },
  ]);
  const [activeRowIndex, setActiveRowIndex] = useState<number>(0);
  const [copiedVarName, setCopiedVarName] = useState<string | null>(null);

  function handleCsvFileUpload(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (e) => {
      const text = e.target?.result as string;
      if (!text) return;
      parseAndSetCsv(text);
    };
    reader.readAsText(file);
  }

  function parseAndSetCsv(csvText: string) {
    const lines = csvText.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
    if (lines.length < 2) {
      alert("CSV file must have at least a header line and one data row.");
      return;
    }

    const headers = lines[0].split(",").map((h) => h.replace(/^["']|["']$/g, "").trim());
    const rows: Record<string, string>[] = [];

    for (let i = 1; i < lines.length; i++) {
      const values = lines[i].split(",").map((v) => v.replace(/^["']|["']$/g, "").trim());
      const rowObj: Record<string, string> = {};
      headers.forEach((h, idx) => {
        rowObj[h] = values[idx] || "";
      });
      rows.push(rowObj);
    }

    setCsvColumns(headers);
    setCsvRows(rows);
    setActiveRowIndex(0);
    setStatusMessage({
      type: "success",
      text: `Loaded CSV with ${rows.length} rows and ${headers.length} columns (${headers.join(", ")}).`,
    });
  }

  function handleLoadSampleCsv() {
    setCsvColumns(["Hours", "Task_Name", "Project", "Comments", "Date"]);
    setCsvRows([
      { Hours: "8.0", Task_Name: "Frontend Development", Project: "Timesheet App", Comments: "Dynamic action tests", Date: "2026-10-23" },
      { Hours: "7.5", Task_Name: "Backend Automation", Project: "Veriqon Core", Comments: "Fast Playwright execution", Date: "2026-10-24" },
      { Hours: "6.0", Task_Name: "Documentation & Release", Project: "Platform", Comments: "End-to-end verification", Date: "2026-10-25" },
    ]);
    setActiveRowIndex(0);
    setStatusMessage({ type: "success", text: "Loaded sample Timesheet CSV dataset (3 rows, 5 columns)." });
  }

  function handleAddCsvRow() {
    const newRow: Record<string, string> = {};
    csvColumns.forEach((c) => {
      newRow[c] = "";
    });
    setCsvRows([...csvRows, newRow]);
  }

  function handleRemoveCsvRow(idx: number) {
    const updated = csvRows.filter((_, i) => i !== idx);
    setCsvRows(updated);
    if (activeRowIndex >= updated.length) {
      setActiveRowIndex(Math.max(0, updated.length - 1));
    }
  }

  function handleCsvCellChange(rowIdx: number, colName: string, val: string) {
    const updated = [...csvRows];
    updated[rowIdx] = { ...updated[rowIdx], [colName]: val };
    setCsvRows(updated);
  }

  function handleAddCsvColumn() {
    const colName = prompt("Enter new column name (e.g. Employee_ID, Status):");
    if (!colName || !colName.trim()) return;
    const cleanCol = colName.trim().replace(/[^a-zA-Z0-9_-]/g, "_");
    if (csvColumns.includes(cleanCol)) {
      alert("Column already exists.");
      return;
    }
    setCsvColumns([...csvColumns, cleanCol]);
    setCsvRows(csvRows.map((r) => ({ ...r, [cleanCol]: "" })));
  }

  function handleClearCsv() {
    if (window.confirm("Are you sure you want to clear all CSV data?")) {
      setCsvColumns([]);
      setCsvRows([]);
      setActiveRowIndex(0);
    }
  }

  // Element Picker states
  const [elementPickerOpen, setElementPickerOpen] = useState(false);
  const [currentPickingTarget, setCurrentPickingTarget] = useState<string>("main");
  const [navigateMethod, setNavigateMethod] = useState<"menu" | "url">("menu");

  function handlePickedElement(el: InspectElement) {
    if (currentPickingTarget === "username") {
      setModalStepData({
        ...modalStepData,
        action_params: {
          ...modalStepData.action_params,
          username_locator: el.locator_value,
          username_locator_type: el.locator_strategy,
          username_friendly_name: el.friendly_name,
        },
      });
    } else if (currentPickingTarget === "password") {
      setModalStepData({
        ...modalStepData,
        action_params: {
          ...modalStepData.action_params,
          password_locator: el.locator_value,
          password_locator_type: el.locator_strategy,
          password_friendly_name: el.friendly_name,
        },
      });
    } else if (currentPickingTarget === "submit") {
      setModalStepData({
        ...modalStepData,
        action_params: {
          ...modalStepData.action_params,
          submit_locator: el.locator_value,
          submit_locator_type: el.locator_strategy,
          submit_friendly_name: el.friendly_name,
        },
      });
    } else {
      const isNavigate = modalStepData.action_type === "navigate";
      const isFill = modalStepData.action_type === "fill_input";
      const isClick = modalStepData.action_type === "click_element";
      const isSelect = modalStepData.action_type === "select_option";
      const isVerify = modalStepData.action_type === "verify_element";

      let autoDesc = modalStepData.description;
      if (!autoDesc || autoDesc.startsWith("Step") || autoDesc.includes("element") || autoDesc.includes("input") || autoDesc.includes("path")) {
        if (isNavigate) autoDesc = `Navigate to ${el.text || el.label || el.locator_value}`;
        else if (isFill) autoDesc = `Fill ${el.label || el.placeholder || el.friendly_name}`;
        else if (isClick) autoDesc = `Click "${el.text || el.friendly_name}"`;
        else if (isSelect) autoDesc = `Select option in ${el.friendly_name}`;
        else if (isVerify) autoDesc = `Verify ${el.friendly_name}`;
      }

      const updatedParams: Record<string, any> = {
        ...modalStepData.action_params,
        element_friendly_name: el.friendly_name,
        element_category: el.category,
        available_options: el.options || [],
      };

      if (isNavigate) {
        updatedParams.method = "click";
        updatedParams.path = el.locator_value;
        setNavigateMethod("menu");
      }

      setModalStepData({
        ...modalStepData,
        locator_value: el.locator_value,
        locator_type: el.locator_strategy,
        description: autoDesc,
        action_params: updatedParams,
      });
    }
  }

  // App switcher dropdown state
  const [showAppSelector, setShowAppSelector] = useState(false);

  // Save workflow modal state
  const [showSaveModal, setShowSaveModal] = useState(false);
  const [saveWorkflowTitle, setSaveWorkflowTitle] = useState("");
  const [saveWorkflowDesc, setSaveWorkflowDesc] = useState("");
  const [savingWorkflow, setSavingWorkflow] = useState(false);

  // Execution state
  const [executing, setExecuting] = useState(false);
  const [statusMessage, setStatusMessage] = useState<{ type: "success" | "error"; text: string } | null>(null);

  // Load application credentials & saved workflows
  useEffect(() => {
    void loadAppMetadata();
  }, [projectId]);

  async function loadAppMetadata() {
    setCredentialsLoading(true);
    setStatusMessage(null);
    try {
      const [creds, scens] = await Promise.all([
        getProjectCredentials(projectId).catch(() => []),
        getProjectScenarios(projectId).catch(() => []),
      ]);
      setCredentials(creds);
      setSavedWorkflows(scens);
    } catch (err: any) {
      console.error("Error loading app metadata:", err);
    } finally {
      setCredentialsLoading(false);
    }
  }

  const effectiveBaseUrl = baseUrl || (projects.find((p) => p.id === projectId)?.base_url || "");
  const hasVaultCredentials = credentials.length > 0;

  // Add action from library
  function handleAddAction(actionType: string) {
    const actionDef = REUSABLE_ACTIONS.find((a) => a.type === actionType);
    const newOrder = workflowSteps.length + 1;
    let initialParams: Record<string, any> = {};
    let initialDesc = actionDef ? actionDef.name : `Step ${newOrder}`;
    let initialLocator = "";

    if (actionType === "open_app") {
      initialDesc = "Open application base URL";
    } else if (actionType === "login") {
      initialDesc = "Login with application vault credentials";
    } else if (actionType === "navigate") {
      initialParams = { method: "path", path: "/" };
      initialDesc = "Navigate to page path";
    } else if (actionType === "fill_input") {
      initialParams = { value: "", clear_first: true };
      initialDesc = "Fill input field";
    } else if (actionType === "click_element") {
      initialParams = { click_type: "click" };
      initialDesc = "Click element";
    } else if (actionType === "select_option") {
      initialParams = { value: "" };
      initialDesc = "Select dropdown option";
    } else if (actionType === "verify_element") {
      initialParams = { verify_type: "visible", expected: "" };
      initialDesc = "Verify element visibility";
    } else if (actionType === "wait_for_element") {
      initialParams = { condition: "visible", timeout_ms: 5000 };
      initialDesc = "Wait for element";
    }

    const newStep: ScenarioStep = {
      step_order: newOrder,
      action_type: actionType,
      locator_type: "smart",
      locator_value: initialLocator,
      action_params: initialParams,
      description: initialDesc,
      is_enabled: true,
    };

    setEditingStepIndex(null);
    setModalStepData(newStep);
    setShowAdvancedLocators(false);
    setNavigateMethod("menu");
    setStepModalOpen(true);
  }

  function handleEditStep(index: number) {
    const step = workflowSteps[index];
    setEditingStepIndex(index);
    setModalStepData(JSON.parse(JSON.stringify(step)));
    if (step.action_type === "navigate") {
      const isPath = step.action_params?.method === "path" || (step.locator_value && (step.locator_value.startsWith("/") || step.locator_value.startsWith("http")));
      setNavigateMethod(isPath ? "url" : "menu");
    }
    setShowAdvancedLocators(
      Boolean(step.locator_type && step.locator_type !== "smart") ||
      Boolean(step.action_params?.username_locator || step.action_params?.password_locator)
    );
    setStepModalOpen(true);
  }

  function handleSaveStepModal() {
    const type = modalStepData.action_type;
    if (type === "navigate") {
      const target = modalStepData.locator_value || modalStepData.action_params?.path;
      if (!target || !target.trim()) {
        alert("Please provide the Target Link Name or URL Route to navigate to.");
        return;
      }
    } else if (type === "fill_input") {
      if (!modalStepData.locator_value?.trim()) {
        alert("Please provide the Target Input Field Name or Selector.");
        return;
      }
      if (modalStepData.action_params?.value === undefined || modalStepData.action_params?.value === "") {
        alert("Please provide the Value to Enter.");
        return;
      }
    } else if (type === "click_element") {
      if (!modalStepData.locator_value?.trim()) {
        alert("Please provide the Button or Element Name to Click.");
        return;
      }
    } else if (type === "select_option") {
      if (!modalStepData.locator_value?.trim()) {
        alert("Please provide the Dropdown Select Element.");
        return;
      }
    }

    const updated = [...workflowSteps];
    if (editingStepIndex !== null) {
      updated[editingStepIndex] = modalStepData;
    } else {
      updated.push({ ...modalStepData, step_order: updated.length + 1 });
    }
    setWorkflowSteps(updated);
    setStepModalOpen(false);
  }

  function handleRemoveStep(index: number) {
    const updated = workflowSteps.filter((_, i) => i !== index);
    const reordered = updated.map((step, idx) => ({ ...step, step_order: idx + 1 }));
    setWorkflowSteps(reordered);
  }

  function handleDuplicateStep(index: number) {
    const step = workflowSteps[index];
    const duplicated: ScenarioStep = {
      ...JSON.parse(JSON.stringify(step)),
      description: `${step.description} (Copy)`,
    };
    const updated = [...workflowSteps];
    updated.splice(index + 1, 0, duplicated);
    const reordered = updated.map((s, idx) => ({ ...s, step_order: idx + 1 }));
    setWorkflowSteps(reordered);
  }

  function handleMoveStep(index: number, direction: "up" | "down") {
    if (direction === "up" && index === 0) return;
    if (direction === "down" && index === workflowSteps.length - 1) return;

    const targetIndex = direction === "up" ? index - 1 : index + 1;
    const updated = [...workflowSteps];
    const temp = updated[index];
    updated[index] = updated[targetIndex];
    updated[targetIndex] = temp;

    const reordered = updated.map((s, idx) => ({ ...s, step_order: idx + 1 }));
    setWorkflowSteps(reordered);
  }

  function handleToggleEnable(index: number) {
    const updated = [...workflowSteps];
    updated[index] = { ...updated[index], is_enabled: !updated[index].is_enabled };
    setWorkflowSteps(updated);
  }

  function loadStandardTemplate() {
    setWorkflowSteps([
      {
        step_order: 1,
        action_type: "open_app",
        description: "Open application base URL",
        locator_value: "",
        action_params: {},
        is_enabled: true,
      },
      {
        step_order: 2,
        action_type: "login",
        description: "Login with vault credentials",
        locator_value: "",
        action_params: {},
        is_enabled: true,
      },
      {
        step_order: 3,
        action_type: "wait_for_element",
        description: "Wait 2 seconds for page load",
        locator_value: "",
        action_params: { condition: "duration", duration_ms: 2000 },
        is_enabled: true,
      },
      {
        step_order: 4,
        action_type: "verify_element",
        description: "Verify page URL or title loaded",
        locator_value: "",
        action_params: { verify_type: "url_contains", expected: effectiveBaseUrl.replace(/https?:\/\//, "").split("/")[0] },
        is_enabled: true,
      },
    ]);
    setStatusMessage({ type: "success", text: "Loaded standard login & verification workflow." });
  }

  function loadSavedWorkflow(scenario: ScenarioItem) {
    if (scenario.steps && scenario.steps.length > 0) {
      setWorkflowSteps(scenario.steps);
      setWorkflowName(scenario.name);
      setStatusMessage({ type: "success", text: `Loaded saved workflow: "${scenario.name}".` });
    }
  }

  // Run dynamic workflow immediately
  async function handleRunWorkflow() {
    if (workflowSteps.length === 0) {
      setStatusMessage({ type: "error", text: "Workflow has no steps. Please add at least one action." });
      return;
    }

    setExecuting(true);
    setStatusMessage(null);

    try {
      const activeDataRow = csvRows.length > 0 ? (csvRows[activeRowIndex] || csvRows[0]) : undefined;
      const response = await runDynamicWorkflow(projectId, {
        name: workflowName || "Dynamic Browser Workflow",
        steps: workflowSteps,
        failure_policy: "stop",
        timeout_seconds: 120,
        dataset_row: activeDataRow,
        dataset_rows: csvRows.length > 0 ? csvRows : undefined,
      });

      setStatusMessage({ type: "success", text: `Workflow execution started! Run ID: ${response.run_id}` });
      if (onRunTriggered && response.run_id) {
        onRunTriggered(response.run_id);
      }
    } catch (err: any) {
      setStatusMessage({
        type: "error",
        text: err?.message || "Failed to start workflow execution. Please verify configuration.",
      });
    } finally {
      setExecuting(false);
    }
  }

  // Save workflow as reusable scenario
  async function handleSaveWorkflowSubmit() {
    if (!saveWorkflowTitle.trim()) return;
    setSavingWorkflow(true);
    try {
      const created = await createScenario(projectId, {
        name: saveWorkflowTitle.trim(),
        description: saveWorkflowDesc.trim() || undefined,
        tags: ["dynamic-workflow", "reusable"],
        steps: workflowSteps,
      });
      setSavedWorkflows([created, ...savedWorkflows]);
      setShowSaveModal(false);
      setStatusMessage({ type: "success", text: `Saved workflow "${created.name}" successfully.` });
    } catch (err: any) {
      setStatusMessage({ type: "error", text: `Failed to save workflow: ${err.message}` });
    } finally {
      setSavingWorkflow(false);
    }
  }

  return (
    <div className="sb-container">
      {/* =========================================================================
          1. COMPACT SAAS HEADER
      ========================================================================= */}
      <div className="sb-header">
        <div>
          <div className="sb-header-title-row">
            <h1 className="sb-header-title">Workflow Studio</h1>

            {/* Application Dropdown Selector */}
            <div style={{ position: "relative" }}>
              <button
                type="button"
                onClick={() => setShowAppSelector(!showAppSelector)}
                className="sb-app-selector-btn"
              >
                <span>{projectName}</span>
                <ChevronDown size={14} style={{ color: "var(--v-text-muted)" }} />
              </button>

              {showAppSelector && (
                <div
                  style={{
                    position: "absolute",
                    left: 0,
                    top: "100%",
                    zIndex: 40,
                    marginTop: 6,
                    width: 250,
                    background: "var(--v-surface)",
                    borderRadius: 10,
                    border: "1px solid var(--v-border)",
                    boxShadow: "0 10px 25px rgba(0,0,0,0.1)",
                    padding: 6,
                    textAlign: "left",
                  }}
                >
                  <div style={{ padding: "6px 10px", fontSize: "0.7rem", fontWeight: 700, color: "var(--v-text-muted)", textTransform: "uppercase" }}>
                    Select Application
                  </div>
                  <div style={{ maxHeight: 220, overflowY: "auto" }}>
                    {projects.map((p) => (
                      <button
                        key={p.id}
                        type="button"
                        onClick={() => {
                          if (onSelectProject) onSelectProject(p.id);
                          setShowAppSelector(false);
                        }}
                        style={{
                          width: "100%",
                          textAlign: "left",
                          padding: "8px 10px",
                          borderRadius: 6,
                          fontSize: "0.8rem",
                          border: "none",
                          cursor: "pointer",
                          display: "flex",
                          justifyContent: "space-between",
                          alignItems: "center",
                          background: p.id === projectId ? "var(--v-accent-light)" : "transparent",
                          color: p.id === projectId ? "var(--v-accent)" : "var(--v-text)",
                          fontWeight: p.id === projectId ? 700 : 500,
                        }}
                      >
                        <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{p.name}</span>
                        {p.id === projectId && <Check size={14} />}
                      </button>
                    ))}
                  </div>
                  {onNavigateToApplications && (
                    <div style={{ borderTop: "1px solid var(--v-border)", marginTop: 6, paddingTop: 6 }}>
                      <button
                        type="button"
                        onClick={() => {
                          setShowAppSelector(false);
                          onNavigateToApplications();
                        }}
                        style={{
                          width: "100%",
                          textAlign: "left",
                          padding: "6px 10px",
                          borderRadius: 6,
                          fontSize: "0.78rem",
                          fontWeight: 600,
                          color: "var(--v-accent)",
                          background: "transparent",
                          border: "none",
                          cursor: "pointer",
                        }}
                      >
                        Manage Applications &rarr;
                      </button>
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
          <p className="sb-header-subtitle">
            Build and run browser workflows using reusable actions.
          </p>
        </div>

        {/* Right Aligned Header Actions */}
        <div className="sb-header-actions">
          <button
            type="button"
            onClick={loadStandardTemplate}
            className="button button-secondary button-small"
            style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
          >
            <Sparkles size={14} style={{ color: "var(--v-accent)" }} />
            <span>Standard Flow</span>
          </button>

          <button
            type="button"
            onClick={() => void loadAppMetadata()}
            disabled={credentialsLoading}
            title="Refresh application configuration"
            className="button button-secondary button-small"
            style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", padding: "6px 10px" }}
          >
            <RefreshCw size={14} className={credentialsLoading ? "spin" : ""} />
          </button>

          {running ? (
            <button
              type="button"
              onClick={onStopRun}
              className="button button-danger button-small"
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 8,
                padding: "7px 16px",
                background: "#dc2626",
                borderColor: "#b91c1c",
                color: "#ffffff",
                fontWeight: 600,
              }}
            >
              <Square size={14} fill="currentColor" />
              <span>Stop Run</span>
            </button>
          ) : (
            <button
              type="button"
              onClick={() => void handleRunWorkflow()}
              disabled={executing || workflowSteps.length === 0}
              className="button button-primary button-small"
              style={{ display: "inline-flex", alignItems: "center", gap: 8, padding: "7px 16px" }}
            >
              {executing ? (
                <>
                  <div className="vq-spinner-sm" />
                  <span>Starting...</span>
                </>
              ) : (
                <>
                  <Play size={14} fill="currentColor" />
                  <span>Run Workflow</span>
                </>
              )}
            </button>
          )}
        </div>
      </div>

      {/* Operational Alert if Credentials are Missing */}
      {!hasVaultCredentials && !credentialsLoading && (
        <div className="alert alert-error" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", margin: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <AlertCircle size={18} />
            <span>
              No credentials configured in vault for <strong>{projectName}</strong>. The <em>Login</em> action requires credentials in the vault.
            </span>
          </div>
          {onNavigateToCredentials && (
            <button
              onClick={onNavigateToCredentials}
              style={{
                background: "transparent",
                border: "none",
                fontWeight: 700,
                color: "inherit",
                cursor: "pointer",
                textDecoration: "underline",
              }}
            >
              Configure Credentials &rarr;
            </button>
          )}
        </div>
      )}

      {/* Status Notification */}
      {statusMessage && (
        <div
          className={`alert ${statusMessage.type === "success" ? "alert-success" : "alert-error"}`}
          style={{ display: "flex", justifyContent: "space-between", alignItems: "center", margin: 0 }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            {statusMessage.type === "success" ? <Check size={18} /> : <AlertCircle size={18} />}
            <span>{statusMessage.text}</span>
          </div>
          <button
            onClick={() => setStatusMessage(null)}
            style={{ background: "transparent", border: "none", cursor: "pointer", color: "inherit" }}
          >
            <X size={16} />
          </button>
        </div>
      )}

      {/* =========================================================================
          MODE SWITCHER: WORKFLOW STEPS vs CSV DATA INPUTS
      ========================================================================= */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", borderBottom: "1px solid var(--v-border)", paddingBottom: 12, flexWrap: "wrap", gap: 12 }}>
        <div style={{ display: "flex", gap: 6, background: "var(--v-surface-2)", padding: 4, borderRadius: 8, border: "1px solid var(--v-border)" }}>
          <button
            type="button"
            onClick={() => setBuilderTab("steps")}
            style={{
              padding: "7px 16px",
              borderRadius: 6,
              border: "none",
              fontSize: "0.82rem",
              fontWeight: builderTab === "steps" ? 700 : 500,
              background: builderTab === "steps" ? "var(--v-surface)" : "transparent",
              color: builderTab === "steps" ? "var(--v-accent)" : "var(--v-text-secondary)",
              boxShadow: builderTab === "steps" ? "0 1px 3px rgba(0,0,0,0.08)" : "none",
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              gap: 7,
              transition: "all 0.15s ease",
            }}
          >
            <Layers size={15} />
            <span>Workflow Steps ({workflowSteps.length})</span>
          </button>

          <button
            type="button"
            onClick={() => setBuilderTab("csv")}
            style={{
              padding: "7px 16px",
              borderRadius: 6,
              border: "none",
              fontSize: "0.82rem",
              fontWeight: builderTab === "csv" ? 700 : 500,
              background: builderTab === "csv" ? "var(--v-surface)" : "transparent",
              color: builderTab === "csv" ? "var(--v-accent)" : "var(--v-text-secondary)",
              boxShadow: builderTab === "csv" ? "0 1px 3px rgba(0,0,0,0.08)" : "none",
              cursor: "pointer",
              display: "flex",
              alignItems: "center",
              gap: 7,
              transition: "all 0.15s ease",
            }}
          >
            <FileSpreadsheet size={15} />
            <span>CSV Data Inputs</span>
            {csvRows.length > 0 && (
              <span
                style={{
                  fontSize: "0.68rem",
                  padding: "1px 6px",
                  borderRadius: 10,
                  background: "var(--v-accent-light)",
                  color: "var(--v-accent)",
                  fontWeight: 700,
                }}
              >
                {csvRows.length} rows
              </span>
            )}
          </button>
        </div>

        {/* Dynamic Data active row selector */}
        {csvRows.length > 0 && (
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <span style={{ fontSize: "0.78rem", color: "var(--v-text-secondary)", fontWeight: 600 }}>
              Active CSV Row for Run:
            </span>
            <select
              value={activeRowIndex}
              onChange={(e) => setActiveRowIndex(parseInt(e.target.value) || 0)}
              style={{
                fontSize: "0.78rem",
                padding: "5px 10px",
                borderRadius: 6,
                border: "1px solid var(--v-border)",
                background: "var(--v-surface)",
                color: "var(--v-text)",
                fontWeight: 600,
              }}
            >
              {csvRows.map((row, idx) => (
                <option key={idx} value={idx}>
                  Row {idx + 1}: {Object.entries(row).slice(0, 2).map(([k, v]) => `${k}=${v}`).join(", ")}
                </option>
              ))}
            </select>
          </div>
        )}
      </div>

      {builderTab === "steps" && (
        <>
          {/* =========================================================================
              2. AVAILABLE ACTIONS (Responsive 4-column Grid)
          ========================================================================= */}
      <div className="sb-section">
        <div className="sb-section-header">
          <div>
            <h2 className="sb-section-title">Available actions</h2>
            <p className="sb-section-desc">Add the steps you want Veriqon to perform.</p>
          </div>
        </div>

        <div className="sb-actions-grid">
          {REUSABLE_ACTIONS.map((action) => {
            const Icon = action.icon;
            return (
              <div
                key={action.type}
                onClick={() => handleAddAction(action.type)}
                className="sb-action-card"
              >
                <div>
                  <div className="sb-action-card-top">
                    <div className="sb-action-icon-box">
                      <Icon size={18} />
                    </div>
                    <span className="sb-action-add-btn">+ Add</span>
                  </div>
                  <h3 className="sb-action-name">{action.name}</h3>
                  <p className="sb-action-desc">{action.shortDesc}</p>
                </div>
              </div>
            );
          })}
        </div>
      </div>

      {/* =========================================================================
          3. YOUR WORKFLOW (Numbered Sequential Steps)
      ========================================================================= */}
      <div className="sb-section">
        <div className="sb-section-header">
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <h2 className="sb-section-title">Your workflow</h2>
              <span className="badge" style={{ fontSize: "0.72rem", padding: "2px 8px" }}>
                {workflowSteps.length} {workflowSteps.length === 1 ? "step" : "steps"}
              </span>
            </div>
            <p className="sb-section-desc">Steps will execute sequentially from top to bottom.</p>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <button
              type="button"
              onClick={() => setShowSaveModal(true)}
              disabled={workflowSteps.length === 0}
              className="button button-secondary button-small"
              style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
            >
              <Bookmark size={13} style={{ color: "var(--v-text-muted)" }} />
              <span>Save as Workflow</span>
            </button>
            {workflowSteps.length > 0 && (
              <button
                type="button"
                onClick={() => setWorkflowSteps([])}
                className="button button-secondary button-small"
                style={{ padding: "6px 8px" }}
                title="Clear all steps"
              >
                <Trash2 size={14} style={{ color: "var(--v-error)" }} />
              </button>
            )}
          </div>
        </div>

        {/* Empty State */}
        {workflowSteps.length === 0 ? (
          <div className="sb-empty-card">
            <div
              style={{
                width: 44,
                height: 44,
                borderRadius: 10,
                background: "var(--v-surface-2)",
                display: "flex",
                alignItems: "center",
                justifyContent: "center",
                color: "var(--v-text-muted)",
                marginBottom: 12,
              }}
            >
              <Layers size={22} />
            </div>
            <h3 style={{ margin: 0, fontSize: "0.9rem", fontWeight: 700, color: "var(--v-text)" }}>
              Your workflow has no steps yet
            </h3>
            <p style={{ margin: "4px 0 16px 0", fontSize: "0.8rem", color: "var(--v-text-secondary)", maxWidth: 360 }}>
              Select any action from the library above to add a step, or load the standard starter sequence.
            </p>
            <div style={{ display: "flex", gap: 10 }}>
              <button
                type="button"
                onClick={loadStandardTemplate}
                className="button button-primary button-small"
                style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
              >
                <Sparkles size={14} />
                <span>Load Standard Flow</span>
              </button>
              <button
                type="button"
                onClick={() => handleAddAction("open_app")}
                className="button button-secondary button-small"
                style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
              >
                <Plus size={14} />
                <span>Add First Action</span>
              </button>
            </div>
          </div>
        ) : (
          <div className="sb-workflow-list">
            {workflowSteps.map((step, idx) => {
              const actionDef = REUSABLE_ACTIONS.find((a) => a.type === step.action_type) || {
                name: step.action_type,
                shortDesc: "",
                icon: FileCode,
              };
              const Icon = actionDef.icon;
              const isFirst = idx === 0;
              const isLast = idx === workflowSteps.length - 1;

              return (
                <div
                  key={idx}
                  className={`sb-step-card ${!step.is_enabled ? "disabled" : ""}`}
                >
                  {/* Left: Step Number, Icon, Title, and Concise Summary */}
                  <div className="sb-step-left">
                    <span className="sb-step-num">{idx + 1}</span>

                    <div className="sb-step-icon">
                      <Icon size={16} />
                    </div>

                    <div className="sb-step-content">
                      <div className="sb-step-title-row">
                        <span className="sb-step-title">
                          {step.description || actionDef.name}
                        </span>
                        <span className="sb-step-tag">
                          {step.action_type}
                        </span>
                      </div>

                      {/* Concise Config Summary */}
                      <div className="sb-step-summary">
                        {step.action_type === "open_app" && (
                          <span>
                            Opens application base URL {step.action_params?.path ? `(${step.action_params.path})` : ""}
                          </span>
                        )}
                        {step.action_type === "login" && (
                          <span style={{ color: "var(--v-success-text)", fontWeight: 600 }}>
                            Auto-authenticates with saved vault credentials
                          </span>
                        )}
                        {step.action_type === "navigate" && (
                          <span>Destination: {step.action_params?.path || step.locator_value || "/"}</span>
                        )}
                        {step.action_type === "fill_input" && (
                          <span>
                            Field: <strong style={{ color: "var(--v-text)" }}>{step.locator_value || "unspecified"}</strong> &bull; Value: "{step.action_params?.value || ""}"
                          </span>
                        )}
                        {step.action_type === "click_element" && (
                          <span>
                            Target: <strong style={{ color: "var(--v-text)" }}>{step.locator_value || "unspecified"}</strong>
                          </span>
                        )}
                        {step.action_type === "select_option" && (
                          <span>
                            Dropdown: {step.locator_value} &bull; Option: "{step.action_params?.value || ""}"
                          </span>
                        )}
                        {step.action_type === "verify_element" && (
                          <span>
                            Verify: <strong style={{ color: "var(--v-text)" }}>{step.action_params?.verify_type || "visible"}</strong>
                            {step.action_params?.expected && ` "${step.action_params.expected}"`}
                          </span>
                        )}
                        {step.action_type === "wait_for_element" && (
                          <span>
                            Condition: {step.action_params?.condition === "duration" ? `${step.action_params?.duration_ms || 1000}ms` : step.action_params?.condition || "visible"}
                          </span>
                        )}
                      </div>
                    </div>
                  </div>

                  {/* Right: Step Controls (Consistent Alignment) */}
                  <div className="sb-step-controls">
                    <button
                      type="button"
                      onClick={() => handleToggleEnable(idx)}
                      title={step.is_enabled ? "Disable step" : "Enable step"}
                      className="sb-icon-btn"
                    >
                      {step.is_enabled ? <Eye size={15} /> : <EyeOff size={15} style={{ color: "var(--v-warning)" }} />}
                    </button>
                    <button
                      type="button"
                      onClick={() => handleMoveStep(idx, "up")}
                      disabled={isFirst}
                      title="Move up"
                      className="sb-icon-btn"
                    >
                      <ArrowUp size={15} />
                    </button>
                    <button
                      type="button"
                      onClick={() => handleMoveStep(idx, "down")}
                      disabled={isLast}
                      title="Move down"
                      className="sb-icon-btn"
                    >
                      <ArrowDown size={15} />
                    </button>
                    <button
                      type="button"
                      onClick={() => handleDuplicateStep(idx)}
                      title="Duplicate step"
                      className="sb-icon-btn"
                    >
                      <Copy size={15} />
                    </button>
                    <button
                      type="button"
                      onClick={() => handleEditStep(idx)}
                      title="Edit step"
                      className="sb-icon-btn"
                      style={{ color: "var(--v-accent)" }}
                    >
                      <Pencil size={15} />
                    </button>
                    <button
                      type="button"
                      onClick={() => handleRemoveStep(idx)}
                      title="Delete step"
                      className="sb-icon-btn danger"
                    >
                      <Trash2 size={15} />
                    </button>
                  </div>
                </div>
              );
            })}
          </div>
        )}

        {/* Saved Workflows Accordion/Selector if Any Exist */}
        {savedWorkflows.length > 0 && (
          <div style={{ paddingTop: 14, borderTop: "1px solid var(--v-border)" }}>
            <details style={{ background: "var(--v-surface)", border: "1px solid var(--v-border)", borderRadius: 10, padding: 12 }}>
              <summary style={{ fontSize: "0.82rem", fontWeight: 700, color: "var(--v-text)", cursor: "pointer", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                <span style={{ display: "inline-flex", alignItems: "center", gap: 6 }}>
                  <Bookmark size={14} style={{ color: "var(--v-accent)" }} />
                  Saved Reusable Workflows ({savedWorkflows.length})
                </span>
                <ChevronDown size={14} style={{ color: "var(--v-text-muted)" }} />
              </summary>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))", gap: 10, marginTop: 12 }}>
                {savedWorkflows.map((scen) => (
                  <div
                    key={scen.id}
                    onClick={() => loadSavedWorkflow(scen)}
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      padding: "8px 12px",
                      borderRadius: 8,
                      border: "1px solid var(--v-border)",
                      background: "var(--v-surface)",
                      cursor: "pointer",
                      transition: "all 0.15s ease",
                    }}
                  >
                    <div>
                      <div style={{ fontSize: "0.8rem", fontWeight: 700, color: "var(--v-text)" }}>{scen.name}</div>
                      <div style={{ fontSize: "0.7rem", color: "var(--v-text-muted)" }}>{scen.steps?.length || 0} steps</div>
                    </div>
                    <span style={{ fontSize: "0.75rem", fontWeight: 700, color: "var(--v-accent)" }}>Load &rarr;</span>
                  </div>
                ))}
              </div>
            </details>
          </div>
        )}
      </div>
      </>
      )}

      {/* =========================================================================
          CSV DATA INPUTS PANEL (Interactive Data Table & Parameters)
      ========================================================================= */}
      {builderTab === "csv" && (
        <div className="sb-section" style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          {/* Header & Controls */}
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 12 }}>
            <div>
              <h2 className="sb-section-title" style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <FileSpreadsheet size={20} style={{ color: "var(--v-accent)" }} />
                CSV Data-Driven Parameters
              </h2>
              <p className="sb-section-desc">
                Provide test input values using CSV columns. In any action step, reference variables using <code>{"{{ColumnName}}"}</code> (e.g. <code>{"{{Hours}}"}</code>).
              </p>
            </div>

            <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
              {/* Hidden file input */}
              <input
                id="csv-file-upload"
                type="file"
                accept=".csv"
                style={{ display: "none" }}
                onChange={handleCsvFileUpload}
              />
              <button
                type="button"
                className="button button-secondary button-small"
                onClick={() => document.getElementById("csv-file-upload")?.click()}
                style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
              >
                <Upload size={14} />
                Upload CSV
              </button>

              <button
                type="button"
                className="button button-secondary button-small"
                onClick={handleLoadSampleCsv}
                style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
              >
                <Sparkles size={14} style={{ color: "var(--v-accent)" }} />
                Sample Data
              </button>

              <button
                type="button"
                className="button button-secondary button-small"
                onClick={handleAddCsvColumn}
                style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
              >
                <Plus size={14} />
                Add Column
              </button>

              <button
                type="button"
                className="button button-secondary button-small"
                onClick={handleAddCsvRow}
                style={{ display: "inline-flex", alignItems: "center", gap: 6 }}
              >
                <Plus size={14} />
                Add Row
              </button>

              {csvRows.length > 0 && (
                <button
                  type="button"
                  className="button button-secondary button-small"
                  onClick={handleClearCsv}
                  title="Clear all CSV data"
                  style={{ color: "#ef4444" }}
                >
                  <Trash2 size={14} />
                </button>
              )}
            </div>
          </div>

          {/* Quick Variable Copy Pill Bar */}
          {csvColumns.length > 0 && (
            <div style={{ background: "var(--v-surface-2)", borderRadius: 10, padding: 12, border: "1px solid var(--v-border)" }}>
              <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8 }}>
                <span style={{ fontSize: "0.75rem", fontWeight: 700, color: "var(--v-text-secondary)", textTransform: "uppercase", letterSpacing: "0.04em" }}>
                  Available Action Input Variables (Click to copy)
                </span>
                {copiedVarName && (
                  <span style={{ fontSize: "0.74rem", color: "var(--v-success)", fontWeight: 600 }}>
                    Copied {`{{${copiedVarName}}}`} to clipboard!
                  </span>
                )}
              </div>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
                {csvColumns.map((col) => (
                  <button
                    key={col}
                    type="button"
                    onClick={() => {
                      navigator.clipboard.writeText(`{{${col}}}`);
                      setCopiedVarName(col);
                      setTimeout(() => setCopiedVarName(null), 2000);
                    }}
                    style={{
                      display: "inline-flex",
                      alignItems: "center",
                      gap: 6,
                      background: "var(--v-surface)",
                      border: "1px solid rgba(99, 102, 241, 0.3)",
                      borderRadius: 6,
                      padding: "4px 10px",
                      fontSize: "0.75rem",
                      fontWeight: 600,
                      color: "var(--v-accent)",
                      cursor: "pointer",
                      boxShadow: "0 1px 2px rgba(0,0,0,0.04)",
                    }}
                  >
                    <span>{`{{${col}}}`}</span>
                    <span style={{ fontSize: "0.7rem", color: "var(--v-text-muted)" }}>
                      = "{csvRows[activeRowIndex]?.[col] || ""}"
                    </span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Table */}
          {csvRows.length === 0 ? (
            <div style={{ padding: 48, textAlign: "center", background: "var(--v-surface)", borderRadius: 10, border: "1px dashed var(--v-border)" }}>
              <FileSpreadsheet size={36} style={{ color: "var(--v-text-muted)", margin: "0 auto 12px" }} />
              <h3 style={{ fontSize: "0.95rem", fontWeight: 700, margin: "0 0 6px 0", color: "var(--v-text)" }}>
                No CSV Data Loaded Yet
              </h3>
              <p style={{ fontSize: "0.82rem", color: "var(--v-text-secondary)", maxWidth: 460, margin: "0 auto 16px" }}>
                Upload a CSV file or load sample timesheet data to dynamically provide input values into your workflow actions.
              </p>
              <div style={{ display: "flex", gap: 10, justifyContent: "center" }}>
                <button
                  type="button"
                  className="button button-primary button-small"
                  onClick={handleLoadSampleCsv}
                >
                  <Sparkles size={14} />
                  Load Sample Timesheet Data
                </button>
                <button
                  type="button"
                  className="button button-secondary button-small"
                  onClick={() => document.getElementById("csv-file-upload")?.click()}
                >
                  <Upload size={14} />
                  Upload CSV File
                </button>
              </div>
            </div>
          ) : (
            <div style={{ overflowX: "auto", border: "1px solid var(--v-border)", borderRadius: 10, background: "var(--v-surface)" }}>
              <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.82rem" }}>
                <thead>
                  <tr style={{ background: "var(--v-surface-2)", borderBottom: "1px solid var(--v-border)" }}>
                    <th style={{ padding: "10px 12px", width: 60, textAlign: "center", fontWeight: 700, color: "var(--v-text-secondary)" }}>
                      Active
                    </th>
                    <th style={{ padding: "10px 12px", width: 45, fontWeight: 700, color: "var(--v-text-secondary)" }}>
                      #
                    </th>
                    {csvColumns.map((col) => (
                      <th key={col} style={{ padding: "10px 12px", textAlign: "left", fontWeight: 700, color: "var(--v-text)" }}>
                        {col}
                      </th>
                    ))}
                    <th style={{ padding: "10px 12px", width: 50, textAlign: "center" }}></th>
                  </tr>
                </thead>
                <tbody>
                  {csvRows.map((row, rIdx) => (
                    <tr
                      key={rIdx}
                      style={{
                        borderBottom: "1px solid var(--v-border)",
                        background: activeRowIndex === rIdx ? "rgba(99, 102, 241, 0.05)" : "transparent",
                      }}
                    >
                      <td style={{ padding: "8px 12px", textAlign: "center" }}>
                        <input
                          type="radio"
                          name="activeCsvRow"
                          checked={activeRowIndex === rIdx}
                          onChange={() => setActiveRowIndex(rIdx)}
                          title="Select this row as the active input dataset"
                          style={{ cursor: "pointer" }}
                        />
                      </td>
                      <td style={{ padding: "8px 12px", color: "var(--v-text-muted)", fontWeight: 600 }}>
                        {rIdx + 1}
                      </td>
                      {csvColumns.map((col) => (
                        <td key={col} style={{ padding: "6px 12px" }}>
                          <input
                            type="text"
                            value={row[col] ?? ""}
                            onChange={(e) => handleCsvCellChange(rIdx, col, e.target.value)}
                            className="sb-input"
                            style={{ height: 32, padding: "4px 8px", fontSize: "0.8rem" }}
                          />
                        </td>
                      ))}
                      <td style={{ padding: "8px 12px", textAlign: "center" }}>
                        <button
                          type="button"
                          onClick={() => handleRemoveCsvRow(rIdx)}
                          style={{ background: "transparent", border: "none", color: "var(--v-text-muted)", cursor: "pointer", padding: 4 }}
                          title="Delete this row"
                        >
                          <Trash2 size={14} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* =========================================================================
          4. ACTION CONFIGURATION MODAL (Only asks necessary questions)
      ========================================================================= */}
      {stepModalOpen && (
        <div className="sb-modal-backdrop">
          <div className="sb-modal-card">
            {/* Modal Header */}
            <div className="sb-modal-header">
              <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                <div
                  style={{
                    width: 38,
                    height: 38,
                    borderRadius: 8,
                    background: "var(--v-accent-light)",
                    color: "var(--v-accent)",
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    flexShrink: 0,
                  }}
                >
                  {React.createElement(
                    REUSABLE_ACTIONS.find((a) => a.type === modalStepData.action_type)?.icon || FileCode,
                    { size: 18 }
                  )}
                </div>
                <div>
                  <h3 style={{ margin: 0, fontSize: "0.95rem", fontWeight: 700, color: "var(--v-text)" }}>
                    {editingStepIndex !== null ? "Edit Action" : "Add Action"}:{" "}
                    {REUSABLE_ACTIONS.find((a) => a.type === modalStepData.action_type)?.name ||
                      modalStepData.action_type}
                  </h3>
                  <p style={{ margin: "2px 0 0 0", fontSize: "0.75rem", color: "var(--v-text-secondary)" }}>
                    {REUSABLE_ACTIONS.find((a) => a.type === modalStepData.action_type)?.shortDesc}
                  </p>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setStepModalOpen(false)}
                className="sb-icon-btn"
              >
                <X size={16} />
              </button>
            </div>

            {/* Modal Body: Action-Specific Form Fields */}
            <div style={{ display: "flex", flexDirection: "column", gap: 14, maxHeight: "60vh", overflowY: "auto", paddingRight: 4 }}>
              {/* Step Description */}
              <div>
                <label className="sb-label">Step Description</label>
                <input
                  type="text"
                  value={modalStepData.description || ""}
                  onChange={(e) => setModalStepData({ ...modalStepData, description: e.target.value })}
                  placeholder="e.g. Enter timesheet hours and save"
                  className="sb-input"
                />
              </div>

              {/* ACTION 1: Open Application */}
              {modalStepData.action_type === "open_app" && (
                <div style={{ background: "var(--v-surface-2)", borderRadius: 10, padding: 14, border: "1px solid var(--v-border)", display: "flex", flexDirection: "column", gap: 12 }}>
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
                    <div>
                      <div style={{ fontSize: "0.82rem", fontWeight: 700, color: "var(--v-text)" }}>
                        Target Application
                      </div>
                      <div style={{ fontSize: "0.76rem", color: "var(--v-text-secondary)", marginTop: 2 }}>
                        {projectName} ({effectiveBaseUrl || "No URL configured"})
                      </div>
                    </div>
                    <button
                      type="button"
                      className="sb-picker-btn"
                      onClick={() => {
                        setCurrentPickingTarget("main");
                        setElementPickerOpen(true);
                      }}
                      title="Open interactive page inspector"
                    >
                      <Sparkles size={14} />
                      Inspect Page
                    </button>
                  </div>

                  <div>
                    <label className="sb-label">Relative Path Override (Optional)</label>
                    <input
                      type="text"
                      value={modalStepData.action_params?.path || ""}
                      onChange={(e) =>
                        setModalStepData({
                          ...modalStepData,
                          action_params: { ...modalStepData.action_params, path: e.target.value },
                        })
                      }
                      placeholder="/dashboard or /login (leave empty for base URL)"
                      className="sb-input"
                      style={{ fontFamily: "monospace" }}
                    />
                  </div>
                </div>
              )}

              {/* ACTION 2: Login */}
              {modalStepData.action_type === "login" && (
                <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                  <div style={{ background: "var(--v-success-bg)", border: "1px solid var(--v-success-border)", borderRadius: 10, padding: 12, fontSize: "0.8rem", color: "var(--v-success-text)", lineHeight: 1.4 }}>
                    Veriqon automatically retrieves and injects the credentials saved in the vault for{" "}
                    <strong>{projectName}</strong>. Passwords remain encrypted and are never exposed.
                  </div>

                  {/* Form Field Target Locators with pickers */}
                  <div style={{ background: "var(--v-surface-2)", borderRadius: 10, padding: 12, border: "1px solid var(--v-border)", display: "flex", flexDirection: "column", gap: 10 }}>
                    <div style={{ fontSize: "0.78rem", fontWeight: 700, color: "var(--v-text)" }}>
                      Login Form Elements (Auto-detected or Pick from Page)
                    </div>

                    {/* Username Field */}
                    <div>
                      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 4 }}>
                        <label className="sb-label" style={{ margin: 0 }}>Username Field</label>
                        <button
                          type="button"
                          className="sb-picker-btn-mini"
                          onClick={() => {
                            setCurrentPickingTarget("username");
                            setElementPickerOpen(true);
                          }}
                        >
                          <MousePointer size={12} />
                          {modalStepData.action_params?.username_locator ? "Re-pick" : "Inspect & Pick"}
                        </button>
                      </div>
                      <input
                        type="text"
                        value={modalStepData.action_params?.username_locator || ""}
                        onChange={(e) =>
                          setModalStepData({
                            ...modalStepData,
                            action_params: { ...modalStepData.action_params, username_locator: e.target.value },
                          })
                        }
                        placeholder="Auto-detected (e.g. textbox:Username, #username)"
                        className="sb-input"
                        style={{ fontFamily: "monospace" }}
                      />
                    </div>

                    {/* Password Field */}
                    <div>
                      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 4 }}>
                        <label className="sb-label" style={{ margin: 0 }}>Password Field</label>
                        <button
                          type="button"
                          className="sb-picker-btn-mini"
                          onClick={() => {
                            setCurrentPickingTarget("password");
                            setElementPickerOpen(true);
                          }}
                        >
                          <MousePointer size={12} />
                          {modalStepData.action_params?.password_locator ? "Re-pick" : "Inspect & Pick"}
                        </button>
                      </div>
                      <input
                        type="text"
                        value={modalStepData.action_params?.password_locator || ""}
                        onChange={(e) =>
                          setModalStepData({
                            ...modalStepData,
                            action_params: { ...modalStepData.action_params, password_locator: e.target.value },
                          })
                        }
                        placeholder="Auto-detected (e.g. textbox:Password, #password)"
                        className="sb-input"
                        style={{ fontFamily: "monospace" }}
                      />
                    </div>

                    {/* Submit Button */}
                    <div>
                      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 4 }}>
                        <label className="sb-label" style={{ margin: 0 }}>Submit Button</label>
                        <button
                          type="button"
                          className="sb-picker-btn-mini"
                          onClick={() => {
                            setCurrentPickingTarget("submit");
                            setElementPickerOpen(true);
                          }}
                        >
                          <MousePointer size={12} />
                          {modalStepData.action_params?.submit_locator ? "Re-pick" : "Inspect & Pick"}
                        </button>
                      </div>
                      <input
                        type="text"
                        value={modalStepData.action_params?.submit_locator || ""}
                        onChange={(e) =>
                          setModalStepData({
                            ...modalStepData,
                            action_params: { ...modalStepData.action_params, submit_locator: e.target.value },
                          })
                        }
                        placeholder="Auto-detected (e.g. button:Sign In, button[type=submit])"
                        className="sb-input"
                        style={{ fontFamily: "monospace" }}
                      />
                    </div>
                  </div>
                </div>
              )}

              {/* ACTION 3: Navigate */}
              {modalStepData.action_type === "navigate" && (
                <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                  <div className="sb-nav-tabs">
                    <button
                      type="button"
                      className={`sb-nav-tab ${navigateMethod === "menu" ? "sb-nav-tab-active" : ""}`}
                      onClick={() => {
                        setNavigateMethod("menu");
                        setModalStepData({
                          ...modalStepData,
                          action_params: { ...modalStepData.action_params, method: "click" },
                        });
                      }}
                    >
                      <Compass size={14} style={{ display: "inline", marginRight: 6, verticalAlign: "middle" }} />
                      Select Link or Menu Item
                    </button>
                    <button
                      type="button"
                      className={`sb-nav-tab ${navigateMethod === "url" ? "sb-nav-tab-active" : ""}`}
                      onClick={() => {
                        setNavigateMethod("url");
                        setModalStepData({
                          ...modalStepData,
                          action_params: { ...modalStepData.action_params, method: "path" },
                        });
                      }}
                    >
                      <Globe size={14} style={{ display: "inline", marginRight: 6, verticalAlign: "middle" }} />
                      Direct URL Route
                    </button>
                  </div>

                  {navigateMethod === "menu" ? (
                    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                      {modalStepData.locator_value ? (
                        <div className="sb-picked-card">
                          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                            <div
                              style={{
                                width: 32,
                                height: 32,
                                borderRadius: 6,
                                background: "rgba(16, 185, 129, 0.15)",
                                color: "var(--v-success)",
                                display: "flex",
                                alignItems: "center",
                                justifyContent: "center",
                              }}
                            >
                              <Check size={16} />
                            </div>
                            <div>
                              <div style={{ fontSize: "0.82rem", fontWeight: 700, color: "var(--v-text)" }}>
                                {modalStepData.action_params?.element_friendly_name || modalStepData.locator_value}
                              </div>
                              <div style={{ fontSize: "0.72rem", color: "var(--v-text-secondary)", fontFamily: "monospace" }}>
                                {modalStepData.locator_type || "smart"}: {modalStepData.locator_value}
                              </div>
                            </div>
                          </div>
                          <button
                            type="button"
                            className="sb-picker-btn-mini"
                            onClick={() => {
                              setCurrentPickingTarget("main");
                              setElementPickerOpen(true);
                            }}
                          >
                            Pick Different Menu
                          </button>
                        </div>
                      ) : (
                        <button
                          type="button"
                          className="sb-picker-btn"
                          style={{ justifyContent: "center", padding: "10px 16px" }}
                          onClick={() => {
                            setCurrentPickingTarget("main");
                            setElementPickerOpen(true);
                          }}
                        >
                          <Sparkles size={16} />
                          Inspect & Pick Menu / Link from Page
                        </button>
                      )}

                      <div>
                        <label className="sb-label">Visible Menu or Link Name <b>*</b></label>
                        <input
                          type="text"
                          required
                          value={modalStepData.locator_value || ""}
                          onChange={(e) =>
                            setModalStepData({
                              ...modalStepData,
                              locator_value: e.target.value,
                              action_params: { ...modalStepData.action_params, method: "click", path: e.target.value },
                            })
                          }
                          placeholder='e.g. "My Timesheet", "Dashboard", "Projects"'
                          className="sb-input"
                        />
                        <small style={{ display: "block", marginTop: 4, fontSize: "0.74rem", color: "var(--v-text-secondary)" }}>
                          Enter the visible text of the menu or link to click.
                        </small>
                      </div>
                    </div>
                  ) : (
                    <div>
                      <label className="sb-label">URL Path or Full URL <b>*</b></label>
                      <input
                        type="text"
                        required
                        value={modalStepData.action_params?.path || modalStepData.locator_value || ""}
                        onChange={(e) =>
                          setModalStepData({
                            ...modalStepData,
                            locator_value: e.target.value,
                            action_params: { ...modalStepData.action_params, method: "path", path: e.target.value },
                          })
                        }
                        placeholder="e.g. /dashboard, /timesheet, or https://example.com/page"
                        className="sb-input"
                        style={{ fontFamily: "monospace" }}
                      />
                      <small style={{ display: "block", marginTop: 4, fontSize: "0.74rem", color: "var(--v-text-secondary)" }}>
                        Relative routes will navigate relative to the application's base URL.
                      </small>
                    </div>
                  )}
                </div>
              )}

              {/* ACTION 4: Fill Input */}
              {modalStepData.action_type === "fill_input" && (
                <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                  {modalStepData.locator_value ? (
                    <div className="sb-picked-card">
                      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                        <div
                          style={{
                            width: 32,
                            height: 32,
                            borderRadius: 6,
                            background: "rgba(16, 185, 129, 0.15)",
                            color: "var(--v-success)",
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                          }}
                        >
                          <Check size={16} />
                        </div>
                        <div>
                          <div style={{ fontSize: "0.82rem", fontWeight: 700, color: "var(--v-text)" }}>
                            {modalStepData.action_params?.element_friendly_name || modalStepData.locator_value}
                          </div>
                          <div style={{ fontSize: "0.72rem", color: "var(--v-text-secondary)", fontFamily: "monospace" }}>
                            {modalStepData.locator_type || "smart"}: {modalStepData.locator_value}
                          </div>
                        </div>
                      </div>
                      <button
                        type="button"
                        className="sb-picker-btn-mini"
                        onClick={() => {
                          setCurrentPickingTarget("main");
                          setElementPickerOpen(true);
                        }}
                      >
                        Pick Different Field
                      </button>
                    </div>
                  ) : (
                    <button
                      type="button"
                      className="sb-picker-btn"
                      style={{ justifyContent: "center", padding: "10px 16px" }}
                      onClick={() => {
                        setCurrentPickingTarget("main");
                        setElementPickerOpen(true);
                      }}
                    >
                      <Sparkles size={16} />
                      Inspect & Pick Input Field from Page
                    </button>
                  )}

                  <div>
                    <label className="sb-label">Target Field Name or Selector <b>*</b></label>
                    <input
                      type="text"
                      required
                      value={modalStepData.locator_value || ""}
                      onChange={(e) => setModalStepData({ ...modalStepData, locator_value: e.target.value })}
                      placeholder='e.g. "Hours Worked", "Task Name", "Email"'
                      className="sb-input"
                    />
                  </div>

                  <div>
                    <label className="sb-label">Value to Enter <b>*</b></label>
                    <input
                      type="text"
                      required
                      value={modalStepData.action_params?.value ?? ""}
                      onChange={(e) =>
                        setModalStepData({
                          ...modalStepData,
                          action_params: { ...modalStepData.action_params, value: e.target.value },
                        })
                      }
                      placeholder='e.g. "8.0", "Development", or "2026-10-23"'
                      className="sb-input"
                    />
                  </div>

                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <input
                      type="checkbox"
                      id="clear_first"
                      checked={modalStepData.action_params?.clear_first !== false}
                      onChange={(e) =>
                        setModalStepData({
                          ...modalStepData,
                          action_params: { ...modalStepData.action_params, clear_first: e.target.checked },
                        })
                      }
                    />
                    <label htmlFor="clear_first" style={{ fontSize: "0.78rem", color: "var(--v-text-secondary)", cursor: "pointer" }}>
                      Clear existing field value before typing
                    </label>
                  </div>
                </div>
              )}

              {/* ACTION 5: Click Element */}
              {modalStepData.action_type === "click_element" && (
                <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                  {modalStepData.locator_value ? (
                    <div className="sb-picked-card">
                      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                        <div
                          style={{
                            width: 32,
                            height: 32,
                            borderRadius: 6,
                            background: "rgba(16, 185, 129, 0.15)",
                            color: "var(--v-success)",
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                          }}
                        >
                          <Check size={16} />
                        </div>
                        <div>
                          <div style={{ fontSize: "0.82rem", fontWeight: 700, color: "var(--v-text)" }}>
                            {modalStepData.action_params?.element_friendly_name || modalStepData.locator_value}
                          </div>
                          <div style={{ fontSize: "0.72rem", color: "var(--v-text-secondary)", fontFamily: "monospace" }}>
                            {modalStepData.locator_type || "smart"}: {modalStepData.locator_value}
                          </div>
                        </div>
                      </div>
                      <button
                        type="button"
                        className="sb-picker-btn-mini"
                        onClick={() => {
                          setCurrentPickingTarget("main");
                          setElementPickerOpen(true);
                        }}
                      >
                        Pick Different Button
                      </button>
                    </div>
                  ) : (
                    <button
                      type="button"
                      className="sb-picker-btn"
                      style={{ justifyContent: "center", padding: "10px 16px" }}
                      onClick={() => {
                        setCurrentPickingTarget("main");
                        setElementPickerOpen(true);
                      }}
                    >
                      <Sparkles size={16} />
                      Inspect & Pick Button from Page
                    </button>
                  )}

                  <div>
                    <label className="sb-label">Button or Element Name <b>*</b></label>
                    <input
                      type="text"
                      required
                      value={modalStepData.locator_value || ""}
                      onChange={(e) => setModalStepData({ ...modalStepData, locator_value: e.target.value })}
                      placeholder='e.g. "Save", "Submit", "Sign In", "Apply"'
                      className="sb-input"
                    />
                  </div>

                  <div>
                    <label className="sb-label">Click Type</label>
                    <select
                      value={modalStepData.action_params?.click_type || "click"}
                      onChange={(e) =>
                        setModalStepData({
                          ...modalStepData,
                          action_params: { ...modalStepData.action_params, click_type: e.target.value },
                        })
                      }
                      className="sb-input"
                    >
                      <option value="click">Single Click</option>
                      <option value="double">Double Click</option>
                    </select>
                  </div>
                </div>
              )}

              {/* ACTION 6: Select Option */}
              {modalStepData.action_type === "select_option" && (
                <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                  {modalStepData.locator_value ? (
                    <div className="sb-picked-card">
                      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                        <div
                          style={{
                            width: 32,
                            height: 32,
                            borderRadius: 6,
                            background: "rgba(16, 185, 129, 0.15)",
                            color: "var(--v-success)",
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                          }}
                        >
                          <Check size={16} />
                        </div>
                        <div>
                          <div style={{ fontSize: "0.82rem", fontWeight: 700, color: "var(--v-text)" }}>
                            {modalStepData.action_params?.element_friendly_name || modalStepData.locator_value}
                          </div>
                          <div style={{ fontSize: "0.72rem", color: "var(--v-text-secondary)", fontFamily: "monospace" }}>
                            {modalStepData.locator_type || "smart"}: {modalStepData.locator_value}
                          </div>
                        </div>
                      </div>
                      <button
                        type="button"
                        className="sb-picker-btn-mini"
                        onClick={() => {
                          setCurrentPickingTarget("main");
                          setElementPickerOpen(true);
                        }}
                      >
                        Pick Different Dropdown
                      </button>
                    </div>
                  ) : (
                    <button
                      type="button"
                      className="sb-picker-btn"
                      style={{ justifyContent: "center", padding: "10px 16px" }}
                      onClick={() => {
                        setCurrentPickingTarget("main");
                        setElementPickerOpen(true);
                      }}
                    >
                      <Sparkles size={16} />
                      Inspect & Pick Dropdown from Page
                    </button>
                  )}

                  <div>
                    <label className="sb-label">Dropdown Field Name or Selector <b>*</b></label>
                    <input
                      type="text"
                      required
                      value={modalStepData.locator_value || ""}
                      onChange={(e) => setModalStepData({ ...modalStepData, locator_value: e.target.value })}
                      placeholder='e.g. "Department", "Status", or "select#project"'
                      className="sb-input"
                    />
                  </div>

                  <div>
                    <label className="sb-label">Option to Select <b>*</b></label>
                    {modalStepData.action_params?.available_options && modalStepData.action_params.available_options.length > 0 ? (
                      <select
                        value={modalStepData.action_params?.value || ""}
                        onChange={(e) =>
                          setModalStepData({
                            ...modalStepData,
                            action_params: { ...modalStepData.action_params, value: e.target.value },
                          })
                        }
                        className="sb-input"
                      >
                        <option value="">-- Choose Option from Inspected Dropdown --</option>
                        {modalStepData.action_params.available_options.map((opt: any, idx: number) => {
                          const val = typeof opt === "object" ? opt.value || opt.label : opt;
                          const lab = typeof opt === "object" ? opt.label || opt.value : opt;
                          return (
                            <option key={idx} value={val}>
                              {lab}
                            </option>
                          );
                        })}
                      </select>
                    ) : (
                      <input
                        type="text"
                        required
                        value={modalStepData.action_params?.value || modalStepData.action_params?.label || ""}
                        onChange={(e) =>
                          setModalStepData({
                            ...modalStepData,
                            action_params: { ...modalStepData.action_params, value: e.target.value },
                          })
                        }
                        placeholder='e.g. "Approved", "Engineering", or "101"'
                        className="sb-input"
                      />
                    )}
                  </div>
                </div>
              )}

              {/* ACTION 7: Verify Element */}
              {modalStepData.action_type === "verify_element" && (
                <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                  <div>
                    <label className="sb-label">Verification Assertion Type</label>
                    <select
                      value={modalStepData.action_params?.verify_type || "visible"}
                      onChange={(e) =>
                        setModalStepData({
                          ...modalStepData,
                          action_params: { ...modalStepData.action_params, verify_type: e.target.value },
                        })
                      }
                      className="sb-input"
                    >
                      <option value="visible">Verify Element is Visible</option>
                      <option value="hidden">Verify Element is Hidden</option>
                      <option value="contains_text">Verify Element Contains Text</option>
                      <option value="exact_text">Verify Element Exact Text</option>
                      <option value="input_value">Verify Field Input Value</option>
                      <option value="url_contains">Verify Page URL Contains Substring</option>
                      <option value="page_title">Verify Page Title Contains Substring</option>
                    </select>
                  </div>

                  {modalStepData.action_params?.verify_type !== "url_contains" &&
                    modalStepData.action_params?.verify_type !== "page_title" && (
                      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                        {modalStepData.locator_value ? (
                          <div className="sb-picked-card">
                            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                              <div
                                style={{
                                  width: 32,
                                  height: 32,
                                  borderRadius: 6,
                                  background: "rgba(16, 185, 129, 0.15)",
                                  color: "var(--v-success)",
                                  display: "flex",
                                  alignItems: "center",
                                  justifyContent: "center",
                                }}
                              >
                                <Check size={16} />
                              </div>
                              <div>
                                <div style={{ fontSize: "0.82rem", fontWeight: 700, color: "var(--v-text)" }}>
                                  {modalStepData.action_params?.element_friendly_name || modalStepData.locator_value}
                                </div>
                                <div style={{ fontSize: "0.72rem", color: "var(--v-text-secondary)", fontFamily: "monospace" }}>
                                  {modalStepData.locator_type || "smart"}: {modalStepData.locator_value}
                                </div>
                              </div>
                            </div>
                            <button
                              type="button"
                              className="sb-picker-btn-mini"
                              onClick={() => {
                                setCurrentPickingTarget("main");
                                setElementPickerOpen(true);
                              }}
                            >
                              Pick Different Element
                            </button>
                          </div>
                        ) : (
                          <button
                            type="button"
                            className="sb-picker-btn"
                            style={{ justifyContent: "center", padding: "10px 16px" }}
                            onClick={() => {
                              setCurrentPickingTarget("main");
                              setElementPickerOpen(true);
                            }}
                          >
                            <Sparkles size={16} />
                            Inspect & Pick Target Element from Page
                          </button>
                        )}

                        <div>
                          <label className="sb-label">Target Element Locator <b>*</b></label>
                          <input
                            type="text"
                            value={modalStepData.locator_value || ""}
                            onChange={(e) => setModalStepData({ ...modalStepData, locator_value: e.target.value })}
                            placeholder='e.g. "Success Message", ".alert-success", or "#status-badge"'
                            className="sb-input"
                          />
                        </div>
                      </div>
                    )}

                  {modalStepData.action_params?.verify_type !== "visible" &&
                    modalStepData.action_params?.verify_type !== "hidden" && (
                      <div>
                        <label className="sb-label">Expected Value / Text <b>*</b></label>
                        <input
                          type="text"
                          required
                          value={modalStepData.action_params?.expected || ""}
                          onChange={(e) =>
                            setModalStepData({
                              ...modalStepData,
                              action_params: { ...modalStepData.action_params, expected: e.target.value },
                            })
                          }
                          placeholder='e.g. "Saved successfully", "Dashboard", or "8.0"'
                          className="sb-input"
                        />
                      </div>
                    )}
                </div>
              )}

              {/* ACTION 8: Wait for Element */}
              {modalStepData.action_type === "wait_for_element" && (
                <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                  <div>
                    <label className="sb-label">Wait Condition</label>
                    <select
                      value={modalStepData.action_params?.condition || "visible"}
                      onChange={(e) =>
                        setModalStepData({
                          ...modalStepData,
                          action_params: { ...modalStepData.action_params, condition: e.target.value },
                        })
                      }
                      className="sb-input"
                    >
                      <option value="visible">Wait until Element is Visible</option>
                      <option value="hidden">Wait until Element is Hidden</option>
                      <option value="attached">Wait until Element is Attached to DOM</option>
                      <option value="duration">Pause for Duration (ms)</option>
                    </select>
                  </div>

                  {modalStepData.action_params?.condition === "duration" ? (
                    <div>
                      <label className="sb-label">Duration (ms)</label>
                      <input
                        type="number"
                        value={modalStepData.action_params?.duration_ms || 1000}
                        onChange={(e) =>
                          setModalStepData({
                            ...modalStepData,
                            action_params: { ...modalStepData.action_params, duration_ms: parseInt(e.target.value) || 1000 },
                          })
                        }
                        className="sb-input"
                      />
                    </div>
                  ) : (
                    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                      {modalStepData.locator_value ? (
                        <div className="sb-picked-card">
                          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                            <div
                              style={{
                                width: 32,
                                height: 32,
                                borderRadius: 6,
                                background: "rgba(16, 185, 129, 0.15)",
                                color: "var(--v-success)",
                                display: "flex",
                                alignItems: "center",
                                justifyContent: "center",
                              }}
                            >
                              <Check size={16} />
                            </div>
                            <div>
                              <div style={{ fontSize: "0.82rem", fontWeight: 700, color: "var(--v-text)" }}>
                                {modalStepData.action_params?.element_friendly_name || modalStepData.locator_value}
                              </div>
                              <div style={{ fontSize: "0.72rem", color: "var(--v-text-secondary)", fontFamily: "monospace" }}>
                                {modalStepData.locator_type || "smart"}: {modalStepData.locator_value}
                              </div>
                            </div>
                          </div>
                          <button
                            type="button"
                            className="sb-picker-btn-mini"
                            onClick={() => {
                              setCurrentPickingTarget("main");
                              setElementPickerOpen(true);
                            }}
                          >
                            Pick Different Element
                          </button>
                        </div>
                      ) : (
                        <button
                          type="button"
                          className="sb-picker-btn"
                          style={{ justifyContent: "center", padding: "10px 16px" }}
                          onClick={() => {
                            setCurrentPickingTarget("main");
                            setElementPickerOpen(true);
                          }}
                        >
                          <Sparkles size={16} />
                          Inspect & Pick Element to Wait For
                        </button>
                      )}

                      <div>
                        <label className="sb-label">Target Element Locator <b>*</b></label>
                        <input
                          type="text"
                          value={modalStepData.locator_value || ""}
                          onChange={(e) => setModalStepData({ ...modalStepData, locator_value: e.target.value })}
                          placeholder='e.g. "#loading-spinner", ".results-table", or "Save Button"'
                          className="sb-input"
                        />
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* Advanced Locator Strategy Selector (Progressive Disclosure) */}
              {["fill_input", "click_element", "select_option", "verify_element", "wait_for_element"].includes(
                modalStepData.action_type
              ) && (
                <div style={{ paddingTop: 8, borderTop: "1px solid var(--v-border)" }}>
                  <button
                    type="button"
                    onClick={() => setShowAdvancedLocators(!showAdvancedLocators)}
                    style={{ background: "transparent", border: "none", color: "var(--v-text-muted)", fontSize: "0.75rem", fontWeight: 700, cursor: "pointer", display: "inline-flex", alignItems: "center", gap: 6, padding: 0 }}
                  >
                    <Settings2 size={13} />
                    Advanced Locator Strategy
                    {showAdvancedLocators ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
                  </button>

                  {showAdvancedLocators && (
                    <div style={{ marginTop: 8, padding: 10, borderRadius: 8, background: "var(--v-surface-2)", border: "1px solid var(--v-border)", display: "flex", flexDirection: "column", gap: 6 }}>
                      <select
                        value={modalStepData.locator_type || "smart"}
                        onChange={(e) => setModalStepData({ ...modalStepData, locator_type: e.target.value })}
                        className="sb-input"
                      >
                        {LOCATOR_STRATEGIES.map((strat) => (
                          <option key={strat.value} value={strat.value}>
                            {strat.label}
                          </option>
                        ))}
                      </select>
                      <p style={{ margin: 0, fontSize: "0.7rem", color: "var(--v-text-muted)" }}>
                        "Smart Dynamic" prioritizes accessible roles, form labels, and placeholders automatically before falling back to selectors.
                      </p>
                    </div>
                  )}
                </div>
              )}
            </div>

            {/* Modal Footer */}
            <div className="sb-modal-footer">
              <button
                type="button"
                onClick={() => setStepModalOpen(false)}
                className="button button-secondary button-small"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleSaveStepModal}
                className="button button-primary button-small"
              >
                {editingStepIndex !== null ? "Save Changes" : "Add to Workflow"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* =========================================================================
          5. SAVE WORKFLOW MODAL
      ========================================================================= */}
      {showSaveModal && (
        <div className="sb-modal-backdrop">
          <div className="sb-modal-card" style={{ maxWidth: 440 }}>
            <h3 style={{ margin: "0 0 4px 0", fontSize: "0.95rem", fontWeight: 700, color: "var(--v-text)" }}>
              Save Reusable Workflow
            </h3>
            <p style={{ margin: 0, fontSize: "0.78rem", color: "var(--v-text-secondary)" }}>
              Save this {workflowSteps.length}-step sequence to reuse anytime on {projectName}.
            </p>

            <div style={{ display: "flex", flexDirection: "column", gap: 12, marginTop: 16 }}>
              <div>
                <label className="sb-label">Workflow Name</label>
                <input
                  type="text"
                  value={saveWorkflowTitle || workflowName}
                  onChange={(e) => setSaveWorkflowTitle(e.target.value)}
                  placeholder="e.g. End-to-End Login & Timesheet Entry"
                  className="sb-input"
                />
              </div>

              <div>
                <label className="sb-label">Description (Optional)</label>
                <textarea
                  rows={2}
                  value={saveWorkflowDesc}
                  onChange={(e) => setSaveWorkflowDesc(e.target.value)}
                  placeholder="Describe what this workflow validates..."
                  className="sb-input"
                  style={{ resize: "vertical" }}
                />
              </div>
            </div>

            <div className="sb-modal-footer">
              <button
                type="button"
                onClick={() => setShowSaveModal(false)}
                className="button button-secondary button-small"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => void handleSaveWorkflowSubmit()}
                disabled={savingWorkflow}
                className="button button-primary button-small"
              >
                {savingWorkflow ? "Saving..." : "Save Workflow"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* =========================================================================
          6. VISUAL ELEMENT PICKER & INSPECTOR MODAL
      ========================================================================= */}
      {elementPickerOpen && (
        <ElementPickerModal
          projectId={projectId}
          projectName={projectName}
          actionType={modalStepData.action_type}
          onSelectElement={(el) => {
            handlePickedElement(el);
            setElementPickerOpen(false);
          }}
          onClose={() => setElementPickerOpen(false)}
        />
      )}
    </div>
  );
};
