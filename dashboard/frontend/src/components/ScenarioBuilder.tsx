import React, { useEffect, useState } from "react";
import {
  Layers,
  Plus,
  Play,
  Pencil,
  Trash2,
  ArrowUp,
  ArrowDown,
  CheckCircle2,
  AlertCircle,
  Clock,
  ShieldCheck,
  Search,
  Database,
  X,
  PlayCircle,
  FileCode,
  LogIn,
} from "lucide-react";
import {
  getProjectScenarios,
  getScenarioDetails,
  createScenario,
  updateScenario,
  deleteScenario,
  runScenario,
  getProjectCredentials,
  getProjectDataProfiles,
  createProjectDataProfile,
  deleteProjectDataProfile,
} from "../services/api";
import type {
  ScenarioItem,
  ScenarioPayload,
  ScenarioStep,
  CredentialItem,
  DataProfileItem,
} from "../services/api";

interface ScenarioBuilderProps {
  projectId: string;
  projectName: string;
  onRunTriggered: (runId: string) => void;
}

const ACTION_TYPES = [
  { value: "navigate", label: "Open page (URL / path)", hasLocator: false, hasParam: true, paramLabel: "URL or Path", placeholder: "/timesheet or https://..." },
  { value: "login", label: "Perform login (Auto-fill credentials vault)", hasLocator: false, hasParam: false },
  { value: "click", label: "Click element", hasLocator: true, hasParam: false },
  { value: "fill", label: "Enter text (fill input)", hasLocator: true, hasParam: true, paramLabel: "Text or Variable", placeholder: "e.g. {{username}} or text" },
  { value: "type", label: "Type text (keystrokes)", hasLocator: true, hasParam: true, paramLabel: "Text to type", placeholder: "e.g. 8.0" },
  { value: "clear", label: "Clear text", hasLocator: true, hasParam: false },
  { value: "press_key", label: "Press key", hasLocator: false, hasParam: true, paramLabel: "Key (e.g. Enter, Tab, Escape)", placeholder: "Enter" },
  { value: "select_option", label: "Select dropdown option", hasLocator: true, hasParam: true, paramLabel: "Option label or value", placeholder: "e.g. Project-Alpha" },
  { value: "check", label: "Check checkbox", hasLocator: true, hasParam: false },
  { value: "uncheck", label: "Uncheck checkbox", hasLocator: true, hasParam: false },
  { value: "hover", label: "Hover over element", hasLocator: true, hasParam: false },
  { value: "wait_for_timeout", label: "Pause / wait (ms)", hasLocator: false, hasParam: true, paramLabel: "Milliseconds to wait", placeholder: "1000" },
  { value: "wait_for_selector", label: "Wait for element to appear", hasLocator: true, hasParam: false },
  { value: "wait_for_navigation", label: "Wait for page load", hasLocator: false, hasParam: false },
  { value: "assert_visible", label: "Verify element is visible", hasLocator: true, hasParam: false },
  { value: "assert_hidden", label: "Verify element is hidden", hasLocator: true, hasParam: false },
  { value: "assert_text", label: "Verify element contains text", hasLocator: true, hasParam: true, paramLabel: "Expected text", placeholder: "Welcome" },
  { value: "assert_value", label: "Verify input value", hasLocator: true, hasParam: true, paramLabel: "Expected value", placeholder: "Expected value" },
  { value: "assert_title", label: "Verify page title", hasLocator: false, hasParam: true, paramLabel: "Expected title", placeholder: "Dashboard" },
  { value: "assert_url", label: "Verify URL substring", hasLocator: false, hasParam: true, paramLabel: "Expected URL substring", placeholder: "/timesheet" },
  { value: "capture_screenshot", label: "Capture screenshot", hasLocator: false, hasParam: false },
];

const LOCATOR_TYPES = [
  { value: "css", label: "CSS Selector" },
  { value: "id", label: "Element ID" },
  { value: "name", label: "Name Attribute" },
  { value: "text", label: "Visible Text" },
  { value: "placeholder", label: "Placeholder" },
  { value: "label", label: "Form Label" },
  { value: "testid", label: "Test ID (data-testid)" },
  { value: "xpath", label: "XPath" },
  { value: "role", label: "ARIA Role" },
];

