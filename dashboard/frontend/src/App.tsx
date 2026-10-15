
import { useEffect, useState } from "react";
import type { ReactNode } from "react";
import {
  Activity,
  Archive,
  Camera,
  CheckCircle2,
  Check,
  Code2,
  FileCode2,
  ChevronDown,
  CircleAlert,
  Clock3,
  FileBarChart,
  FileText,
  FlaskConical,
  Gauge,
  HardDrive,
  LayoutDashboard,
  ListChecks,
  LoaderCircle,
  Play,
  RefreshCw,
  Search,
  Save,
  Plus,
  Settings2,
  SquareTerminal,
  Video,
  XCircle,
} from "lucide-react";

import {
  checkBackendHealth,
  getTestCases,
  startRun,
  getRunStatus,
  getRunLogs,
  getScripts,
  getScript,
  createScript,
  updateScript,
} from "./services/api";

import type { TestCase, TestScript } from "./services/api";
import "./App.css";

type Page =
  | "Dashboard"
  | "Test Suites"
  | "Test Scripts"
  | "Test Execution"
  | "Reports"
  | "Video Recordings"
  | "Screenshots"
  | "Execution Logs"
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
      { label: "Dashboard", icon: LayoutDashboard },
      { label: "Test Suites", icon: ListChecks },
      { label: "Test Scripts", icon: Code2 },
      { label: "Test Execution", icon: Play },
    ],
  },
  {
    section: "ARTIFACTS",
    items: [
      { label: "Reports", icon: FileBarChart },
      { label: "Video Recordings", icon: Video },
      { label: "Screenshots", icon: Camera },
      { label: "Execution Logs", icon: SquareTerminal },
    ],
  },
  {
    section: "CONFIGURATION",
    items: [{ label: "Settings", icon: Settings2 }],
  },
];

