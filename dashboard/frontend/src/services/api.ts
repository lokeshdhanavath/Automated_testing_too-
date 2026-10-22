export const API_BASE_URL = "http://127.0.0.1:8000";

async function apiRequest<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const isFormData =
    typeof FormData !== "undefined" && options.body instanceof FormData;

  const headers = new Headers(options.headers);

  if (!isFormData && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers,
  });

  const raw = await response.text();
  let data: unknown = null;

  if (raw) {
    try {
      data = JSON.parse(raw);
    } catch {
      data = raw;
    }
  }

  if (!response.ok) {
    const detail =
      typeof data === "object" &&
      data !== null &&
      "detail" in data
        ? String((data as { detail: unknown }).detail)
        : typeof data === "string" && data.trim()
          ? data
          : `Request failed (${response.status})`;

    throw new Error(detail);
  }

  return data as T;
}

// ---------------------------------------------------------
// Projects
// ---------------------------------------------------------

export type ProjectType =
  | "Web application"
  | "API application"
  | "Full-stack application";

export type ProjectEnvironment =
  | "Development"
  | "QA"
  | "Staging"
  | "Production";

export type ProjectBrowser = "chromium" | "firefox" | "webkit";

export interface ProjectConfig {
  id: string;
  name: string;
  project_type: ProjectType;
  base_url: string;
  test_directory: string;
  default_environment: ProjectEnvironment;
  browser: ProjectBrowser;
  headless: boolean;
  capture_screenshots: boolean;
  capture_video: boolean;
  username_env_var: string;
  password_env_var: string;
  description?: string;
  test_timeout_seconds?: number;
  navigation_timeout_seconds?: number;
  default_wait_ms?: number;
  auth_method?: string;
  is_default: boolean;
  is_active?: boolean;
  created_at: string;
  updated_at: string;
}

export type ProjectPayload = Omit<
  ProjectConfig,
  "id" | "is_default" | "created_at" | "updated_at"
> & {
  is_active?: boolean;
};

export async function getProjects(): Promise<ProjectConfig[]> {
  return apiRequest<ProjectConfig[]>("/api/projects");
}

