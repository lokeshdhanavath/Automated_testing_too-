
import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import {
  Activity,
  Archive,
  Camera,
  CheckCircle2,
  CircleAlert,
  Clock3,
  Download,
  ExternalLink,
  Eye,
  FileBarChart,
  FileText,
  Film,
  FlaskConical,
  FolderKanban,
  Gauge,
  HardDrive,
  KeyRound,
  Layers,
  LayoutDashboard,
  ListChecks,
  LoaderCircle,
  Pencil,
  Play,
  Plus,
  RefreshCw,
  Save,
  Search,
  Settings2,
  SquareTerminal,
  Trash2,
  Video,
  X,
  XCircle,
} from "lucide-react";

import {
  API_BASE_URL,
  checkBackendHealth,
  getTestCases,
  startRun,
  getRunStatus,
  getRunLogs,
  getProjectRuns,
  getProjectArtifacts,
  validateCsvScenarios,
  executeCsvScenarios,
  getProjects,
  createProject,
  updateProject,
  deleteProject,
  toggleProjectActive,
  getRunStepResults,
} from "./services/api";

import type {
  TestCase,
  CsvValidationResponse,
  ProjectConfig,
  ProjectPayload,
  ArtifactItem,
  RunRecord,
  TestResultItem,
  StepExecutionResult,
} from "./services/api";
import { CredentialsPanel } from "./components/CredentialsPanel";
import { ScenarioBuilder } from "./components/ScenarioBuilder";
import { ScenarioExecutionView } from "./components/ScenarioExecutionView";
import "./App.css";

type Page =
  | "Applications"
  | "Overview"
  | "Scenario Builder"
  | "Credentials"
  | "Test Suites"
  | "CSV Scenarios"
  | "Test Runs"
  | "Test Evidence"
  | "Screenshots & Recordings"
  | "Settings";

type RunSummary = {
  total?: number;
  passed?: number;
  failed?: number;
  skipped?: number;
  errors?: number;
};

const terminalStatuses = new Set([
  "passed",
  "failed",
  "error",
  "cancelled",
]);

const navigation: {
  section: string;
  items: { label: Page; icon: typeof LayoutDashboard }[];
}[] = [
  {
    section: "WORKSPACE",
    items: [
      { label: "Overview", icon: LayoutDashboard },
      { label: "Scenario Builder", icon: Layers },
      { label: "Credentials", icon: KeyRound },
    ],
  },
  {
    section: "TESTING",
    items: [
      { label: "Test Suites", icon: ListChecks },
      { label: "CSV Scenarios", icon: FileText },
      { label: "Test Runs", icon: Play },
    ],
  },
  {
    section: "EVIDENCE",
    items: [
      { label: "Test Evidence", icon: FileBarChart },
      { label: "Screenshots & Recordings", icon: Camera },
    ],
  },
  {
    section: "CONFIGURATION",
    items: [{ label: "Settings", icon: Settings2 }],
  },
];