export default function App() {
  const [page, setPage] = useState<Page>("Dashboard");
  const [tests, setTests] = useState<TestCase[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [suite, setSuite] = useState("All Test Suites");
  const [search, setSearch] = useState("");

  // Test script explorer/editor state
  const [scripts, setScripts] = useState<TestScript[]>([]);
  const [selectedScript, setSelectedScript] = useState<string>("");
  const [scriptContent, setScriptContent] = useState("");
  const [scriptLoading, setScriptLoading] = useState(false);
  const [scriptSaving, setScriptSaving] = useState(false);
  const [scriptError, setScriptError] = useState("");
  const [scriptMessage, setScriptMessage] = useState("");
  const [newScriptName, setNewScriptName] = useState("test_new_feature.py");

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

  
async function loadTests() {
  setLoadingTests(true);
  setTestError("");

  try {
    const health = await checkBackendHealth();
    setBackendStatus("Connected");
    addLog(`Backend connected: ${health.application ?? "APEX API"}`);

    const discovered = await getTestCases();
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
        const [status, logResult] = await Promise.all([
          getRunStatus(activeRunId!),
          getRunLogs(activeRunId!),
        ]);

        if (cancelled) return;

        setRunStatus(status.status);

        if (status.summary) {
          setRunSummary(status.summary);
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
          addLog(`Run finished with status: ${status.status}`);
          if (status.exit_code !== undefined) {
            addLog(`Pytest exit code: ${status.exit_code}`);
          }
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

  async function loadScripts(preferredFilename?: string) {
    setScriptLoading(true);
    setScriptError("");
    setScriptMessage("");
    try {
      const result = await getScripts();
      setScripts(result.scripts);
      const target = preferredFilename ?? selectedScript ?? result.scripts[0]?.filename ?? "";
      if (target && result.scripts.some((script) => script.filename === target)) {
        await openScript(target);
      } else if (!target && result.scripts.length > 0) {
        await openScript(result.scripts[0].filename);
      } else if (result.scripts.length === 0) {
        setSelectedScript("");
        setScriptContent("");
      }
    } catch (error) {
      setScriptError(error instanceof Error ? error.message : "Unable to load scripts.");
    } finally {
      setScriptLoading(false);
    }
  }

  async function openScript(filename: string) {
    setSelectedScript(filename);
    setScriptError("");
    setScriptMessage("");
    try {
      const result = await getScript(filename);
      setScriptContent(result.content);
      if (!result.syntax_valid && result.syntax_error) {
        setScriptError(`Python syntax issue at line ${result.syntax_error.line ?? "?"}: ${result.syntax_error.message ?? "Invalid syntax"}`);
      }
    } catch (error) {
      setScriptError(error instanceof Error ? error.message : "Unable to open script.");
    }
  }

  async function saveCurrentScript() {
    if (!selectedScript || scriptSaving) return;
    setScriptSaving(true);
    setScriptError("");
    setScriptMessage("");
    try {
      const result = await updateScript(selectedScript, scriptContent);
      await loadScripts(selectedScript);
      setScriptMessage(result.message || "Script saved successfully.");
    } catch (error) {
      setScriptError(error instanceof Error ? error.message : "Unable to save script.");
    } finally {
      setScriptSaving(false);
    }
  }

  async function makeNewScript() {
    const filename = newScriptName.trim();
    if (!filename) {
      setScriptError("Enter a filename such as test_new_feature.py.");
      return;
    }
    const safeFilename = filename.endsWith(".py") ? filename : `${filename}.py`;
    const initialContent = `import pytest


def test_new_feature(page):
    \"\"\"Describe the expected behavior for this test.\"\"\"
    # TODO: Add your Playwright steps and assertions.
    assert True
`;
    setScriptSaving(true);
    setScriptError("");
    setScriptMessage("");
    try {
      const result = await createScript({ filename: safeFilename, content: initialContent });
      setNewScriptName("test_new_feature.py");
      await loadScripts(safeFilename);
      setScriptMessage(result.message || `Created ${safeFilename}.`);
    } catch (error) {
      setScriptError(error instanceof Error ? error.message : "Unable to create script.");
    } finally {
      setScriptSaving(false);
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
      const response = await startRun({ test_ids: selected });
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
    if (nextPage === "Test Scripts") void loadScripts();
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
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">
            <FlaskConical size={23} />
          </div>
          <div>
            <strong>TestPilot</strong>
            <span>Automation Platform</span>
          </div>
        </div>

        <div className="workspace-switcher">
          <div className="workspace-icon">
            <Activity size={18} />
          </div>
          <div className="workspace-copy">
            <strong>APEX Timesheet</strong>
            <span>Playwright workspace</span>
          </div>
          <ChevronDown size={16} />
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
          <div className="sidebar-version">TestPilot · Local workspace</div>
        </div>
      </aside>

      <div className="app-main">
        <header className="topbar">
          <div className="breadcrumbs">
            <span>Automation</span>
            <span>/</span>
            <strong>{page}</strong>
          </div>

          <div className="topbar-actions">
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
          {page === "Dashboard" && (
            <>
              <PageHeader
                eyebrow="AUTOMATION OVERVIEW"
                title="Testing dashboard"
                description="Run your Playwright tests, track outcomes, and inspect execution evidence."
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
                        onClick={() => openPage("Test Execution")}
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
                        onClick={() => openPage("Execution Logs")}
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

          {page === "Test Scripts" && (
            <>
              <PageHeader
                eyebrow="SCRIPT WORKSPACE"
                title="Test scripts"
                description="Browse and edit the Python pytest scripts used by your Playwright automation suite."
                action={
                  <button className="button button-secondary" onClick={() => void loadScripts()} disabled={scriptLoading}>
                    <RefreshCw size={16} /> Refresh scripts
                  </button>
                }
              />

              <div className="script-workspace">
                <section className="card script-explorer">
                  <div className="script-panel-heading">
                    <div>
                      <strong><FolderOpenIcon /> Test files</strong>
                      <span>{scripts.length} scripts in tests/</span>
                    </div>
                    <button className="icon-button" title="Refresh scripts" onClick={() => void loadScripts()} disabled={scriptLoading}>
                      <RefreshCw size={15} />
                    </button>
                  </div>
                  <div className="script-create-form">
                    <input
                      value={newScriptName}
                      onChange={(event) => setNewScriptName(event.target.value)}
                      aria-label="New Python test filename"
                      placeholder="test_new_feature.py"
                    />
                    <button className="button button-primary button-small" onClick={() => void makeNewScript()} disabled={scriptSaving}>
                      <Plus size={15} /> Create
                    </button>
                  </div>
                  <div className="script-file-list">
                    {scripts.map((script) => (
                      <button
                        key={script.filename}
                        className={`script-file ${selectedScript === script.filename ? "selected" : ""}`}
                        onClick={() => void openScript(script.filename)}
                      >
                        <FileCode2 size={17} />
                        <span className="script-file-copy">
                          <strong>{script.filename}</strong>
                          <small>{script.test_count ?? 0} test functions · {formatBytes(script.size_bytes)}</small>
                        </span>
                        {selectedScript === script.filename && <span className="script-active-dot" />}
                      </button>
                    ))}
                    {!scriptLoading && scripts.length === 0 && (
                      <div className="script-list-empty">No test scripts found in the tests/ folder.</div>
                    )}
                  </div>
                </section>

                <section className="card script-editor-panel">
                  <div className="script-editor-toolbar">
                    <div className="script-editor-title">
                      <Code2 size={18} />
                      <div>
                        <strong>{selectedScript || "No script selected"}</strong>
                        <span>Python · tests/</span>
                      </div>
                    </div>
                    <button className="button button-primary" onClick={() => void saveCurrentScript()} disabled={!selectedScript || scriptSaving}>
                      {scriptSaving ? <LoaderCircle className="spin" size={16} /> : <Save size={16} />}
                      {scriptSaving ? "Saving…" : "Save changes"}
                    </button>
                  </div>

                  {scriptError && <div className="script-message error"><CircleAlert size={16} />{scriptError}</div>}
                  {scriptMessage && <div className="script-message success"><Check size={16} />{scriptMessage}</div>}

                  <div className="script-editor-meta">
                    <span><span className="status-dot online" /> Python source</span>
                    <span>Changes are saved to your local tests/ folder</span>
                  </div>
                  <textarea
                    className="python-editor"
                    value={scriptContent}
                    onChange={(event) => {
                      setScriptContent(event.target.value);
                      setScriptMessage("");
                    }}
                    spellCheck={false}
                    aria-label="Python test script editor"
                    placeholder={scriptLoading ? "Loading script…" : "Select a script from the left, or create a new one."}
                    disabled={!selectedScript || scriptLoading}
                  />
                  <div className="script-editor-footer">
                    <span>{scriptContent.split("").length} lines</span>
                    <span>Save validates Python syntax on the backend</span>
                  </div>
                </section>
              </div>
              <div className="script-workspace-note">
                <CircleAlert size={16} /> Edit carefully: saved scripts are real pytest files. Run them from Test Suites or Test Execution after saving.
              </div>
            </>
          )}

          {page === "Test Execution" && (
            <>
              <PageHeader
                eyebrow="RUNNER"
                title="Test execution"
                description="Launch selected tests and monitor the live runner status."
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

          {page === "Reports" && (
            <>
              <PageHeader
                eyebrow="RESULTS"
                title="Test reports"
                description="Review the current run's summary and locate generated report files."
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
              </section>
            </>
          )}

          {page === "Video Recordings" && (
            <ArtifactPage
              icon={<Video />}
              title="Video recordings"
              description="Review Playwright videos captured during browser test execution."
              note="The backend must return run-specific video paths and provide a safe way to serve them before recordings can be opened here."
              onViewLogs={() => openPage("Execution Logs")}
            />
          )}

          {page === "Screenshots" && (
            <ArtifactPage
              icon={<Camera />}
              title="Screenshots"
              description="Inspect screenshots captured during test execution and failures."
              note="The current frontend does not yet retrieve or display screenshot file URLs from the artifacts endpoint."
              onViewLogs={() => openPage("Execution Logs")}
            />
          )}

          {page === "Execution Logs" && (
            <>
              <PageHeader
                eyebrow="DIAGNOSTICS"
                title="Execution logs"
                description="Inspect the output received from the current run and dashboard."
                action={
                  <button
                    className="button button-secondary"
                    onClick={() => setLogs([])}
                  >
                    Clear logs
                  </button>
                }
              />

              <section className="card">
                <div className="log-meta">
                  <span>
                    <span
                      className={`status-dot ${
                        backendStatus === "Connected" ? "online" : "offline"
                      }`}
                    />
                    Backend: {backendStatus}
                  </span>
                  <span>Run status: {runStatus}</span>
                  {activeRunId && <code>{activeRunId}</code>}
                </div>
                <LogViewer logs={logs} />
              </section>
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

        <footer className="app-footer">
          <span>TestPilot Automation Platform</span>
          <span>Playwright · Pytest · FastAPI</span>
        </footer>
      </div>
    </div>
  );
}

function FolderOpenIcon() {
  return <FileText size={17} />;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  return `${(bytes / 1024).toFixed(1)} KB`;
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

function ArtifactPage({
  icon,
  title,
  description,
  note,
  onViewLogs,
}: {
  icon: ReactNode;
  title: string;
  description: string;
  note: string;
  onViewLogs: () => void;
}) {
  return (
    <>
      <PageHeader
        eyebrow="EXECUTION ARTIFACTS"
        title={title}
        description={description}
      />

      <section className="card artifact-empty-card">
        <EmptyState
          icon={icon}
          title="Artifact gallery not connected yet"
          description={note}
        />
        <button className="button button-secondary" onClick={onViewLogs}>
          <SquareTerminal size={16} />
          Inspect execution logs
        </button>
      </section>
    </>
  );
}