export const ScenarioBuilder: React.FC<ScenarioBuilderProps> = ({
  projectId,
  projectName,
  onRunTriggered,
}) => {
  const [scenarios, setScenarios] = useState<ScenarioItem[]>([]);
  const [credentials, setCredentials] = useState<CredentialItem[]>([]);
  const [dataProfiles, setDataProfiles] = useState<DataProfileItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  // Editor mode state
  const [isEditing, setIsEditing] = useState(false);
  const [activeScenarioId, setActiveScenarioId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // Scenario form fields
  const [formName, setFormName] = useState("");
  const [formDescription, setFormDescription] = useState("");
  const [formTags, setFormTags] = useState("");
  const [formPolicy, setFormPolicy] = useState<"stop" | "continue">("stop");
  const [formTimeout, setFormTimeout] = useState(60);
  const [formEnv, setFormEnv] = useState("QA");
  const [formCredentialId, setFormCredentialId] = useState<string>("");
  const [formSteps, setFormSteps] = useState<ScenarioStep[]>([]);

  // Execution modal state
  const [execModalScenario, setExecModalScenario] = useState<ScenarioItem | null>(null);
  const [execEnv, setExecEnv] = useState("QA");
  const [execCredId, setExecCredId] = useState<string>("");
  const [execDataProfileId, setExecDataProfileId] = useState<string>("");
  const [execStarting, setExecStarting] = useState(false);

  // Data Profiles modal state
  const [dataProfilesModalOpen, setDataProfilesModalOpen] = useState(false);
  const [newProfileName, setNewProfileName] = useState("");
  const [newProfileRowsJson, setNewProfileRowsJson] = useState('[\n  {"user": "tester", "role": "admin"}\n]');

  const loadData = async () => {
    if (!projectId) return;
    setLoading(true);
    setError(null);
    try {
      const [scList, crList, dpList] = await Promise.all([
        getProjectScenarios(projectId),
        getProjectCredentials(projectId),
        getProjectDataProfiles(projectId),
      ]);
      setScenarios(scList);
      setCredentials(crList);
      setDataProfiles(dpList);
    } catch (err: any) {
      setError(err?.message || "Failed to load scenarios.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadData();
  }, [projectId]);

  const handleOpenCreate = () => {
    setActiveScenarioId(null);
    setFormName("");
    setFormDescription("");
    setFormTags("smoke, regression");
    setFormPolicy("stop");
    setFormTimeout(60);
    setFormEnv("QA");
    setFormCredentialId(credentials.length > 0 ? credentials[0].id : "");
    // Default 3 starter steps
    setFormSteps([
      {
        step_order: 1,
        action_type: "navigate",
        locator_value: "/",
        action_params: { url: "/" },
        description: "Open application home page",
        is_enabled: true,
      },
      {
        step_order: 2,
        action_type: "assert_title",
        action_params: { value: "" },
        description: "Verify title contains expected application name",
        is_enabled: true,
      },
      {
        step_order: 3,
        action_type: "capture_screenshot",
        description: "Capture screenshot of loaded page",
        is_enabled: true,
      },
    ]);
    setIsEditing(true);
  };

  const handleOpenEdit = async (scenario: ScenarioItem) => {
    setLoading(true);
    try {
      const details = await getScenarioDetails(scenario.id);
      setActiveScenarioId(details.id);
      setFormName(details.name);
      setFormDescription(details.description || "");
      setFormTags((details.tags || []).join(", "));
      setFormPolicy(details.failure_policy || "stop");
      setFormTimeout(details.timeout_seconds || 60);
      setFormEnv(details.environment || "QA");
      setFormCredentialId(details.credential_id || "");
      setFormSteps(details.steps || []);
      setIsEditing(true);
    } catch (err: any) {
      setError(err?.message || "Failed to load scenario details.");
    } finally {
      setLoading(false);
    }
  };

  const handleAddStep = () => {
    const nextOrder = formSteps.length + 1;
    setFormSteps([
      ...formSteps,
      {
        step_order: nextOrder,
        action_type: "click",
        locator_type: "css",
        locator_value: "",
        action_params: {},
        description: `Step ${nextOrder}`,
        is_enabled: true,
      },
    ]);
  };

  const handleInsertLoginFlow = () => {
    const nextOrder = formSteps.length;
    const loginSteps: ScenarioStep[] = [
      {
        step_order: nextOrder + 1,
        action_type: "navigate",
        action_params: { url: "/" },
        description: "Open application login page",
        is_enabled: true,
      },
      {
        step_order: nextOrder + 2,
        action_type: "fill",
        locator_type: "css",
        locator_value: "input[name='username'], #username, #P9999_USERNAME",
        action_params: { value: "{{username}}" },
        description: "Enter username from application vault",
        is_enabled: true,
      },
      {
        step_order: nextOrder + 3,
        action_type: "fill",
        locator_type: "css",
        locator_value: "input[type='password'], #password, #P9999_PASSWORD",
        action_params: { value: "{{password}}" },
        description: "Enter password from application vault",
        is_enabled: true,
      },
      {
        step_order: nextOrder + 4,
        action_type: "click",
        locator_type: "css",
        locator_value: "button[type='submit'], input[type='submit'], #B9999_LOGIN, #login-btn",
        description: "Click Sign In / Submit button",
        is_enabled: true,
      },
    ];
    setFormSteps([...formSteps, ...loginSteps]);
  };

  const handleUpdateStep = (index: number, updates: Partial<ScenarioStep>) => {
    const updated = [...formSteps];
    updated[index] = { ...updated[index], ...updates };
    setFormSteps(updated);
  };

  const handleMoveStep = (index: number, direction: "up" | "down") => {
    if (direction === "up" && index === 0) return;
    if (direction === "down" && index === formSteps.length - 1) return;

    const targetIdx = direction === "up" ? index - 1 : index + 1;
    const updated = [...formSteps];
    const [moved] = updated.splice(index, 1);
    updated.splice(targetIdx, 0, moved);

    // Re-index step_order
    updated.forEach((s, idx) => {
      s.step_order = idx + 1;
    });
    setFormSteps(updated);
  };

  const handleDeleteStep = (index: number) => {
    const updated = formSteps.filter((_, idx) => idx !== index);
    updated.forEach((s, idx) => {
      s.step_order = idx + 1;
    });
    setFormSteps(updated);
  };

  const handleSaveScenario = async () => {
    if (!formName.trim()) {
      setError("Scenario name is required.");
      return;
    }
    if (formSteps.length === 0) {
      setError("Please add at least one step to the scenario.");
      return;
    }

    setSaving(true);
    setError(null);

    const tagsArray = formTags
      .split(",")
      .map((t) => t.trim())
      .filter(Boolean);

    const payload: ScenarioPayload = {
      name: formName.trim(),
      description: formDescription.trim() || undefined,
      tags: tagsArray,
      failure_policy: formPolicy,
      timeout_seconds: Number(formTimeout) || 60,
      environment: formEnv,
      credential_id: formCredentialId || null,
      steps: formSteps,
    };

    try {
      if (activeScenarioId) {
        await updateScenario(activeScenarioId, payload);
        setSuccess(`Scenario "${formName}" updated successfully.`);
      } else {
        await createScenario(projectId, payload);
        setSuccess(`Scenario "${formName}" created successfully.`);
      }
      setIsEditing(false);
      void loadData();
      setTimeout(() => setSuccess(null), 4000);
    } catch (err: any) {
      setError(err?.message || "Failed to save scenario.");
    } finally {
      setSaving(false);
    }
  };

  const handleDeleteScenario = async (scenario: ScenarioItem) => {
    if (!confirm(`Are you sure you want to delete scenario "${scenario.name}"?`)) return;
    try {
      await deleteScenario(scenario.id);
      setSuccess(`Scenario "${scenario.name}" removed.`);
      void loadData();
      setTimeout(() => setSuccess(null), 4000);
    } catch (err: any) {
      setError(err?.message || "Failed to delete scenario.");
    }
  };

  const handleTriggerRunModal = (scenario: ScenarioItem) => {
    setExecModalScenario(scenario);
    setExecEnv(scenario.environment || "QA");
    setExecCredId(scenario.credential_id || (credentials[0]?.id ?? ""));
    setExecDataProfileId(dataProfiles[0]?.id ?? "");
  };

  const handleExecuteNow = async () => {
    if (!execModalScenario) return;
    setExecStarting(true);
    try {
      const res = await runScenario(execModalScenario.id, {
        environment: execEnv,
        credential_id: execCredId || undefined,
        data_profile_id: execDataProfileId || undefined,
      });
      setExecModalScenario(null);
      onRunTriggered(res.run_id);
    } catch (err: any) {
      setError(err?.message || "Failed to start scenario run.");
    } finally {
      setExecStarting(false);
    }
  };

  const handleCreateDataProfile = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newProfileName.trim()) return;
    try {
      const parsedRows = JSON.parse(newProfileRowsJson);
      if (!Array.isArray(parsedRows)) {
        throw new Error("Dataset rows must be a JSON array of objects.");
      }
      await createProjectDataProfile(projectId, {
        name: newProfileName.trim(),
        dataset_rows: parsedRows,
      });
      setNewProfileName("");
      setNewProfileRowsJson('[\n  {"user": "tester", "role": "admin"}\n]');
      void loadData();
      setSuccess("Test data profile saved.");
      setTimeout(() => setSuccess(null), 3000);
    } catch (err: any) {
      setError(err?.message || "Invalid JSON array.");
    }
  };

  const filtered = scenarios.filter(
    (s) =>
      s.name.toLowerCase().includes(search.toLowerCase()) ||
      (s.description || "").toLowerCase().includes(search.toLowerCase()) ||
      (s.tags || []).some((t) => t.toLowerCase().includes(search.toLowerCase())),
  );

  return (
    <div className="scenario-builder-wrap">
      {/* List View */}
      {!isEditing && (
        <div className="card">
          <div className="card-heading-row" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
            <div>
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <div className="card-heading-icon" style={{ padding: 8, borderRadius: 8, background: "rgba(0, 214, 176, 0.12)", color: "#00d6b0" }}>
                  <Layers size={22} />
                </div>
                <div>
                  <h2 style={{ margin: 0, fontSize: "1.15rem", fontWeight: 700, color: "var(--vq-text, #fff)" }}>
                    Test Scenario Builder
                  </h2>
                  <span className="muted-text" style={{ fontSize: "0.85rem" }}>
                    Visual, configuration-driven browser automation for <strong>{projectName}</strong>. No Python test files needed.
                  </span>
                </div>
              </div>
            </div>

            <div style={{ display: "flex", gap: 10 }}>
              <button
                className="button button-secondary button-small"
                onClick={() => setDataProfilesModalOpen(true)}
              >
                <Database size={15} />
                Data Profiles ({dataProfiles.length})
              </button>
              <button
                className="button button-primary button-small"
                onClick={handleOpenCreate}
              >
                <Plus size={15} />
                Create Scenario
              </button>
            </div>
          </div>

          {error && (
            <div className="alert-error" style={{ display: "flex", alignItems: "center", gap: 8, padding: "10px 14px", borderRadius: 8, marginBottom: 16 }}>
              <AlertCircle size={16} />
              <span>{error}</span>
            </div>
          )}

          {success && (
            <div className="alert-success" style={{ display: "flex", alignItems: "center", gap: 8, padding: "10px 14px", borderRadius: 8, marginBottom: 16 }}>
              <CheckCircle2 size={16} />
              <span>{success}</span>
            </div>
          )}

          {/* Architecture & Credential Guidance Banner */}
          <div
            style={{
              padding: "14px 18px",
              background: "linear-gradient(135deg, #EEF2FF 0%, #F0FDF4 100%)",
              border: "1px solid #C7D2FE",
              borderRadius: 8,
              marginBottom: 18,
              display: "flex",
              gap: 14,
              alignItems: "flex-start",
            }}
          >
            <ShieldCheck size={20} style={{ color: "var(--v-accent)", marginTop: 2, flexShrink: 0 }} />
            <div style={{ fontSize: "0.84rem", color: "#1E293B", lineHeight: 1.5 }}>
              <strong style={{ color: "#3730A3", display: "block", marginBottom: 3 }}>
                How Scenario Automation & Isolated Credentials Work
              </strong>
              <span>
                Scenarios run step-by-step in real headless/headed browser sessions. When your steps reference{" "}
                <code style={{ background: "#FFFFFF", border: "1px solid #CBD5E1", padding: "1px 6px", borderRadius: 4, color: "var(--v-accent)", fontWeight: 600 }}>{"{{username}}"}</code> and{" "}
                <code style={{ background: "#FFFFFF", border: "1px solid #CBD5E1", padding: "1px 6px", borderRadius: 4, color: "var(--v-accent)", fontWeight: 600 }}>{"{{password}}"}</code>,
                Veriqon decrypts the credentials saved for <strong>{projectName}</strong> directly in memory. Each application has its own isolated credential vault and baseURL—credentials never leak between applications.
              </span>
            </div>
          </div>

          {/* Search bar */}
          <div style={{ position: "relative", marginBottom: 16 }}>
            <Search
              size={16}
              style={{ position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)", color: "var(--vq-muted, #7188a6)" }}
            />
            <input
              type="text"
              placeholder="Search scenarios by name, description, or tags..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              style={{ width: "100%", paddingLeft: 36, height: 38 }}
            />
          </div>

          {/* Scenario Cards / List */}
          {loading && scenarios.length === 0 ? (
            <div style={{ padding: 40, textAlign: "center", color: "var(--vq-muted)" }}>
              Loading scenarios...
            </div>
          ) : filtered.length === 0 ? (
            <div style={{ padding: 40, textAlign: "center", background: "var(--vq-surface-2, rgba(255,255,255,0.02))", borderRadius: 8, border: "1px dashed var(--vq-border)" }}>
              <Layers size={32} style={{ color: "var(--vq-muted)", marginBottom: 8, opacity: 0.7 }} />
              <div style={{ fontWeight: 600, color: "var(--vq-text)" }}>No test scenarios created yet</div>
              <div className="muted-text" style={{ fontSize: "0.85rem", marginTop: 4, marginBottom: 16 }}>
                Create automated user journeys, form fills, button clicks, and assertions visually without writing Python test scripts.
              </div>
              <button className="button button-primary button-small" onClick={handleOpenCreate}>
                <Plus size={15} /> Create Scenario
              </button>
            </div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {filtered.map((s) => (
                <div
                  key={s.id}
                  className="card"
                  style={{
                    padding: "16px 20px",
                    background: "var(--vq-surface, #101a28)",
                    border: "1px solid var(--vq-border)",
                    borderRadius: 10,
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                  }}
                >
                  <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                      <span style={{ fontWeight: 700, fontSize: "1.05rem", color: "var(--vq-text, #fff)" }}>
                        {s.name}
                      </span>
                      <span
                        className="badge"
                        style={{
                          background: "rgba(0, 214, 176, 0.12)",
                          color: "#00d6b0",
                          padding: "2px 8px",
                          borderRadius: 6,
                          fontSize: "0.75rem",
                          fontWeight: 700,
                        }}
                      >
                        {s.step_count ?? s.steps?.length ?? 0} Steps
                      </span>
                      <span
                        className="badge"
                        style={{
                          background: s.failure_policy === "stop" ? "rgba(255, 96, 120, 0.15)" : "rgba(139, 184, 255, 0.15)",
                          color: s.failure_policy === "stop" ? "#ff6078" : "#8bb8ff",
                          padding: "2px 8px",
                          borderRadius: 6,
                          fontSize: "0.75rem",
                          fontWeight: 600,
                        }}
                      >
                        Policy: {s.failure_policy === "stop" ? "Stop on Error" : "Continue"}
                      </span>
                    </div>

                    <div style={{ fontSize: "0.85rem", color: "var(--vq-muted)" }}>
                      {s.description || "No description provided."}
                    </div>

                    <div style={{ display: "flex", alignItems: "center", gap: 14, fontSize: "0.8rem", color: "var(--vq-muted)", marginTop: 4 }}>
                      <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
                        <Clock size={13} /> Timeout: {s.timeout_seconds}s
                      </span>
                      {s.credential_name && (
                        <span style={{ display: "flex", alignItems: "center", gap: 4, color: "#00d6b0" }}>
                          <ShieldCheck size={13} /> Credential: {s.credential_name}
                        </span>
                      )}
                      {(s.tags || []).map((tag, tIdx) => (
                        <span
                          key={tIdx}
                          style={{
                            background: "rgba(255,255,255,0.06)",
                            padding: "1px 6px",
                            borderRadius: 4,
                            fontSize: "0.75rem",
                          }}
                        >
                          #{tag}
                        </span>
                      ))}
                    </div>
                  </div>

                  <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
                    <button
                      className="button button-primary button-small"
                      onClick={() => handleTriggerRunModal(s)}
                    >
                      <Play size={14} /> Run
                    </button>
                    <button
                      className="button button-secondary button-small"
                      onClick={() => void handleOpenEdit(s)}
                      title="Edit Scenario Steps"
                    >
                      <Pencil size={14} /> Edit
                    </button>
                    <button
                      className="button button-secondary button-small"
                      onClick={() => void handleDeleteScenario(s)}
                      title="Delete Scenario"
                      style={{ color: "#ff6078" }}
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Editor & Step Builder View */}
      {isEditing && (
        <div className="card">
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <div className="card-heading-icon" style={{ padding: 8, borderRadius: 8, background: "rgba(0, 214, 176, 0.12)", color: "#00d6b0" }}>
                <FileCode size={22} />
              </div>
              <div>
                <h2 style={{ margin: 0, fontSize: "1.2rem", fontWeight: 700, color: "var(--vq-text, #fff)" }}>
                  {activeScenarioId ? `Edit Scenario: ${formName}` : "Create New Automated Scenario"}
                </h2>
                <span className="muted-text" style={{ fontSize: "0.85rem" }}>
                  Configure application journey, order of interaction steps, locators, and variable placeholders.
                </span>
              </div>
            </div>

            <div style={{ display: "flex", gap: 10 }}>
              <button
                className="button button-secondary button-small"
                onClick={() => setIsEditing(false)}
              >
                Back to Scenarios
              </button>
              <button
                className="button button-primary button-small"
                onClick={handleSaveScenario}
                disabled={saving}
              >
                {saving ? "Saving..." : "Save Scenario"}
              </button>
            </div>
          </div>

          {error && (
            <div className="alert-error" style={{ display: "flex", alignItems: "center", gap: 8, padding: "10px 14px", borderRadius: 8, marginBottom: 16 }}>
              <AlertCircle size={16} />
              <span>{error}</span>
            </div>
          )}

          {/* Scenario Configuration Grid */}
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 16, marginBottom: 24, padding: 16, background: "var(--vq-surface-2, rgba(255,255,255,0.02))", borderRadius: 8, border: "1px solid var(--vq-border)" }}>
            <label className="field">
              <span>Scenario Name *</span>
              <input
                type="text"
                placeholder="e.g. Timesheet Submission Workflow"
                value={formName}
                onChange={(e) => setFormName(e.target.value)}
                required
              />
            </label>

            <label className="field">
              <span>Description</span>
              <input
                type="text"
                placeholder="What this automated workflow verifies"
                value={formDescription}
                onChange={(e) => setFormDescription(e.target.value)}
              />
            </label>

            <label className="field">
              <span>Associated Credential Profile</span>
              <select
                value={formCredentialId}
                onChange={(e) => setFormCredentialId(e.target.value)}
              >
                <option value="">None (Public / No Auth)</option>
                {credentials.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name} ({c.username}) - {c.environment}
                  </option>
                ))}
              </select>
            </label>

            <label className="field">
              <span>Failure Policy</span>
              <select
                value={formPolicy}
                onChange={(e) => setFormPolicy(e.target.value as "stop" | "continue")}
              >
                <option value="stop">Stop immediately on first step failure (Recommended)</option>
                <option value="continue">Continue executing remaining steps</option>
              </select>
            </label>

            <label className="field">
              <span>Timeout (Seconds)</span>
              <input
                type="number"
                min={5}
                max={600}
                value={formTimeout}
                onChange={(e) => setFormTimeout(Number(e.target.value))}
              />
            </label>

            <label className="field">
              <span>Tags (comma-separated)</span>
              <input
                type="text"
                placeholder="smoke, regression, timesheet"
                value={formTags}
                onChange={(e) => setFormTags(e.target.value)}
              />
            </label>
          </div>

          {/* Visual Step Builder */}
          <div style={{ marginBottom: 24 }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12, flexWrap: "wrap", gap: 10 }}>
              <div>
                <h3 style={{ margin: 0, fontSize: "1.05rem", fontWeight: 700, color: "var(--v-text)" }}>
                  Execution Steps ({formSteps.length})
                </h3>
                <span style={{ fontSize: "0.82rem", color: "var(--v-text-secondary)" }}>
                  Steps execute in exact order. Inject secure credentials with <code style={{ color: "var(--v-accent)", fontWeight: 600 }}>{"{{username}}"}</code> and <code style={{ color: "var(--v-accent)", fontWeight: 600 }}>{"{{password}}"}</code>.
                </span>
              </div>
              <div style={{ display: "flex", gap: 8 }}>
                <button
                  type="button"
                  className="button button-secondary button-small"
                  onClick={handleInsertLoginFlow}
                  title="Insert 4-step login sequence configured with this application's credentials"
                >
                  <LogIn size={14} /> Insert Login Steps
                </button>
                <button
                  type="button"
                  className="button button-primary button-small"
                  onClick={handleAddStep}
                >
                  <Plus size={14} /> Add Step
                </button>
              </div>
            </div>

            {formSteps.length === 0 ? (
              <div style={{ padding: 36, textAlign: "center", background: "var(--v-surface-2)", borderRadius: 8, border: "1px dashed var(--v-border)" }}>
                <p style={{ color: "var(--v-text-secondary)", marginBottom: 14 }}>No steps defined yet. Click "Insert Login Steps" for a quick start, or "Add Step" to customize.</p>
                <div style={{ display: "flex", gap: 10, justifyContent: "center" }}>
                  <button type="button" className="button button-secondary button-small" onClick={handleInsertLoginFlow}>
                    <LogIn size={14} /> Insert Login Steps
                  </button>
                  <button type="button" className="button button-primary button-small" onClick={handleAddStep}>
                    <Plus size={14} /> Add Step
                  </button>
                </div>
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                {formSteps.map((step, idx) => {
                  const actionMeta = ACTION_TYPES.find((a) => a.value === step.action_type) || ACTION_TYPES[0];
                  const hasLoc = actionMeta.hasLocator;
                  const hasPar = actionMeta.hasParam;
                  const paramVal = step.action_params?.value ?? step.action_params?.url ?? step.action_params?.key ?? "";

                  return (
                    <div
                      key={idx}
                      className="card"
                      style={{
                        padding: 14,
                        background: step.is_enabled ? "var(--vq-surface, #101a28)" : "rgba(255,255,255,0.02)",
                        border: "1px solid var(--vq-border)",
                        borderRadius: 8,
                        opacity: step.is_enabled ? 1 : 0.6,
                      }}
                    >
                      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                          <span
                            style={{
                              background: "rgba(0, 214, 176, 0.15)",
                              color: "#00d6b0",
                              fontWeight: 700,
                              borderRadius: "50%",
                              width: 24,
                              height: 24,
                              display: "flex",
                              alignItems: "center",
                              justifyContent: "center",
                              fontSize: "0.8rem",
                            }}
                          >
                            {idx + 1}
                          </span>
                          <input
                            type="text"
                            placeholder="Step description..."
                            value={step.description || ""}
                            onChange={(e) => handleUpdateStep(idx, { description: e.target.value })}
                            style={{
                              fontWeight: 600,
                              fontSize: "0.95rem",
                              background: "transparent",
                              border: "none",
                              borderBottom: "1px solid transparent",
                              color: "var(--vq-text, #fff)",
                              width: 320,
                            }}
                          />
                        </div>

                        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                          <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: "0.8rem", cursor: "pointer", marginRight: 8 }}>
                            <input
                              type="checkbox"
                              checked={step.is_enabled !== false}
                              onChange={(e) => handleUpdateStep(idx, { is_enabled: e.target.checked })}
                            />
                            Enabled
                          </label>

                          <button
                            className="button button-secondary button-small"
                            onClick={() => handleMoveStep(idx, "up")}
                            disabled={idx === 0}
                            title="Move Step Up"
                            style={{ padding: "3px 6px" }}
                          >
                            <ArrowUp size={13} />
                          </button>
                          <button
                            className="button button-secondary button-small"
                            onClick={() => handleMoveStep(idx, "down")}
                            disabled={idx === formSteps.length - 1}
                            title="Move Step Down"
                            style={{ padding: "3px 6px" }}
                          >
                            <ArrowDown size={13} />
                          </button>
                          <button
                            className="button button-secondary button-small"
                            onClick={() => handleDeleteStep(idx)}
                            title="Delete Step"
                            style={{ padding: "3px 6px", color: "#ff6078" }}
                          >
                            <Trash2 size={13} />
                          </button>
                        </div>
                      </div>

                      {/* Step Action Config Row */}
                      <div style={{ display: "grid", gridTemplateColumns: hasLoc && hasPar ? "1.2fr 1fr 1.5fr" : hasLoc ? "1.2fr 2fr" : hasPar ? "1.2fr 2fr" : "1fr", gap: 10 }}>
                        <label className="field" style={{ margin: 0 }}>
                          <span style={{ fontSize: "0.78rem" }}>Action Type</span>
                          <select
                            value={step.action_type}
                            onChange={(e) => {
                              const newAction = e.target.value;
                              handleUpdateStep(idx, {
                                action_type: newAction,
                                locator_type: newAction === "navigate" ? undefined : step.locator_type || "css",
                              });
                            }}
                          >
                            {ACTION_TYPES.map((a) => (
                              <option key={a.value} value={a.value}>
                                {a.label}
                              </option>
                            ))}
                          </select>
                        </label>

                        {hasLoc && (
                          <div style={{ display: "flex", gap: 8 }}>
                            <label className="field" style={{ margin: 0, width: "35%" }}>
                              <span style={{ fontSize: "0.78rem" }}>Locator Type</span>
                              <select
                                value={step.locator_type || "css"}
                                onChange={(e) => handleUpdateStep(idx, { locator_type: e.target.value })}
                              >
                                {LOCATOR_TYPES.map((l) => (
                                  <option key={l.value} value={l.value}>
                                    {l.label}
                                  </option>
                                ))}
                              </select>
                            </label>

                            <label className="field" style={{ margin: 0, flex: 1 }}>
                              <span style={{ fontSize: "0.78rem" }}>Locator Target</span>
                              <input
                                type="text"
                                placeholder="#submit-btn or text=Log In"
                                value={step.locator_value || ""}
                                onChange={(e) => handleUpdateStep(idx, { locator_value: e.target.value })}
                              />
                            </label>
                          </div>
                        )}

                        {hasPar && (
                          <label className="field" style={{ margin: 0 }}>
                            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                              <span style={{ fontSize: "0.78rem" }}>{actionMeta.paramLabel}</span>
                              <div style={{ display: "flex", gap: 4 }}>
                                <button
                                  type="button"
                                  style={{ background: "transparent", border: "none", color: "#00d6b0", fontSize: "0.7rem", cursor: "pointer", padding: 0 }}
                                  onClick={() => {
                                    const curr = String(paramVal || "");
                                    const key = step.action_type === "navigate" ? "url" : step.action_type === "press_key" ? "key" : "value";
                                    handleUpdateStep(idx, {
                                      action_params: { ...step.action_params, [key]: curr + "{{username}}" },
                                    });
                                  }}
                                >
                                  +{"{{username}}"}
                                </button>
                                <button
                                  type="button"
                                  style={{ background: "transparent", border: "none", color: "#00d6b0", fontSize: "0.7rem", cursor: "pointer", padding: 0 }}
                                  onClick={() => {
                                    const curr = String(paramVal || "");
                                    const key = step.action_type === "navigate" ? "url" : step.action_type === "press_key" ? "key" : "value";
                                    handleUpdateStep(idx, {
                                      action_params: { ...step.action_params, [key]: curr + "{{password}}" },
                                    });
                                  }}
                                >
                                  +{"{{password}}"}
                                </button>
                              </div>
                            </div>
                            <input
                              type="text"
                              placeholder={actionMeta.placeholder}
                              value={paramVal}
                              onChange={(e) => {
                                const key = step.action_type === "navigate" ? "url" : step.action_type === "press_key" ? "key" : "value";
                                handleUpdateStep(idx, {
                                  action_params: { ...step.action_params, [key]: e.target.value },
                                });
                              }}
                            />
                          </label>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          <div style={{ display: "flex", justifyContent: "flex-end", gap: 10 }}>
            <button
              className="button button-secondary"
              onClick={() => setIsEditing(false)}
            >
              Cancel
            </button>
            <button
              className="button button-primary"
              onClick={handleSaveScenario}
              disabled={saving}
            >
              {saving ? "Saving Workflow..." : "Save Scenario"}
            </button>
          </div>
        </div>
      )}

      {/* Execution Trigger Modal */}
      {execModalScenario && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0, 0, 0, 0.7)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 9999,
            padding: 16,
          }}
        >
          <div
            className="card"
            style={{
              width: "100%",
              maxWidth: 480,
              boxShadow: "0 10px 40px rgba(0,0,0,0.6)",
              border: "1px solid var(--vq-border)",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <PlayCircle size={20} style={{ color: "#00d6b0" }} />
                <h3 style={{ margin: 0, fontSize: "1.1rem" }}>
                  Run: {execModalScenario.name}
                </h3>
              </div>
              <button
                className="button button-secondary button-small"
                onClick={() => setExecModalScenario(null)}
                style={{ padding: 4 }}
              >
                <X size={16} />
              </button>
            </div>

            <div className="form-stack">
              <label className="field">
                <span>Target Environment</span>
                <select
                  value={execEnv}
                  onChange={(e) => setExecEnv(e.target.value)}
                >
                  <option value="QA">QA</option>
                  <option value="Development">Development</option>
                  <option value="Staging">Staging</option>
                  <option value="Production">Production</option>
                </select>
              </label>

              <label className="field">
                <span>Application Credential</span>
                <select
                  value={execCredId}
                  onChange={(e) => setExecCredId(e.target.value)}
                >
                  <option value="">No credential override</option>
                  {credentials.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name} ({c.username}) [{c.environment}]
                    </option>
                  ))}
                </select>
              </label>

              {dataProfiles.length > 0 && (
                <label className="field">
                  <span>Test Data Profile (Optional)</span>
                  <select
                    value={execDataProfileId}
                    onChange={(e) => setExecDataProfileId(e.target.value)}
                  >
                    <option value="">None (Static Step Values)</option>
                    {dataProfiles.map((dp) => (
                      <option key={dp.id} value={dp.id}>
                        {dp.name} ({dp.dataset_rows.length} rows)
                      </option>
                    ))}
                  </select>
                </label>
              )}

              <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 14 }}>
                <button
                  type="button"
                  className="button button-secondary"
                  onClick={() => setExecModalScenario(null)}
                >
                  Cancel
                </button>
                <button
                  type="button"
                  className="button button-primary"
                  onClick={handleExecuteNow}
                  disabled={execStarting}
                >
                  <Play size={15} />
                  {execStarting ? "Launching Runner..." : "Start Scenario"}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Data Profiles Modal */}
      {dataProfilesModalOpen && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0, 0, 0, 0.7)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            zIndex: 9999,
            padding: 16,
          }}
        >
          <div
            className="card"
            style={{
              width: "100%",
              maxWidth: 600,
              boxShadow: "0 10px 40px rgba(0,0,0,0.6)",
              border: "1px solid var(--vq-border)",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <Database size={20} style={{ color: "#00d6b0" }} />
                <h3 style={{ margin: 0, fontSize: "1.1rem" }}>
                  Reusable Test Data Profiles
                </h3>
              </div>
              <button
                className="button button-secondary button-small"
                onClick={() => setDataProfilesModalOpen(false)}
                style={{ padding: 4 }}
              >
                <X size={16} />
              </button>
            </div>

            <div style={{ marginBottom: 16, maxHeight: 180, overflowY: "auto" }}>
              {dataProfiles.length === 0 ? (
                <p className="muted-text" style={{ fontSize: "0.85rem" }}>
                  No data profiles configured for this application yet.
                </p>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                  {dataProfiles.map((dp) => (
                    <div
                      key={dp.id}
                      style={{
                        padding: "8px 12px",
                        borderRadius: 6,
                        background: "var(--vq-surface-2)",
                        display: "flex",
                        justifyContent: "space-between",
                        alignItems: "center",
                      }}
                    >
                      <div>
                        <strong>{dp.name}</strong> ({dp.dataset_rows.length} rows)
                      </div>
                      <button
                        className="button button-secondary button-small"
                        onClick={async () => {
                          await deleteProjectDataProfile(dp.id);
                          void loadData();
                        }}
                        style={{ color: "#ff6078", padding: "2px 6px" }}
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <form onSubmit={handleCreateDataProfile} className="form-stack">
              <label className="field">
                <span>New Profile Name</span>
                <input
                  type="text"
                  placeholder="e.g. Employee Hours Matrix"
                  value={newProfileName}
                  onChange={(e) => setNewProfileName(e.target.value)}
                  required
                />
              </label>

              <label className="field">
                <span>Dataset Rows (JSON Array)</span>
                <textarea
                  rows={5}
                  value={newProfileRowsJson}
                  onChange={(e) => setNewProfileRowsJson(e.target.value)}
                  style={{ fontFamily: "monospace", fontSize: "0.85rem" }}
                  required
                />
              </label>

              <div style={{ display: "flex", justifyContent: "flex-end", gap: 10 }}>
                <button
                  type="button"
                  className="button button-secondary"
                  onClick={() => setDataProfilesModalOpen(false)}
                >
                  Close
                </button>
                <button type="submit" className="button button-primary">
                  <Plus size={14} /> Add Profile
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