export default function App() {
  const [page, setPage] = useState<Page>("Applications");
  const [artifactTab, setArtifactTab] = useState<"Screenshots" | "Videos">("Screenshots");
  const [tests, setTests] = useState<TestCase[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [suite, setSuite] = useState("All Test Suites");
  const [search, setSearch] = useState("");

  // Artifacts and Runs state for project isolation
  const [artifacts, setArtifacts] = useState<ArtifactItem[]>([]);
  const [artifactsLoading, setArtifactsLoading] = useState(false);
  const [selectedRunFilter, setSelectedRunFilter] = useState<string>("all");
  const [previewImage, setPreviewImage] = useState<ArtifactItem | null>(null);
  const [projectRuns, setProjectRuns] = useState<RunRecord[]>([]);
  const [runTestResults, setRunTestResults] = useState<TestResultItem[]>([]);
  const [stepResults, setStepResults] = useState<StepExecutionResult[]>([]);

  // Projects are persisted by FastAPI in a local JSON registry.
  const [projects, setProjects] = useState<ProjectConfig[]>([]);
  const [activeProjectId, setActiveProjectId] = useState("apex-timesheet");
  const [projectsLoading, setProjectsLoading] = useState(false);
  const [projectSaving, setProjectSaving] = useState(false);
  const [projectError, setProjectError] = useState("");
  const [projectMessage, setProjectMessage] = useState("");
  const [editingProjectId, setEditingProjectId] = useState<string | null>(null);
  const [projectFormOpen, setProjectFormOpen] = useState(false);
  const emptyProjectForm: ProjectPayload = {
    name: "", project_type: "Web application", base_url: "https://",
    test_directory: "tests", default_environment: "QA", browser: "chromium",
    headless: true, capture_screenshots: true, capture_video: false,
    username_env_var: "", password_env_var: "",
    description: "", test_timeout_seconds: 60,
    navigation_timeout_seconds: 30, default_wait_ms: 500, auth_method: "form",
  };
  const [projectForm, setProjectForm] = useState<ProjectPayload>(emptyProjectForm);
  const activeProject = projects.find((project) => project.id === activeProjectId) ?? projects[0];

  // CSV scenario upload, validation, and selection state
  const [csvFile, setCsvFile] = useState<File | null>(null);
  const [csvValidation, setCsvValidation] = useState<CsvValidationResponse | null>(null);
  const [selectedScenarioIds, setSelectedScenarioIds] = useState<string[]>([]);
  const [csvLoading, setCsvLoading] = useState(false);
  const [csvExecuting, setCsvExecuting] = useState(false);
  const [csvError, setCsvError] = useState("");
  const [csvMessage, setCsvMessage] = useState("");

  const [backendStatus, setBackendStatus] = useState("Checking...");
  const [loadingTests, setLoadingTests] = useState(true);
  const [testError, setTestError] = useState("");

  const [running, setRunning] = useState(false);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [runStatus, setRunStatus] = useState("Idle");
  const [runSummary, setRunSummary] = useState<RunSummary | null>(null);
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const [startedAt, setStartedAt] = useState<number | null>(null);

  const [logs, setLogs] = useState<string[]>([
    "[System] Automation dashboard initialized.",
    "[System] Connecting to FastAPI...",
  ]);

  const [environment, setEnvironment] = useState("QA (Test)");
  const [browser, setBrowser] = useState("Chrome");
  const [headless, setHeadless] = useState(true);
  const [capture, setCapture] = useState(false);

  function addLog(message: string) {
    setLogs((old) => [
      ...old,
      `[${new Date().toLocaleTimeString()}] ${message}`,
    ]);
  }

  
async function loadTests(projectId?: string) {
  setLoadingTests(true);
  setTestError("");

  try {
    const health = await checkBackendHealth();
    setBackendStatus("Connected");
    addLog(`Backend connected: ${health.application ?? "APEX API"}`);

    const discovered = await getTestCases(projectId ?? activeProjectId);
    setTests(discovered);

    // Keep only tests the user has already selected.
    // Do not automatically select every discovered test.
    setSelected((old) =>
      old.filter((id) => discovered.some((test) => test.id === id)),
    );

    setTestError("");
    addLog(`Discovered ${discovered.length} pytest test cases.`);
  } catch (error) {
    const message =
      error instanceof Error ? error.message : "Unknown connection error";

    setBackendStatus("Disconnected");
    setTestError(message);
    addLog(`Unable to load tests: ${message}`);
  } finally {
    setLoadingTests(false);
  }
}


  function formatBytes(bytes?: number | null): string {
    if (!bytes || bytes === 0) return "0 B";
    const k = 1024;
    const sizes = ["B", "KB", "MB", "GB"];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return `${parseFloat((bytes / Math.pow(k, i)).toFixed(1))} ${sizes[i]}`;
  }

  function formatTimestamp(isoStr?: string | null): string {
    if (!isoStr) return "—";
    try {
      const d = new Date(isoStr);
      return d.toLocaleString([], {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
    } catch {
      return isoStr;
    }
  }

  async function loadArtifacts(type?: string) {
    if (!activeProjectId) return;
    setArtifactsLoading(true);
    try {
      const runId = selectedRunFilter === "all" ? undefined : selectedRunFilter;
      const list = await getProjectArtifacts(activeProjectId, runId, type);
      setArtifacts(list);
    } catch (err) {
      addLog(`Failed to load artifacts: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setArtifactsLoading(false);
    }
  }

  async function loadProjectRuns() {
    if (!activeProjectId) return;
    try {
      const runsList = await getProjectRuns(activeProjectId);
      setProjectRuns(runsList);
    } catch {
      // ignore
    }
  }

  async function enableVideoRecording() {
    if (!activeProject) return;
    try {
      await updateProject(activeProject.id, {
        name: activeProject.name,
        project_type: activeProject.project_type,
        base_url: activeProject.base_url,
        test_directory: activeProject.test_directory,
        default_environment: activeProject.default_environment,
        browser: activeProject.browser,
        headless: activeProject.headless,
        capture_screenshots: activeProject.capture_screenshots,
        capture_video: true,
        username_env_var: activeProject.username_env_var,
        password_env_var: activeProject.password_env_var,
      });
      await refreshProjects();
      addLog(`Video recording enabled for project: ${activeProject.name}`);
    } catch (err) {
      addLog(`Failed to enable video recording: ${err}`);
    }
  }

  async function refreshProjects() {
    setProjectsLoading(true);
    setProjectError("");
    try {
      const result = await getProjects();
      setProjects(result);
      setActiveProjectId((current) => result.some((project) => project.id === current)
        ? current : (result[0]?.id ?? "apex-timesheet"));
    } catch (error) {
      setProjectError(error instanceof Error ? error.message : "Unable to load projects.");
    } finally {
      setProjectsLoading(false);
    }
  }

  function startAddProject() {
    setEditingProjectId(null);
    setProjectForm({ ...emptyProjectForm });
    setProjectError("");
    setProjectMessage("");
    setProjectFormOpen(true);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function startEditProject(project: ProjectConfig) {
    setEditingProjectId(project.id);
    setProjectForm({
      name: project.name,
      project_type: project.project_type,
      base_url: project.base_url,
      test_directory: project.test_directory,
      default_environment: project.default_environment,
      browser: project.browser,
      headless: project.headless,
      capture_screenshots: project.capture_screenshots,
      capture_video: project.capture_video,
      username_env_var: project.username_env_var || "",
      password_env_var: project.password_env_var || "",
      description: project.description || "",
      test_timeout_seconds: project.test_timeout_seconds || 60,
      navigation_timeout_seconds: project.navigation_timeout_seconds || 30,
      default_wait_ms: project.default_wait_ms || 500,
      auth_method: project.auth_method || "form",
      is_active: project.is_active ?? true,
    });
    setProjectError("");
    setProjectMessage("");
    setProjectFormOpen(true);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  async function handleToggleProjectActive(projectId: string) {
    try {
      const res = await toggleProjectActive(projectId);
      await refreshProjects();
      setProjectMessage(res.message);
      addLog(`Application ${projectId} is now ${res.is_active ? "Active" : "Inactive"}.`);
    } catch (err: any) {
      setProjectError(err?.message || "Failed to toggle application status.");
    }
  }

  async function saveProject(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setProjectSaving(true);
    setProjectError("");
    setProjectMessage("");
    try {
      const saved = editingProjectId
        ? await updateProject(editingProjectId, projectForm)
        : await createProject(projectForm);
      const refreshed = await getProjects();
      setProjects(refreshed);
      setActiveProjectId(saved.id);
      setProjectFormOpen(false);
      setProjectMessage(editingProjectId ? "Application settings updated." : "Application added successfully.");
      addLog(`${editingProjectId ? "Updated" : "Added"} application: ${saved.name} (${saved.id}).`);
    } catch (error) {
      setProjectError(error instanceof Error ? error.message : "Unable to save application.");
    } finally {
      setProjectSaving(false);
    }
  }

  async function removeProject(project: ProjectConfig) {
    if (project.is_default) {
      setProjectError("The default application cannot be deleted.");
      return;
    }
    if (!window.confirm(`Delete application “${project.name}”? This removes its configuration record only.`)) return;
    setProjectError("");
    setProjectMessage("");
    try {
      await deleteProject(project.id);
      await refreshProjects();
      setProjectMessage(`Application “${project.name}” was removed.`);
      addLog(`Removed application configuration: ${project.name}.`);
    } catch (error) {
      setProjectError(error instanceof Error ? error.message : "Unable to delete application.");
    }
  }

  useEffect(() => {
    void refreshProjects();
  }, []);

  useEffect(() => {
    if (activeProjectId) {
      void loadTests(activeProjectId);
      void loadProjectRuns();
      if (page === "Screenshots & Recordings") {
        void loadArtifacts(artifactTab === "Videos" ? "video" : "screenshot");
      }
    }
  }, [activeProjectId, page, selectedRunFilter, artifactTab]);

  useEffect(() => {
    void loadTests();
    // Initial connection only; manual refresh uses the same function.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!activeRunId || !running) return;

    let cancelled = false;
    let timer: number | undefined;
    let previousLogs = "";

    async function poll() {
      try {
        const [status, logResult, steps] = await Promise.all([
          getRunStatus(activeRunId!),
          getRunLogs(activeRunId!),
          getRunStepResults(activeRunId!).catch(() => []),
        ]);

        if (cancelled) return;

        setRunStatus(status.status);

        if (steps && steps.length > 0) {
          setStepResults(steps);
        }

        if (status.summary) {
          setRunSummary(status.summary);
        }
        if (status.test_results) {
          setRunTestResults(status.test_results);
        }

        const currentLogs = logResult.logs ?? "";
        if (currentLogs !== previousLogs) {
          const delta = currentLogs.startsWith(previousLogs)
            ? currentLogs.slice(previousLogs.length)
            : currentLogs;

          const lines = delta
            .split(/\r?\n/)
            .filter((line) => line.trim());

          if (lines.length) setLogs((old) => [...old, ...lines]);
          previousLogs = currentLogs;
        }

        if (terminalStatuses.has(status.status.toLowerCase())) {
          setRunning(false);
          setRunStatus(status.status);
          if (status.summary) setRunSummary(status.summary);
          if (status.test_results) setRunTestResults(status.test_results);
          addLog(`Run finished with status: ${status.status}`);
          if (status.exit_code !== undefined) {
            addLog(`Pytest exit code: ${status.exit_code}`);
          }
          void loadProjectRuns();
          void getRunStepResults(activeRunId!).then((st) => st.length && setStepResults(st)).catch(() => {});
          if (page === "Screenshots & Recordings") void loadArtifacts(artifactTab === "Videos" ? "video" : "screenshot");
          return;
        }
      } catch (error) {
        if (!cancelled) {
          addLog(
            `Run polling failed: ${
              error instanceof Error ? error.message : "Unknown error"
            }`,
          );
        }
      }

      if (!cancelled) timer = window.setTimeout(() => void poll(), 1500);
    }

    void poll();

    return () => {
      cancelled = true;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [activeRunId, running]);

  useEffect(() => {
    if (!running || startedAt === null) return;

    const timer = window.setInterval(() => {
      setElapsedSeconds(Math.floor((Date.now() - startedAt) / 1000));
    }, 500);

    return () => window.clearInterval(timer);
  }, [running, startedAt]);

  const filteredTests = tests.filter((test) => {
    const matchesSuite =
      suite === "All Test Suites" || test.category === suite;
    const matchesSearch =
      `${test.name} ${test.category} ${test.id}`
        .toLowerCase()
        .includes(search.toLowerCase());

    return matchesSuite && matchesSearch;
  });

  const categories = [
    "All Test Suites",
    ...Array.from(new Set(tests.map((test) => test.category))),
  ];

  const allFilteredSelected =
    filteredTests.length > 0 &&
    filteredTests.every((test) => selected.includes(test.id));

  function toggleTest(id: string) {
    setSelected((old) =>
      old.includes(id)
        ? old.filter((item) => item !== id)
        : [...old, id],
    );
  }

  function toggleAll(checked: boolean) {
    const visibleIds = filteredTests.map((test) => test.id);

    setSelected((old) =>
      checked
        ? [...new Set([...old, ...visibleIds])]
        : old.filter((id) => !visibleIds.includes(id)),
    );
  }

  async function validateSelectedCsv(file: File) {
    setCsvFile(file);
    setCsvValidation(null);
    setSelectedScenarioIds([]);
    setCsvError("");
    setCsvMessage("");
    setCsvLoading(true);
    try {
      const result = await validateCsvScenarios(file);
      setCsvValidation(result);
      const rows = result.scenarios ?? [];
      setSelectedScenarioIds(rows.filter((row) => row.valid !== false).map((row) => row.TC_ID ?? row.tc_id ?? row.id).filter((id): id is string => Boolean(id)));
      setCsvMessage(result.valid ? `CSV validated: ${result.valid_rows ?? rows.length} valid scenario(s).` : "CSV loaded with validation errors. Review the messages below.");
      addLog(`CSV validation completed for ${file.name}.`);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unable to validate CSV.";
      setCsvError(message);
      addLog(`CSV validation failed: ${message}`);
    } finally {
      setCsvLoading(false);
    }
  }

  function toggleScenario(id: string) {
    setSelectedScenarioIds((current) => current.includes(id) ? current.filter((value) => value !== id) : [...current, id]);
  }

  async function executeSelectedCsv() {
    if (!csvFile || selectedScenarioIds.length === 0 || csvExecuting || running) return;
    setCsvExecuting(true);
    setCsvError("");
    setCsvMessage("");
    try {
      const response = await executeCsvScenarios(csvFile, selectedScenarioIds, activeProjectId);
      setCsvMessage(`Execution started. Run ID: ${response.run_id}`);
      setRunning(true);
      setRunStatus(response.status || "queued");
      setRunSummary(null);
      setElapsedSeconds(0);
      setStartedAt(Date.now());
      setActiveRunId(response.run_id);
      addLog(`CSV execution started for ${selectedScenarioIds.length} scenario(s). Run ID: ${response.run_id}`);
      setPage("Test Runs");
    } catch (error) {
      const message = error instanceof Error ? error.message : "Unable to execute selected CSV scenarios.";
      setCsvError(message);
      addLog(`CSV execution failed: ${message}`);
    } finally {
      setCsvExecuting(false);
    }
  }

  async function runTests() {
    if (running || !selected.length) return;

    if (backendStatus !== "Connected") {
      addLog("Cannot start a run: backend is disconnected.");
      return;
    }

    setRunning(true);
    setRunStatus("Submitting");
    setRunSummary(null);
    setElapsedSeconds(0);
    setStartedAt(Date.now());
    setActiveRunId(null);

    addLog(`Submitting ${selected.length} test(s) to pytest.`);
    addLog(
      `Selected UI settings: ${environment}, ${browser}, headless=${headless}, screenshots=${capture}.`,
    );

    try {
      const response = await startRun({ project_id: activeProjectId, test_ids: selected });
      setActiveRunId(response.run_id);
      setRunStatus(response.status);
      addLog(`Run ID: ${response.run_id}`);
      addLog(`Initial status: ${response.status}`);
    } catch (error) {
      setRunning(false);
      setRunStatus("error");
      addLog(
        `Could not start run: ${
          error instanceof Error ? error.message : "Unknown error"
        }`,
      );
    }
  }

  function openPage(nextPage: Page) {
    setPage(nextPage);
  }

  const passed = runSummary?.passed;
  const failed = runSummary?.failed;
  const skipped = runSummary?.skipped;
  const total = runSummary?.total;

  const duration = `${Math.floor(elapsedSeconds / 60)
    .toString()
    .padStart(2, "0")}:${(elapsedSeconds % 60)
    .toString()
    .padStart(2, "0")}`;

  const progress = running
    ? 12
    : terminalStatuses.has(runStatus.toLowerCase())
      ? 100
      : 0;

  return (
    <div className="automation-app">
      {page !== "Applications" && (
        <aside className="sidebar">
          <div className="brand">
            <div className="brand-mark">
              <FlaskConical size={22} />
            </div>
            <div>
              <strong>Veriqon</strong>
              <span>Automation Platform</span>
            </div>
          </div>

          <div className="workspace-switcher" onClick={() => openPage("Applications")} title="Click to switch application">
            <div className="workspace-icon">
              <Activity size={18} />
            </div>
            <div className="workspace-copy">
              <strong>{activeProject?.name ?? "No application selected"}</strong>
              <span>{activeProject?.default_environment ?? "QA"} workspace</span>
            </div>
            <span
              style={{
                fontSize: "0.7rem",
                padding: "2px 6px",
                borderRadius: 4,
                background: "rgba(255, 255, 255, 0.12)",
                color: "#FFFFFF",
                fontWeight: 600,
              }}
            >
              Switch
            </span>
          </div>

          <nav className="side-navigation">
            {navigation.map((group) => (
              <div className="nav-group" key={group.section}>
                <div className="nav-section-label">{group.section}</div>
                {group.items.map((item) => {
                  const Icon = item.icon;
                  return (
                    <button
                      key={item.label}
                      className={`nav-item ${page === item.label ? "active" : ""}`}
                      onClick={() => openPage(item.label)}
                    >
                      <Icon size={18} />
                      <span>{item.label}</span>
                      {item.label === "Test Suites" && (
                        <span className="nav-count">{tests.length}</span>
                      )}
                    </button>
                  );
                })}
              </div>
            ))}
          </nav>

          <div className="sidebar-bottom">
            <div className="backend-indicator">
              <span
                className={`status-dot ${
                  backendStatus === "Connected" ? "online" : "offline"
                }`}
              />
              <div>
                <strong>{backendStatus}</strong>
                <span>API connection</span>
              </div>
            </div>
            <div className="sidebar-version">Veriqon v2.0 · Local workspace</div>
          </div>
        </aside>
      )}

      <div className={`app-main ${page === "Applications" ? "app-main-full" : ""}`}>
        <header className="topbar">
          <div className="breadcrumbs">
            {page === "Applications" ? (
              <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                <div className="brand-mark" style={{ width: 32, height: 32, borderRadius: 8 }}>
                  <FlaskConical size={18} />
                </div>
                <strong style={{ fontSize: "1rem", letterSpacing: "-0.01em" }}>Veriqon Application Hub</strong>
              </div>
            ) : (
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span
                  style={{ cursor: "pointer", color: "var(--v-accent)", fontWeight: 600 }}
                  onClick={() => setPage("Applications")}
                  title="Return to Applications Manager"
                >
                  Applications
                </span>
                <span>/</span>
                <span style={{ fontWeight: 600, color: "var(--v-text)" }}>{activeProject?.name}</span>
                <span>/</span>
                <strong>{page}</strong>
              </div>
            )}
          </div>

          <div className="topbar-actions">
            {page !== "Applications" ? (
              <button
                className="button button-primary button-small change-project-button"
                onClick={() => { setProjectMessage(""); setProjectError(""); setProjectFormOpen(false); setPage("Applications"); }}
                title="Return to Applications Hub to choose or add another application"
              >
                <FolderKanban size={15} /> Change Application
              </button>
            ) : (
              <button
                type="button"
                className="button button-primary button-small"
                onClick={startAddProject}
              >
                <Plus size={15} /> Add Application
              </button>
            )}
            <span className="connection-label">
              <span
                className={`status-dot ${
                  backendStatus === "Connected" ? "online" : "offline"
                }`}
              />
              {backendStatus}
            </span>
            <button
              className="button button-secondary button-small"
              onClick={() => void loadTests()}
              disabled={loadingTests}
            >
              <RefreshCw size={15} />
              Refresh
            </button>
          </div>
        </header>

        <main className="page-content">
          {page === "Applications" && (
            <>
              <PageHeader
                eyebrow="APPLICATION REGISTRY"
                title="Applications"
                description="Manage applications under test, configure environments, timeouts, browser defaults, and encrypted credentials."
                action={<button type="button" className="button button-primary" onClick={startAddProject}><Plus size={16} /> Add application</button>}
              />

              {projectError && <div className="project-alert project-alert-error"><CircleAlert size={17} />{projectError}</div>}
              {projectMessage && <div className="project-alert project-alert-success"><CheckCircle2 size={17} />{projectMessage}</div>}

              {projectFormOpen && (
                <section className="card project-form-card">
                  <div className="project-form-heading">
                    <div className="project-form-icon"><FolderKanban size={21} /></div>
                    <div><h2>{editingProjectId ? "Edit application" : "Add an application"}</h2><p>Configure application parameters, execution environment, and credentials.</p></div>
                    <button type="button" className="project-icon-button" aria-label="Close form" onClick={() => setProjectFormOpen(false)}><X size={18} /></button>
                  </div>
                  <form onSubmit={(event) => void saveProject(event)}>
                    <div className="project-form-grid">
                      <label className="project-field"><span>Application name <b>*</b></span><input required maxLength={80} value={projectForm.name} onChange={(event) => setProjectForm({ ...projectForm, name: event.target.value })} placeholder="e.g. Customer Portal" /></label>
                      <label className="project-field"><span>Application type</span><select value={projectForm.project_type} onChange={(event) => setProjectForm({ ...projectForm, project_type: event.target.value as ProjectPayload["project_type"] })}><option>Web application</option><option>API application</option><option>Full-stack application</option></select></label>
                      <label className="project-field project-field-wide"><span>Base URL <b>*</b></span><input required type="url" value={projectForm.base_url} onChange={(event) => setProjectForm({ ...projectForm, base_url: event.target.value })} placeholder="https://application.example" /><small>The target URL of the application under test.</small></label>
                      <label className="project-field project-field-wide"><span>Description</span><input maxLength={500} value={projectForm.description || ""} onChange={(event) => setProjectForm({ ...projectForm, description: event.target.value })} placeholder="Application overview, test scope, or notes" /></label>
                      <label className="project-field"><span>Test directory</span><input required value={projectForm.test_directory} onChange={(event) => setProjectForm({ ...projectForm, test_directory: event.target.value })} placeholder="tests" /><small>Relative path inside your workspace.</small></label>
                      <label className="project-field"><span>Default environment</span><select value={projectForm.default_environment} onChange={(event) => setProjectForm({ ...projectForm, default_environment: event.target.value as ProjectPayload["default_environment"] })}><option>Development</option><option>QA</option><option>Staging</option><option>Production</option></select></label>
                      <label className="project-field"><span>Default browser</span><select value={projectForm.browser} onChange={(event) => setProjectForm({ ...projectForm, browser: event.target.value as ProjectPayload["browser"] })}><option value="chromium">Chromium</option><option value="firefox">Firefox</option><option value="webkit">WebKit</option></select></label>
                      <label className="project-field"><span>Test timeout (seconds)</span><input type="number" min={5} max={600} value={projectForm.test_timeout_seconds || 60} onChange={(event) => setProjectForm({ ...projectForm, test_timeout_seconds: Number(event.target.value) })} /></label>
                      <label className="project-field"><span>Navigation timeout (seconds)</span><input type="number" min={5} max={300} value={projectForm.navigation_timeout_seconds || 30} onChange={(event) => setProjectForm({ ...projectForm, navigation_timeout_seconds: Number(event.target.value) })} /></label>
                      <label className="project-field"><span>Default wait (ms)</span><input type="number" min={0} max={10000} value={projectForm.default_wait_ms || 500} onChange={(event) => setProjectForm({ ...projectForm, default_wait_ms: Number(event.target.value) })} /></label>
                    </div>

                    <div className="project-options">
                      <label><input type="checkbox" checked={projectForm.is_active !== false} onChange={(event) => setProjectForm({ ...projectForm, is_active: event.target.checked })} /><span><strong>Active application</strong><small>Enable running tests and scenarios against this application</small></span></label>
                      <label><input type="checkbox" checked={projectForm.headless} onChange={(event) => setProjectForm({ ...projectForm, headless: event.target.checked })} /><span><strong>Headless mode</strong><small>Run browser without opening a visible window</small></span></label>
                      <label><input type="checkbox" checked={projectForm.capture_screenshots} onChange={(event) => setProjectForm({ ...projectForm, capture_screenshots: event.target.checked })} /><span><strong>Capture screenshots</strong><small>Save visual evidence during test runs</small></span></label>
                      <label><input type="checkbox" checked={projectForm.capture_video} onChange={(event) => setProjectForm({ ...projectForm, capture_video: event.target.checked })} /><span><strong>Capture video</strong><small>Record full browser session videos</small></span></label>
                    </div>

                    <div className="project-secrets-note"><Settings2 size={17} /><div><strong>Credential references (optional)</strong><p>Enter environment-variable names for fallback lookup, or configure encrypted credentials directly below.</p></div></div>
                    <div className="project-form-grid project-credentials-grid">
                      <label className="project-field"><span>Username environment variable</span><input value={projectForm.username_env_var} onChange={(event) => setProjectForm({ ...projectForm, username_env_var: event.target.value.replace(/[^A-Za-z0-9_]/g, "") })} placeholder="APEX_QA_USERNAME" /></label>
                      <label className="project-field"><span>Password/token environment variable</span><input value={projectForm.password_env_var} onChange={(event) => setProjectForm({ ...projectForm, password_env_var: event.target.value.replace(/[^A-Za-z0-9_]/g, "") })} placeholder="APEX_QA_PASSWORD" /></label>
                    </div>

                    <div className="project-form-actions">
                      <button type="button" className="button button-secondary" onClick={() => setProjectFormOpen(false)}>Cancel</button>
                      <button type="submit" className="button button-primary" disabled={projectSaving}>
                        {projectSaving ? <LoaderCircle className="spin" size={16} /> : <Save size={16} />}
                        {projectSaving ? "Saving…" : editingProjectId ? "Save changes" : "Add application"}
                      </button>
                    </div>

                    {editingProjectId && (
                      <div style={{ marginTop: 28, borderTop: "1px solid var(--vq-border)", paddingTop: 20 }}>
                        <CredentialsPanel projectId={editingProjectId} projectName={projectForm.name || "Application"} />
                      </div>
                    )}
                  </form>
                </section>
              )}

              <div className="projects-toolbar">
                <div>
                  <strong>{projects.length} registered application{projects.length === 1 ? "" : "s"}</strong>
                  <span>Stored securely in PostgreSQL database</span>
                </div>
                <button className="button button-secondary button-small" onClick={() => void refreshProjects()} disabled={projectsLoading}>
                  {projectsLoading ? <LoaderCircle className="spin" size={15} /> : <RefreshCw size={15} />} Refresh
                </button>
              </div>

              {projectsLoading && projects.length === 0 ? (
                <section className="card projects-empty"><LoaderCircle className="spin" size={22} /><span>Loading applications…</span></section>
              ) : projects.length === 0 ? (
                <section className="card projects-empty"><FolderKanban size={28} /><strong>No applications yet</strong><span>Add your first application to begin testing.</span></section>
              ) : (
                <div className="projects-grid">
                  {projects.map((project) => (
                    <article className={`project-card ${project.id === activeProjectId ? "project-card-active" : ""}`} key={project.id} style={{ opacity: project.is_active === false ? 0.75 : 1 }}>
                      <div className="project-card-top">
                        <div className="project-card-icon"><FolderKanban size={21} /></div>
                        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                          <span
                            className="badge"
                            style={{
                              background: project.is_active !== false ? "rgba(16, 185, 129, 0.12)" : "rgba(239, 68, 68, 0.12)",
                              color: project.is_active !== false ? "#10B981" : "#EF4444",
                              padding: "3px 9px",
                              borderRadius: 6,
                              fontSize: "0.75rem",
                              fontWeight: 600,
                            }}
                          >
                            {project.is_active !== false ? "Active" : "Inactive"}
                          </span>
                          {project.id === activeProjectId && (
                            <span className="project-status project-status-active">Selected</span>
                          )}
                        </div>
                      </div>
                      <h3>{project.name}</h3>
                      <p className="project-card-type">{project.project_type} · {project.default_environment}</p>
                      <div className="project-card-url"><span>BASE URL</span><code title={project.base_url}>{project.base_url}</code></div>
                      <div className="project-card-meta"><span><b>Test directory</b><code>{project.test_directory}</code></span><span><b>Browser</b><code>{project.browser}</code></span></div>
                      <div className="project-card-footer">
                        <button className="button button-primary button-small open-project-button" onClick={() => { setActiveProjectId(project.id); setProjectMessage(""); setProjectError(""); setPage("Overview"); }}>
                          <FolderKanban size={15} /> Open Workspace <span aria-hidden="true">→</span>
                        </button>
                        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
                          <button
                            type="button"
                            className="button button-secondary button-small"
                            title={project.is_active !== false ? "Deactivate application" : "Activate application"}
                            onClick={() => void handleToggleProjectActive(project.id)}
                            style={{ fontSize: "0.75rem", padding: "4px 8px" }}
                          >
                            {project.is_active !== false ? "Deactivate" : "Activate"}
                          </button>
                          <button
                            type="button"
                            className="button button-secondary button-small"
                            title="Manage encrypted credentials"
                            onClick={() => { setActiveProjectId(project.id); setPage("Credentials"); }}
                            style={{ padding: "4px 8px" }}
                          >
                            <KeyRound size={13} />
                          </button>
                          <button
                            type="button"
                            className="project-icon-button"
                            aria-label={`Edit ${project.name}`}
                            title="Edit application configuration"
                            onClick={() => startEditProject(project)}
                          >
                            <Pencil size={15} />
                          </button>
                          <button
                            type="button"
                            className="project-icon-button project-delete-button"
                            aria-label={`Delete ${project.name}`}
                            title={project.is_default ? "Default application cannot be deleted" : "Delete application"}
                            disabled={project.is_default}
                            onClick={() => void removeProject(project)}
                          >
                            <Trash2 size={15} />
                          </button>
                        </div>
                      </div>
                    </article>
                  ))}
                </div>
              )}
            </>
          )}

          {page === "Scenario Builder" && (
            <ScenarioBuilder
              projectId={activeProjectId}
              projectName={activeProject?.name || "Current Application"}
              onRunTriggered={(runId) => {
                setActiveRunId(runId);
                setRunning(true);
                setElapsedSeconds(0);
                setStartedAt(Date.now());
                setStepResults([]);
                setPage("Test Runs");
              }}
            />
          )}

          {page === "Credentials" && (
            <CredentialsPanel
              projectId={activeProjectId}
              projectName={activeProject?.name || "Current Application"}
            />
          )}

          {page === "Overview" && (
            <>
              <PageHeader
                eyebrow="WORKSPACE OVERVIEW"
                title="Overview"
                description="Monitor test runs, track execution status, and inspect test evidence."
                action={
                  <button
                    className="button button-primary"
                    onClick={() => openPage("Test Suites")}
                  >
                    <ListChecks size={17} />
                    Browse test cases
                  </button>
                }
              />

              {testError && (
                <div className="alert alert-error">
                  <CircleAlert size={18} />
                  <span>{testError}</span>
                </div>
              )}

              <div className="metric-grid">
                <MetricCard
                  icon={<ListChecks />}
                  label="Discovered tests"
                  value={loadingTests ? "…" : tests.length}
                  detail="Collected from pytest"
                  tone="blue"
                />
                <MetricCard
                  icon={<CheckCircle2 />}
                  label="Passed"
                  value={passed ?? "—"}
                  detail="Latest run"
                  tone="green"
                />
                <MetricCard
                  icon={<XCircle />}
                  label="Failed"
                  value={failed ?? "—"}
                  detail="Latest run"
                  tone="red"
                />
                <MetricCard
                  icon={<Clock3 />}
                  label="Execution time"
                  value={activeRunId ? duration : "—"}
                  detail={running ? "Run in progress" : "Latest run timer"}
                  tone="purple"
                />
              </div>

              <div className="dashboard-grid">
                <section className="card quick-run-card">
                  <CardHeading
                    icon={<Play />}
                    title="Quick execution"
                    description="Choose your test cases and launch a run."
                  />

                  <div className="quick-run-fields">
                    <label className="field">
                      <span>Test suite</span>
                      <select
                        value={suite}
                        onChange={(event) => setSuite(event.target.value)}
                      >
                        {categories.map((category) => (
                          <option key={category}>{category}</option>
                        ))}
                      </select>
                    </label>

                    <div className="selection-summary">
                      <div className="selection-number">{selected.length}</div>
                      <div>
                        <strong>Tests selected</strong>
                        <span>of {tests.length} discovered tests</span>
                      </div>
                    </div>

                    <div className="settings-inline">
                      <label className="toggle-line">
                        <input
                          type="checkbox"
                          checked={headless}
                          onChange={(event) => setHeadless(event.target.checked)}
                        />
                        Headless mode
                      </label>
                      <label className="toggle-line">
                        <input
                          type="checkbox"
                          checked={capture}
                          onChange={(event) => setCapture(event.target.checked)}
                        />
                        Capture screenshots
                      </label>
                    </div>

                    <button
                      className="button button-primary button-wide"
                      disabled={
                        running ||
                        !selected.length ||
                        loadingTests ||
                        backendStatus !== "Connected"
                      }
                      onClick={() => void runTests()}
                    >
                      {running ? (
                        <LoaderCircle className="spin" size={17} />
                      ) : (
                        <Play size={17} fill="currentColor" />
                      )}
                      {running ? "Tests running…" : "Run selected tests"}
                    </button>
                    <p className="muted-text">
                      Run status: <strong>{runStatus}</strong>
                    </p>
                  </div>
                </section>

                <section className="card latest-run-card">
                  <CardHeading
                    icon={<Activity />}
                    title="Latest execution"
                    description="Current or most recent run."
                    action={
                      <button
                        className="text-button"
                        onClick={() => openPage("Test Runs")}
                      >
                        View details
                      </button>
                    }
                  />

                  {activeRunId ? (
                    <div className="latest-run-content">
                      <div className="run-status-row">
                        <span className="run-id-label">RUN ID</span>
                        <StatusPill status={runStatus} />
                      </div>
                      <code className="run-id">{activeRunId}</code>

                      <div className="progress-label">
                        <span>{running ? "Executing tests" : "Run progress"}</span>
                        <span>{progress}%</span>
                      </div>
                      <div className="progress-track">
                        <div
                          className="progress-fill"
                          style={{ width: `${progress}%` }}
                        />
                      </div>

                      <div className="run-stat-grid">
                        <SmallStat label="Passed" value={passed ?? "—"} />
                        <SmallStat label="Failed" value={failed ?? "—"} />
                        <SmallStat label="Skipped" value={skipped ?? "—"} />
                      </div>
                    </div>
                  ) : (
                    <EmptyState
                      icon={<Gauge />}
                      title="Ready for your first run"
                      description="Select test cases and start execution to see live results here."
                    />
                  )}
                </section>

                <section className="card suite-overview-card">
                  <CardHeading
                    icon={<Archive />}
                    title="Test suite overview"
                    description="Tests grouped by their source module."
                    action={
                      <button
                        className="text-button"
                        onClick={() => openPage("Test Suites")}
                      >
                        View suites
                      </button>
                    }
                  />

                  <div className="suite-list">
                    {categories
                      .filter((category) => category !== "All Test Suites")
                      .map((category) => {
                        const count = tests.filter(
                          (test) => test.category === category,
                        ).length;

                        return (
                          <button
                            className="suite-row"
                            key={category}
                            onClick={() => {
                              setSuite(category);
                              openPage("Test Suites");
                            }}
                          >
                            <span className="suite-icon">
                              <FlaskConical size={17} />
                            </span>
                            <span className="suite-name">{category}</span>
                            <span className="suite-count">{count} tests</span>
                          </button>
                        );
                      })}
                  </div>
                </section>

                <section className="card log-preview-card">
                  <CardHeading
                    icon={<SquareTerminal />}
                    title="Recent console output"
                    description="Latest messages from the automation workspace."
                    action={
                      <button
                        className="text-button"
                        onClick={() => openPage("Test Runs")}
                      >
                        View logs
                      </button>
                    }
                  />
                  <LogViewer logs={logs.slice(-8)} compact />
                </section>
              </div>
            </>
          )}

          {page === "Test Suites" && (
            <>
              <PageHeader
                eyebrow="TEST MANAGEMENT"
                title="Test suites"
                description="Discover, search, filter, and select real pytest tests."
                action={
                  <button
                    className="button button-primary"
                    disabled={
                      running ||
                      !selected.length ||
                      backendStatus !== "Connected"
                    }
                    onClick={() => void runTests()}
                  >
                    <Play size={17} />
                    Run {selected.length} selected
                  </button>
                }
              />

              <section className="card">
                <div className="filter-toolbar">
                  <div className="search-field">
                    <Search size={17} />
                    <input
                      value={search}
                      onChange={(event) => setSearch(event.target.value)}
                      placeholder="Search tests, IDs, or categories…"
                    />
                  </div>

                  <select
                    value={suite}
                    onChange={(event) => setSuite(event.target.value)}
                    aria-label="Filter by test suite"
                  >
                    {categories.map((category) => (
                      <option key={category}>{category}</option>
                    ))}
                  </select>

                  <button
                    className="button button-secondary"
                    onClick={() => toggleAll(!allFilteredSelected)}
                  >
                    {allFilteredSelected ? "Deselect visible" : "Select visible"}
                  </button>
                </div>

                <div className="table-summary">
                  <span>
                    {filteredTests.length} visible · {tests.length} discovered
                  </span>
                  <span>{selected.length} selected</span>
                </div>

                <div className="data-table-wrap">
                  <table className="data-table">
                    <thead>
                      <tr>
                        <th className="check-cell">
                          <input
                            type="checkbox"
                            checked={allFilteredSelected}
                            onChange={(event) =>
                              toggleAll(event.target.checked)
                            }
                            aria-label="Select all visible tests"
                          />
                        </th>
                        <th>Test ID</th>
                        <th>Test name</th>
                        <th>Suite</th>
                        <th>Source</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredTests.map((test) => (
                        <tr key={test.id}>
                          <td className="check-cell">
                            <input
                              type="checkbox"
                              checked={selected.includes(test.id)}
                              onChange={() => toggleTest(test.id)}
                              aria-label={`Select ${test.displayId}`}
                            />
                          </td>
                          <td>
                            <span className="test-id">{test.displayId}</span>
                          </td>
                          <td>
                            <strong className="test-name">{test.name}</strong>
                            <code className="node-id">{test.id}</code>
                          </td>
                          <td>
                            <span className="category-pill">{test.category}</span>
                          </td>
                          <td className="source-cell">
                            {test.id.split("::")[0]}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>

                  {!loadingTests && filteredTests.length === 0 && (
                    <EmptyState
                      icon={<Search />}
                      title="No matching tests"
                      description="Try another search term or test suite."
                    />
                  )}
                </div>
              </section>
            </>
          )}

          {page === "CSV Scenarios" && (
            <>
              <PageHeader
                eyebrow="SCENARIO WORKSPACE"
                title="CSV scenario runner"
                description="Upload a scenario CSV, validate its structure, select supported scenarios, and run them through the existing Playwright/pytest runner."
              />

              <section className="card csv-upload-card">
                <div className="csv-upload-heading">
                  <div>
                    <h3>Upload test scenarios</h3>
                    <p>Required columns: TC_ID, Scenario, Preconditions, Steps, Expected_Result, Priority.</p>
                  </div>
                  <span className="csv-file-type">.CSV</span>
                </div>
                <label className="csv-file-drop" htmlFor="scenario-csv-file">
                  <FileText size={25} />
                  <strong>{csvFile ? csvFile.name : "Choose a CSV file"}</strong>
                  <span>{csvFile ? `${(csvFile.size / 1024).toFixed(1)} KB · Choose another file to replace` : "Select a scenario CSV from your computer (max 2 MB)."}</span>
                  <input id="scenario-csv-file" type="file" accept=".csv,text/csv" onChange={(event) => { const file = event.currentTarget.files?.[0]; if (file) void validateSelectedCsv(file); event.currentTarget.value = ""; }} />
                </label>
                <div className="csv-actions">
                  <button className="button button-primary" disabled={!csvFile || csvLoading || csvExecuting} onClick={() => csvFile && void validateSelectedCsv(csvFile)}>
                    {csvLoading ? <LoaderCircle className="spin" size={16} /> : <RefreshCw size={16} />}
                    {csvLoading ? "Validating…" : "Validate CSV"}
                  </button>
                  <button className="button button-secondary" disabled={!csvFile || !csvValidation || selectedScenarioIds.length === 0 || csvExecuting || running} onClick={() => void executeSelectedCsv()}>
                    {csvExecuting ? <LoaderCircle className="spin" size={16} /> : <Play size={16} />}
                    {csvExecuting ? "Starting…" : `Run selected (${selectedScenarioIds.length})`}
                  </button>
                </div>
                {csvError && <div className="csv-message error"><CircleAlert size={16} />{csvError}</div>}
                {csvMessage && <div className="csv-message success"><CheckCircle2 size={16} />{csvMessage}</div>}
                {csvValidation?.errors?.length ? <div className="csv-validation-errors"><strong>Validation issues</strong><ul>{csvValidation.errors.map((error, index) => <li key={`${index}-${error}`}>{typeof error === "string" ? error : JSON.stringify(error)}</li>)}</ul></div> : null}
              </section>

              {csvValidation && (
                <section className="card csv-scenarios-card">
                  <div className="csv-scenarios-toolbar">
                    <div>
                      <h3>Scenario selection</h3>
                      <p>{csvValidation.total_rows ?? csvValidation.scenarios?.length ?? 0} row(s) · {csvValidation.valid_rows ?? 0} valid · {selectedScenarioIds.length} selected</p>
                    </div>
                    <div className="csv-selection-actions">
                      <button className="button button-secondary button-small" onClick={() => setSelectedScenarioIds((csvValidation.scenarios ?? []).map((row) => row.TC_ID ?? row.tc_id ?? row.id).filter((id): id is string => Boolean(id) && (csvValidation.scenarios ?? []).some((row) => (row.TC_ID ?? row.tc_id ?? row.id) === id && row.valid !== false)))}>Select valid</button>
                      <button className="button button-secondary button-small" onClick={() => setSelectedScenarioIds([])}>Clear</button>
                    </div>
                  </div>
                  <div className="table-wrap csv-table-wrap">
                    <table className="data-table csv-scenarios-table">
                      <thead><tr><th>Select</th><th>TC ID</th><th>Scenario</th><th>Preconditions</th><th>Steps</th><th>Expected result</th><th>Priority</th></tr></thead>
                      <tbody>
                        {(csvValidation.scenarios ?? []).map((row, index) => {
                          const id = row.TC_ID ?? row.tc_id ?? row.id ?? `row-${index}`;
                          const supported = row.valid !== false && Boolean(row.TC_ID ?? row.tc_id ?? row.id);
                          return <tr key={`${id}-${index}`}>
                            <td><input aria-label={`Select ${id}`} type="checkbox" checked={selectedScenarioIds.includes(id)} disabled={!supported} onChange={() => toggleScenario(id)} /></td>
                            <td><strong>{id}</strong></td>
                            <td>{row.Scenario ?? row.scenario ?? "—"}</td>
                            <td>{row.Preconditions ?? row.preconditions ?? "—"}</td>
                            <td>{row.Steps ?? row.steps ?? "—"}</td>
                            <td>{row.Expected_Result ?? row.expected_result ?? "—"}</td>
                            <td><span className={`priority-pill priority-${String(row.Priority ?? row.priority ?? "low").toLowerCase()}`}>{row.Priority ?? row.priority ?? "—"}</span></td>
                          </tr>;
                        })}
                      </tbody>
                    </table>
                  </div>
                  <p className="csv-support-note"><CircleAlert size={15} /> Only scenario IDs configured in the backend mapping can execute. CSV descriptions are not automatically converted into Playwright steps.</p>
                </section>
              )}
            </>
          )}

          {page === "Test Runs" && (
            <>
              <PageHeader
                eyebrow="EXECUTION"
                title="Test Runs"
                description="Launch test suites or visual scenarios and monitor live execution progress and step results."
              />

              <div className="dashboard-grid execution-page-grid">
                <section className="card">
                  <CardHeading
                    icon={<Play />}
                    title="Execution configuration"
                    description="These controls describe the selected run configuration."
                  />

                  <div className="form-stack">
                    <label className="field">
                      <span>Environment</span>
                      <select
                        value={environment}
                        onChange={(event) => setEnvironment(event.target.value)}
                      >
                        <option>QA (Test)</option>
                        <option>UAT</option>
                        <option>Local</option>
                      </select>
                    </label>

                    <label className="field">
                      <span>Browser preference</span>
                      <select
                        value={browser}
                        onChange={(event) => setBrowser(event.target.value)}
                      >
                        <option>Chrome</option>
                        <option>Firefox</option>
                        <option>WebKit</option>
                      </select>
                    </label>

                    <label className="toggle-line">
                      <input
                        type="checkbox"
                        checked={headless}
                        onChange={(event) => setHeadless(event.target.checked)}
                      />
                      Headless mode
                    </label>

                    <label className="toggle-line">
                      <input
                        type="checkbox"
                        checked={capture}
                        onChange={(event) => setCapture(event.target.checked)}
                      />
                      Capture screenshots
                    </label>

                    <div className="selection-summary">
                      <div className="selection-number">{selected.length}</div>
                      <div>
                        <strong>Tests selected</strong>
                        <span>Choose tests from Test Suites.</span>
                      </div>
                    </div>

                    <button
                      className="button button-primary button-wide"
                      disabled={
                        running ||
                        !selected.length ||
                        backendStatus !== "Connected"
                      }
                      onClick={() => void runTests()}
                    >
                      <Play size={17} />
                      {running ? "Running…" : "Start execution"}
                    </button>

                    <p className="muted-text">
                      Note: browser, environment, headless, and screenshot
                      controls are currently UI preferences. They are not
                      passed to the runner by the existing API request.
                    </p>
                  </div>
                </section>

                <section className="card">
                  <CardHeading
                    icon={<Activity />}
                    title="Run status"
                    description="Current run and summary from the backend."
                  />

                  {activeRunId ? (
                    <div className="latest-run-content">
                      <div className="run-status-row">
                        <span className="run-id-label">STATUS</span>
                        <StatusPill status={runStatus} />
                      </div>
                      <code className="run-id">{activeRunId}</code>

                      <div className="progress-label">
                        <span>{running ? "Execution active" : "Execution state"}</span>
                        <span>{progress}%</span>
                      </div>
                      <div className="progress-track">
                        <div
                          className="progress-fill"
                          style={{ width: `${progress}%` }}
                        />
                      </div>

                      <div className="run-stat-grid">
                        <SmallStat label="Passed" value={passed ?? "—"} />
                        <SmallStat label="Failed" value={failed ?? "—"} />
                        <SmallStat label="Skipped" value={skipped ?? "—"} />
                      </div>
                      <p className="muted-text">Elapsed time: {duration}</p>
                    </div>
                  ) : (
                    <EmptyState
                      icon={<Clock3 />}
                      title="No active run"
                      description="Start an execution to see status and results."
                    />
                  )}
                </section>
              </div>

              {activeRunId && stepResults.length > 0 && (
                <ScenarioExecutionView
                  runId={activeRunId}
                  stepResults={stepResults}
                  status={runStatus}
                  runSummary={runSummary}
                  videoArtifact={artifacts.find((a) => a.artifact_type === "video" && a.run_id === activeRunId)}
                  onPreviewImage={(item) => setPreviewImage(item)}
                />
              )}

              <section className="card section-gap">
                <CardHeading
                  icon={<SquareTerminal />}
                  title="Live execution logs"
                  description="Output polled from the FastAPI runner."
                  action={
                    <button
                      className="button button-secondary button-small"
                      onClick={() => setLogs([])}
                    >
                      Clear logs
                    </button>
                  }
                />
                <LogViewer logs={logs} />
              </section>
            </>
          )}

          {page === "Test Evidence" && (
            <>
              <PageHeader
                eyebrow="EVIDENCE"
                title="Test Evidence"
                description="Review test run outcomes, summary reports, and granular assertion results."
              />

              <div className="metric-grid">
                <MetricCard
                  icon={<ListChecks />}
                  label="Total"
                  value={total ?? "—"}
                  detail="Latest run"
                  tone="blue"
                />
                <MetricCard
                  icon={<CheckCircle2 />}
                  label="Passed"
                  value={passed ?? "—"}
                  detail="Latest run"
                  tone="green"
                />
                <MetricCard
                  icon={<XCircle />}
                  label="Failed"
                  value={failed ?? "—"}
                  detail="Latest run"
                  tone="red"
                />
                <MetricCard
                  icon={<CircleAlert />}
                  label="Skipped"
                  value={skipped ?? "—"}
                  detail="Latest run"
                  tone="purple"
                />
              </div>

              <section className="card section-gap">
                <CardHeading
                  icon={<FileBarChart />}
                  title="Latest report"
                  description="Summary returned by the backend."
                />

                {runSummary ? (
                  <div className="report-result">
                    <CheckCircle2 size={24} />
                    <div>
                      <strong>Run summary received</strong>
                      <span>
                        Total {total ?? 0} · Passed {passed ?? 0} · Failed{" "}
                        {failed ?? 0} · Skipped {skipped ?? 0}
                      </span>
                    </div>
                  </div>
                ) : (
                  <EmptyState
                    icon={<FileText />}
                    title="Detailed summary not available yet"
                    description="The run has a status and JUnit XML output, but the backend currently returns a null JSON summary. Report correlation needs to be fixed to show these metrics here."
                  />
                )}

                {activeRunId && (
                  <div className="report-run-id">
                    <span>Latest run ID</span>
                    <code>{activeRunId}</code>
                  </div>
                )}

                {runTestResults.length > 0 && (
                  <div style={{ marginTop: 24 }}>
                    <h4 style={{ margin: "0 0 12px 0", color: "var(--vq-text)" }}>
                      Individual Test Results ({runTestResults.length})
                    </h4>
                    <table className="test-results-table">
                      <thead>
                        <tr>
                          <th>Status</th>
                          <th>Test ID</th>
                          <th>Duration</th>
                        </tr>
                      </thead>
                      <tbody>
                        {runTestResults.map((tr) => (
                          <tr key={tr.id}>
                            <td style={{ width: 110 }}>
                              <span className={`status-badge-${tr.status.toLowerCase()}`}>
                                {tr.status}
                              </span>
                            </td>
                            <td>
                              <code>{tr.test_id}</code>
                              {tr.error_message && (
                                <pre className="test-error-block">{tr.error_message}</pre>
                              )}
                            </td>
                            <td style={{ width: 90, color: "var(--vq-muted)" }}>
                              {tr.duration_seconds ? `${tr.duration_seconds.toFixed(2)}s` : "—"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </section>
            </>
          )}

          {page === "Screenshots & Recordings" && (
            <>
              <PageHeader
                eyebrow="EVIDENCE"
                title="Screenshots & Recordings"
                description={`Review Playwright test captures, screenshots, and browser recordings for ${activeProject?.name ?? "the selected application"}.`}
                action={
                  <div style={{ display: "flex", gap: 8 }}>
                    <button
                      className="button button-secondary"
                      onClick={() => void loadArtifacts(artifactTab === "Videos" ? "video" : "screenshot")}
                    >
                      <RefreshCw size={15} />
                      Refresh {artifactTab.toLowerCase()}
                    </button>
                  </div>
                }
              />

              <div className="tab-pill-bar">
                <button
                  type="button"
                  className={`tab-pill ${artifactTab === "Screenshots" ? "active" : ""}`}
                  onClick={() => setArtifactTab("Screenshots")}
                >
                  <Camera size={16} />
                  Screenshots
                </button>
                <button
                  type="button"
                  className={`tab-pill ${artifactTab === "Videos" ? "active" : ""}`}
                  onClick={() => setArtifactTab("Videos")}
                >
                  <Video size={16} />
                  Video Recordings
                </button>
              </div>

              {artifactTab === "Videos" && !activeProject?.capture_video && (
                <div className="artifact-banner-notice">
                  <div className="artifact-banner-copy">
                    <CircleAlert size={18} color="#3b82f6" />
                    <span>
                      Video recording is currently <strong>disabled</strong> for <strong>{activeProject?.name}</strong>.
                      Enable it to automatically save video recordings for upcoming test runs.
                    </span>
                  </div>
                  <button className="button button-primary" onClick={() => void enableVideoRecording()}>
                    <Film size={15} />
                    Enable video recording
                  </button>
                </div>
              )}

              <div className="artifact-toolbar">
                <div className="artifact-toolbar-left">
                  <span className="artifact-filter-label">
                    {artifactTab === "Videos" ? <Film size={15} /> : <Camera size={15} />}
                    Filter by run:
                  </span>
                  <select
                    className="artifact-filter-select"
                    value={selectedRunFilter}
                    onChange={(e) => setSelectedRunFilter(e.target.value)}
                  >
                    <option value="all">All runs ({projectRuns.length} runs recorded)</option>
                    {projectRuns.map((r) => (
                      <option key={r.id} value={r.id}>
                        {formatTimestamp(r.created_at)} — {r.id?.slice(0, 8)} ({r.status})
                      </option>
                    ))}
                  </select>
                </div>
                <div className="artifact-toolbar-right">
                  <small style={{ color: "var(--vq-muted)" }}>
                    {artifacts.length} {artifactTab === "Videos" ? "video recording" : "screenshot"}{artifacts.length === 1 ? "" : "s"} found
                  </small>
                </div>
              </div>

              {artifactsLoading ? (
                <div style={{ textAlign: "center", padding: "60px 0" }}>
                  <LoaderCircle className="spinner spin" size={28} />
                  <p style={{ marginTop: 12, color: "var(--vq-muted)" }}>Loading {artifactTab.toLowerCase()}...</p>
                </div>
              ) : artifacts.length === 0 ? (
                <section className="card artifact-empty-card">
                  <EmptyState
                    icon={artifactTab === "Videos" ? <Video /> : <Camera />}
                    title={`No ${artifactTab.toLowerCase()} found`}
                    description={
                      artifactTab === "Videos"
                        ? (!activeProject?.capture_video
                            ? `Video capture is currently turned off for ${activeProject?.name}. Enable video recording above and run your tests.`
                            : "No videos have been recorded yet for this application. Execute a test run to capture browser video recordings.")
                        : "Screenshots captured during test execution or on failure will appear here."
                    }
                  />
                  <div style={{ display: "flex", gap: 10, justifyContent: "center" }}>
                    {artifactTab === "Videos" && !activeProject?.capture_video && (
                      <button className="button button-primary" onClick={() => void enableVideoRecording()}>
                        <Film size={15} />
                        Enable video recording
                      </button>
                    )}
                    <button className="button button-secondary" onClick={() => openPage("Test Suites")}>
                      <Play size={15} />
                      Run tests now
                    </button>
                  </div>
                </section>
              ) : artifactTab === "Videos" ? (
                <div className="video-grid">
                  {artifacts.map((art) => (
                    <div key={art.id} className="video-card">
                      <div className="video-player-wrap">
                        <video
                          controls
                          preload="metadata"
                          className="artifact-video-player"
                          src={`${API_BASE_URL}${art.url}`}
                        >
                          Your browser does not support the video tag.
                        </video>
                      </div>
                      <div className="video-card-body">
                        <strong className="artifact-card-title" title={art.filename}>
                          {art.filename}
                        </strong>
                        <div className="artifact-card-meta">
                          <span>Run: <code>{art.run_id ? art.run_id.slice(0, 13) + "..." : "—"}</code></span>
                          <span>Size: {formatBytes(art.size_bytes)} · {formatTimestamp(art.created_at)}</span>
                        </div>
                        <div className="artifact-card-actions">
                          <a
                            href={`${API_BASE_URL}${art.url}`}
                            target="_blank"
                            rel="noreferrer"
                            className="artifact-action-btn"
                          >
                            <ExternalLink size={13} />
                            Open in tab
                          </a>
                          <a
                            href={`${API_BASE_URL}${art.download_url}`}
                            download={art.filename}
                            className="artifact-action-btn"
                          >
                            <Download size={13} />
                            Download
                          </a>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="artifact-grid">
                  {artifacts.map((art) => (
                    <div key={art.id} className="artifact-card">
                      <div className="artifact-thumb-wrap" onClick={() => setPreviewImage(art)}>
                        <img
                          src={`${API_BASE_URL}${art.url}`}
                          alt={art.filename}
                          className="artifact-thumb"
                          loading="lazy"
                        />
                        <div className="artifact-thumb-overlay">
                          <Eye size={16} />
                          Preview
                        </div>
                      </div>
                      <div className="artifact-card-body">
                        <strong className="artifact-card-title" title={art.filename}>
                          {art.filename}
                        </strong>
                        <div className="artifact-card-meta">
                          <span>Run: <code>{art.run_id ? art.run_id.slice(0, 13) + "..." : "—"}</code></span>
                          <span>Size: {formatBytes(art.size_bytes)} · {formatTimestamp(art.created_at)}</span>
                        </div>
                        <div className="artifact-card-actions">
                          <button
                            type="button"
                            className="artifact-action-btn"
                            onClick={() => setPreviewImage(art)}
                          >
                            <Eye size={13} />
                            Preview
                          </button>
                          <a
                            href={`${API_BASE_URL}${art.url}`}
                            target="_blank"
                            rel="noreferrer"
                            className="artifact-action-btn"
                          >
                            <ExternalLink size={13} />
                            Full size
                          </a>
                          <a
                            href={`${API_BASE_URL}${art.download_url}`}
                            download={art.filename}
                            className="artifact-action-btn"
                          >
                            <Download size={13} />
                            Save
                          </a>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}

          {page === "Settings" && (
            <>
              <PageHeader
                eyebrow="CONFIGURATION"
                title="Automation settings"
                description="Set UI preferences for your local test workspace."
              />

              <section className="card settings-card">
                <CardHeading
                  icon={<Settings2 />}
                  title="Execution preferences"
                  description="These preferences are currently held in the dashboard UI."
                />

                <div className="settings-form">
                  <label className="field">
                    <span>Environment label</span>
                    <select
                      value={environment}
                      onChange={(event) => setEnvironment(event.target.value)}
                    >
                      <option>QA (Test)</option>
                      <option>UAT</option>
                      <option>Local</option>
                    </select>
                  </label>

                  <label className="field">
                    <span>Browser preference</span>
                    <select
                      value={browser}
                      onChange={(event) => setBrowser(event.target.value)}
                    >
                      <option>Chrome</option>
                      <option>Firefox</option>
                      <option>WebKit</option>
                    </select>
                  </label>

                  <label className="toggle-line">
                    <input
                      type="checkbox"
                      checked={headless}
                      onChange={(event) => setHeadless(event.target.checked)}
                    />
                    Headless mode
                  </label>

                  <label className="toggle-line">
                    <input
                      type="checkbox"
                      checked={capture}
                      onChange={(event) => setCapture(event.target.checked)}
                    />
                    Capture screenshots
                  </label>
                </div>

                <div className="settings-note">
                  <CircleAlert size={18} />
                  These settings are not yet applied to pytest. The current
                  backend request accepts test IDs only.
                </div>
              </section>

              <section className="card section-gap">
                <CardHeading
                  icon={<HardDrive />}
                  title="Backend connection"
                  description="Local FastAPI service."
                />
                <div className="backend-detail">
                  <span className="status-dot online" />
                  <div>
                    <strong>{backendStatus}</strong>
                    <span>API base URL: http://127.0.0.1:8000</span>
                  </div>
                  <button
                    className="button button-secondary button-small"
                    onClick={() => void loadTests()}
                  >
                    <RefreshCw size={15} />
                    Test connection
                  </button>
                </div>
              </section>
            </>
          )}
        </main>

      {previewImage && (
        <div className="image-modal-backdrop" onClick={() => setPreviewImage(null)}>
          <div className="image-modal-content" onClick={(e) => e.stopPropagation()}>
            <div className="image-modal-header">
              <strong>{previewImage.filename}</strong>
              <button
                type="button"
                className="icon-button"
                onClick={() => setPreviewImage(null)}
                aria-label="Close preview"
              >
                <X size={18} />
              </button>
            </div>
            <div className="image-modal-body">
              <img
                src={`${API_BASE_URL}${previewImage.url}`}
                alt={previewImage.filename}
                className="image-modal-img"
              />
            </div>
            <div className="image-modal-footer">
              <span style={{ fontSize: 12, color: "var(--vq-muted)" }}>
                Size: {formatBytes(previewImage.size_bytes)} · {formatTimestamp(previewImage.created_at)}
              </span>
              <div style={{ display: "flex", gap: 10 }}>
                <a
                  href={`${API_BASE_URL}${previewImage.url}`}
                  target="_blank"
                  rel="noreferrer"
                  className="artifact-action-btn"
                >
                  <ExternalLink size={14} />
                  Open in new tab
                </a>
                <a
                  href={`${API_BASE_URL}${previewImage.download_url}`}
                  download={previewImage.filename}
                  className="artifact-action-btn"
                >
                  <Download size={14} />
                  Download
                </a>
              </div>
            </div>
          </div>
        </div>
      )}

        <footer className="app-footer">
          <span>Veriqon Automation Platform</span>
          <span>Playwright · Pytest · FastAPI</span>
        </footer>
      </div>
    </div>
  );
}

function PageHeader({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow: string;
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <div className="page-heading">
      <div>
        <div className="eyebrow">{eyebrow}</div>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {action && <div className="page-heading-action">{action}</div>}
    </div>
  );
}

function CardHeading({
  icon,
  title,
  description,
  action,
}: {
  icon: ReactNode;
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="card-heading">
      <div className="card-heading-icon">{icon}</div>
      <div className="card-heading-copy">
        <strong>{title}</strong>
        {description && <span>{description}</span>}
      </div>
      {action && <div className="card-heading-action">{action}</div>}
    </div>
  );
}

function MetricCard({
  icon,
  label,
  value,
  detail,
  tone,
}: {
  icon: ReactNode;
  label: string;
  value: string | number;
  detail: string;
  tone: string;
}) {
  return (
    <div className="metric-card">
      <div className={`metric-icon ${tone}`}>{icon}</div>
      <div className="metric-copy">
        <span>{label}</span>
        <strong>{value}</strong>
        <small>{detail}</small>
      </div>
    </div>
  );
}

function SmallStat({
  label,
  value,
}: {
  label: string;
  value: string | number;
}) {
  return (
    <div className="small-stat">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function StatusPill({ status }: { status: string }) {
  const normalized = status.toLowerCase();
  const tone = normalized === "passed"
    ? "success"
    : normalized === "failed" || normalized === "error"
      ? "danger"
      : normalized === "running" || normalized === "queued" ||
          normalized === "submitting"
        ? "warning"
        : "neutral";

  return <span className={`status-pill ${tone}`}>{status}</span>;
}

function EmptyState({
  icon,
  title,
  description,
}: {
  icon: ReactNode;
  title: string;
  description: string;
}) {
  return (
    <div className="empty-state">
      <div className="empty-state-icon">{icon}</div>
      <strong>{title}</strong>
      <span>{description}</span>
    </div>
  );
}

function LogViewer({
  logs,
  compact = false,
}: {
  logs: string[];
  compact?: boolean;
}) {
  return (
    <div className={`log-viewer ${compact ? "compact" : ""}`}>
      {logs.length === 0 ? (
        <div className="log-empty">No log messages yet.</div>
      ) : (
        logs.map((line, index) => (
          <div className="log-line" key={`${index}-${line}`}>
            <span className="log-line-number">
              {String(index + 1).padStart(2, "0")}
            </span>
            <span>{line}</span>
          </div>
        ))
      )}
    </div>
  );
}