export async function createProject(
  payload: ProjectPayload,
): Promise<ProjectConfig> {
  return apiRequest<ProjectConfig>("/api/projects", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function updateProject(
  projectId: string,
  payload: ProjectPayload,
): Promise<ProjectConfig> {
  return apiRequest<ProjectConfig>(
    `/api/projects/${encodeURIComponent(projectId)}`,
    {
      method: "PUT",
      body: JSON.stringify(payload),
    },
  );
}

export async function deleteProject(
  projectId: string,
): Promise<{ message: string }> {
  return apiRequest<{ message: string }>(
    `/api/projects/${encodeURIComponent(projectId)}`,
    { method: "DELETE" },
  );
}

export async function toggleProjectActive(
  projectId: string,
): Promise<{ id: string; is_active: boolean; message: string }> {
  return apiRequest<{ id: string; is_active: boolean; message: string }>(
    `/api/projects/${encodeURIComponent(projectId)}/toggle-active`,
    { method: "PATCH" },
  );
}

// ---------------------------------------------------------
// Backend health
// ---------------------------------------------------------

export interface HealthResponse {
  status?: string;
  application?: string;
  message?: string;
}

export async function checkBackendHealth(): Promise<HealthResponse> {
  return apiRequest<HealthResponse>("/api/health");
}

// ---------------------------------------------------------
// Test cases
// ---------------------------------------------------------

export interface TestCase {
  id: string;
  name: string;
  category: string;
  file?: string;
  displayId?: string;
}

export async function getTestCases(projectId?: string): Promise<TestCase[]> {
  const query = projectId ? `?project_id=${encodeURIComponent(projectId)}` : "";
  const response = await apiRequest<unknown>(`/api/test-cases${query}`);

  const rows: unknown[] = Array.isArray(response)
    ? response
    : typeof response === "object" && response !== null
      ? (
          (response as { tests?: unknown[] }).tests ??
          (response as { test_cases?: unknown[] }).test_cases ??
          []
        )
      : [];

  return rows
    .map((value, index) => {
      const item =
        typeof value === "string"
          ? null
          : (value as Record<string, unknown>);

      const id =
        typeof value === "string"
          ? value
          : String(
              item?.id ??
                item?.nodeid ??
                item?.node_id ??
                "",
            );

      const file =
        typeof value === "string"
          ? (id.split("::")[0] ?? "")
          : String(item?.file ?? id.split("::")[0] ?? "");

      const fileName = file.split(/[\\/]/).pop() ?? file;

      const rawName =
        typeof value === "string"
          ? (id.split("::").pop() ?? id)
          : String(item?.name ?? id.split("::").pop() ?? id);

      const category =
        typeof value === "string"
          ? fileName
              .replace(/^test_/, "")
              .replace(/\.py$/, "")
              .replace(/_/g, " ")
          : String(
              item?.category ??
                fileName
                  .replace(/^test_/, "")
                  .replace(/\.py$/, "")
                  .replace(/_/g, " "),
            );

      const displayId =
        (typeof item?.displayId === "string" ? item.displayId : null) ??
        `TC-${String(index + 1).padStart(3, "0")}`;

      return { id, name: rawName, category, file, displayId };
    })
    .filter((item) => item.id.length > 0);
}

// ---------------------------------------------------------
// Test runs & Results
// ---------------------------------------------------------

export interface RunSummary {
  total?: number;
  passed?: number;
  failed?: number;
  errors?: number;
  skipped?: number;
  duration?: number;
}

export interface StartRunResponse {
  run_id: string;
  project_id?: string;
  status: string;
  message?: string;
}

export interface TestResultItem {
  id: number;
  test_id: string;
  status: string;
  duration_seconds: number;
  error_message: string | null;
  created_at: string;
}

export interface RunStatus {
  id?: string;
  run_id: string;
  project_id?: string;
  status: string;
  summary?: RunSummary | null;
  exit_code?: number;
  started_at?: string;
  finished_at?: string;
  created_at?: string;
  test_results?: TestResultItem[];
  log_path?: string;
}

export interface RunRecord extends RunStatus {
  test_file?: string | null;
  test_ids?: string[];
  logs?: string;
}

export async function startRun(payload: {
  project_id?: string;
  test_file?: string;
  test_ids?: string[];
}): Promise<StartRunResponse> {
  return apiRequest<StartRunResponse>("/api/runs", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getRunStatus(
  runId: string,
): Promise<RunStatus> {
  return apiRequest<RunStatus>(
    `/api/runs/${encodeURIComponent(runId)}`,
  );
}

export async function getRunLogs(
  runId: string,
): Promise<{ logs?: string }> {
  return apiRequest<{ logs?: string }>(
    `/api/runs/${encodeURIComponent(runId)}/logs`,
  );
}

export async function getRuns(projectId?: string): Promise<RunRecord[]> {
  const query = projectId ? `?project_id=${encodeURIComponent(projectId)}` : "";
  return apiRequest<RunRecord[]>(`/api/runs${query}`);
}

export async function getProjectRuns(projectId: string): Promise<RunRecord[]> {
  return apiRequest<RunRecord[]>(`/api/projects/${encodeURIComponent(projectId)}/runs`);
}

// ---------------------------------------------------------
// Artifacts (Screenshots, Videos, Reports, Logs)
// ---------------------------------------------------------

export interface ArtifactItem {
  id: number;
  project_id: string;
  run_id: string | null;
  artifact_type: "screenshot" | "video" | "report" | "log" | "junit";
  filename: string;
  relative_path: string;
  content_type: string | null;
  size_bytes: number | null;
  created_at: string;
  url: string;
  download_url: string;
}

export async function getProjectArtifacts(
  projectId: string,
  runId?: string,
  type?: string,
): Promise<ArtifactItem[]> {
  const params = new URLSearchParams();
  if (runId) params.append("run_id", runId);
  if (type) params.append("type", type);
  const qs = params.toString() ? `?${params.toString()}` : "";
  return apiRequest<ArtifactItem[]>(
    `/api/projects/${encodeURIComponent(projectId)}/artifacts${qs}`,
  );
}

export async function getRunArtifacts(runId: string): Promise<ArtifactItem[]> {
  return apiRequest<ArtifactItem[]>(`/api/runs/${encodeURIComponent(runId)}/artifacts`);
}

// ---------------------------------------------------------
// CSV scenarios
// ---------------------------------------------------------

export interface CsvScenario extends Record<string, unknown> {
  TC_ID?: string;
  tc_id?: string;
  id?: string;
  Scenario?: string;
  scenario?: string;
  Preconditions?: string;
  preconditions?: string;
  Steps?: string;
  steps?: string;
  Expected_Result?: string;
  expected_result?: string;
  Priority?: string;
  priority?: string;
  valid?: boolean;
}

export interface CsvValidationResponse {
  valid?: boolean;
  filename?: string;
  total_rows?: number;
  valid_rows?: number;
  errors?: Array<string | Record<string, unknown>>;
  columns?: string[];
  scenarios?: CsvScenario[];
}

export async function validateCsvScenarios(
  file: File,
  projectId?: string,
): Promise<CsvValidationResponse> {
  const form = new FormData();
  form.append("file", file);
  if (projectId) {
    form.append("project_id", projectId);
  }

  return apiRequest<CsvValidationResponse>(
    "/api/csv-scenarios/validate",
    {
      method: "POST",
      body: form,
    },
  );
}

export async function executeCsvScenarios(
  file: File,
  selectedIds: string[],
  projectId?: string,
): Promise<
  StartRunResponse & {
    selected_tc_ids?: string[];
    pytest_ids?: string[];
  }
> {
  const form = new FormData();
  form.append("file", file);

  selectedIds.forEach((id) => {
    form.append("selected_tc_ids", id);
  });

  if (projectId) {
    form.append("project_id", projectId);
  }

  return apiRequest<
    StartRunResponse & {
      selected_tc_ids?: string[];
      pytest_ids?: string[];
    }
  >("/api/csv-scenarios/execute", {
    method: "POST",
    body: form,
  });
}

// ---------------------------------------------------------
// Credentials & Generic Scenarios
// ---------------------------------------------------------

export interface CredentialItem {
  id: string;
  project_id: string;
  name: string;
  credential_type: string;
  username: string;
  masked_secret: string;
  description: string;
  environment: string;
  created_at: string;
  updated_at: string;
}

export interface CredentialPayload {
  name: string;
  username: string;
  secret: string;
  environment?: string;
  description?: string;
  credential_type?: string;
}

export interface CredentialUpdatePayload {
  name?: string;
  username?: string;
  secret?: string;
  environment?: string;
  description?: string;
}

export interface ScenarioStep {
  id?: number;
  step_order: number;
  action_type: string;
  locator_type?: string;
  locator_value?: string;
  action_params?: Record<string, any>;
  description?: string;
  is_enabled?: boolean;
  timeout_ms?: number;
}

export interface ScenarioItem {
  id: string;
  project_id: string;
  name: string;
  description: string;
  tags: string[];
  failure_policy: "stop" | "continue";
  timeout_seconds: number;
  environment: string;
  credential_id?: string | null;
  credential_name?: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  step_count?: number;
  steps?: ScenarioStep[];
}

export interface ScenarioPayload {
  name: string;
  description?: string;
  tags?: string[];
  failure_policy?: "stop" | "continue";
  timeout_seconds?: number;
  environment?: string;
  credential_id?: string | null;
  steps?: ScenarioStep[];
}

export interface DataProfileItem {
  id: string;
  project_id: string;
  name: string;
  description?: string;
  dataset_rows: Record<string, any>[];
  created_at: string;
  updated_at: string;
}

export interface DataProfilePayload {
  name: string;
  description?: string;
  dataset_rows: Record<string, any>[];
}

export interface StepExecutionResult {
  id: number;
  run_id: string;
  scenario_id?: string;
  step_order: number;
  action_type: string;
  description?: string;
  status: "passed" | "failed" | "skipped";
  duration_ms: number;
  actual_value?: string;
  expected_value?: string;
  error_message?: string;
  screenshot_artifact_id?: number;
  screenshot_url?: string;
  created_at: string;
}

export interface ScenarioRunPayload {
  environment?: string;
  credential_id?: string;
  data_profile_id?: string;
  dataset_row_index?: number;
}

// Credentials API
export async function getProjectCredentials(projectId: string): Promise<CredentialItem[]> {
  return apiRequest<CredentialItem[]>(`/api/projects/${projectId}/credentials`);
}

export async function createProjectCredential(
  projectId: string,
  payload: CredentialPayload,
): Promise<CredentialItem> {
  return apiRequest<CredentialItem>(`/api/projects/${projectId}/credentials`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function updateProjectCredential(
  credentialId: string,
  payload: CredentialUpdatePayload,
): Promise<CredentialItem> {
  return apiRequest<CredentialItem>(`/api/credentials/${credentialId}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export async function deleteProjectCredential(credentialId: string): Promise<{ message: string }> {
  return apiRequest<{ message: string }>(`/api/credentials/${credentialId}`, {
    method: "DELETE",
  });
}

// Scenarios API
export async function getProjectScenarios(projectId: string): Promise<ScenarioItem[]> {
  return apiRequest<ScenarioItem[]>(`/api/projects/${projectId}/scenarios`);
}

export async function getScenarioDetails(scenarioId: string): Promise<ScenarioItem> {
  return apiRequest<ScenarioItem>(`/api/scenarios/${scenarioId}`);
}

export async function createScenario(
  projectId: string,
  payload: ScenarioPayload,
): Promise<ScenarioItem> {
  return apiRequest<ScenarioItem>(`/api/projects/${projectId}/scenarios`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function updateScenario(
  scenarioId: string,
  payload: Partial<ScenarioPayload>,
): Promise<ScenarioItem> {
  return apiRequest<ScenarioItem>(`/api/scenarios/${scenarioId}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export async function deleteScenario(scenarioId: string): Promise<{ message: string }> {
  return apiRequest<{ message: string }>(`/api/scenarios/${scenarioId}`, {
    method: "DELETE",
  });
}

export async function runScenario(
  scenarioId: string,
  payload: ScenarioRunPayload = {},
): Promise<{ run_id: string; project_id: string; status: string }> {
  return apiRequest<{ run_id: string; project_id: string; status: string }>(
    `/api/scenarios/${scenarioId}/run`,
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
  );
}

// Data Profiles API
export async function getProjectDataProfiles(projectId: string): Promise<DataProfileItem[]> {
  return apiRequest<DataProfileItem[]>(`/api/projects/${projectId}/data-profiles`);
}

export async function createProjectDataProfile(
  projectId: string,
  payload: DataProfilePayload,
): Promise<DataProfileItem> {
  return apiRequest<DataProfileItem>(`/api/projects/${projectId}/data-profiles`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function deleteProjectDataProfile(profileId: string): Promise<{ message: string }> {
  return apiRequest<{ message: string }>(`/api/data-profiles/${profileId}`, {
    method: "DELETE",
  });
}

// Step Execution Results API
export async function getRunStepResults(runId: string): Promise<StepExecutionResult[]> {
  return apiRequest<StepExecutionResult[]>(`/api/runs/${runId}/steps`);
}

