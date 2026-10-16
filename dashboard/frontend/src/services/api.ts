
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
  is_default: boolean;
  created_at: string;
  updated_at: string;
}

export type ProjectPayload = Omit<
  ProjectConfig,
  "id" | "is_default" | "created_at" | "updated_at"
>;

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
}

export async function getTestCases(): Promise<TestCase[]> {
  // The current FastAPI endpoint returns a JSON array of pytest
  // node-ID strings. Object-shaped responses are also supported.
  const response = await apiRequest<unknown>("/api/test-cases");

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
    .map((value) => {
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

      return { id, name: rawName, category, file };
    })
    .filter((item) => item.id.length > 0);
}

// ---------------------------------------------------------
// Test runs
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
  status: string;
  message?: string;
}

export interface RunStatus {
  run_id: string;
  status: string;
  summary?: RunSummary | null;
  exit_code?: number;
  started_at?: string;
  finished_at?: string;
}

export interface RunRecord extends RunStatus {
  test_file?: string | null;
  test_ids?: string[];
  logs?: string;
}

export async function startRun(payload: {
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

export async function getRuns(): Promise<RunRecord[]> {
  return apiRequest<RunRecord[]>("/api/runs");
}

// ---------------------------------------------------------
// CSV scenarios
// ---------------------------------------------------------

export interface CsvScenario extends Record<string, unknown> {
  TC_ID?: string;
  tc_id?: string;
  id?: string;
  Scenario?: string;
  Preconditions?: string;
  Steps?: string;
  Expected_Result?: string;
  Priority?: string;
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
): Promise<CsvValidationResponse> {
  const form = new FormData();
  form.append("file", file);

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
