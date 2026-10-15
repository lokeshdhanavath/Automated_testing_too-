
export const API_BASE_URL = "http://127.0.0.1:8000";

// ==================================================
// Common API request handler
// ==================================================

async function apiRequest<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
  });

  if (!response.ok) {
    let message = `Request failed: HTTP ${response.status}`;

    try {
      const body = await response.json();

      message =
        typeof body.detail === "string"
          ? body.detail
          : JSON.stringify(body.detail ?? body);
    } catch {
      // Retain the default HTTP error message.
    }

    throw new Error(message);
  }

  return response.json() as Promise<T>;
}

// ==================================================
// Backend health
// ==================================================

export interface HealthResponse {
  status: string;
  application?: string;
}

export function checkBackendHealth(): Promise<HealthResponse> {
  return apiRequest<HealthResponse>("/api/health");
}

// ==================================================
// Test cases
// ==================================================

export interface TestCase {
  id: string;
  name: string;
  file: string;
  category: string;
  displayId: string;
}

export function getTestCases(): Promise<TestCase[]> {
  return apiRequest<string[]>("/api/test-cases").then((tests) =>
    tests.map((testId) => {
      const parts = testId.split("::");
      const file = parts[0] ?? testId;
      const testName = parts[parts.length - 1] ?? testId;

      const fileName = file.split(/[\\/]/).pop() ?? file;

      const category = fileName
        .replace(/^test_/, "")
        .replace(/\.py$/, "")
        .split("_")
        .map(
          (word) => word.charAt(0).toUpperCase() + word.slice(1)
        )
        .join(" ");

      const displayId = testName.replace(/^test_/, "");

      return {
        id: testId,
        name: testName,
        file,
        category,
        displayId,
      };
    })
  );
}

// ==================================================
// Test execution and results
// ==================================================

export interface RunSummary {
  total?: number;
  passed?: number;
  failed?: number;
  errors?: number;
  skipped?: number;
}

export interface RunStatus {
  id?: string;
  run_id?: string;
  status: string;
  exit_code?: number | null;
  summary?: RunSummary | null;
  logs?: string;
  test_file?: string | null;
  test_ids?: string[];
}

export interface StartRunResponse {
  run_id: string;
  status: string;
}

export function startRun(payload: {
  test_file?: string;
  test_ids?: string[];
}): Promise<StartRunResponse> {
  return apiRequest<StartRunResponse>("/api/runs", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getRunStatus(runId: string): Promise<RunStatus> {
  return apiRequest<RunStatus>(
    `/api/runs/${encodeURIComponent(runId)}`
  );
}

export function getRunLogs(
  runId: string
): Promise<{ logs: string }> {
  return apiRequest<{ logs: string }>(
    `/api/runs/${encodeURIComponent(runId)}/logs`
  );
}

export function getRuns(): Promise<RunStatus[]> {
  return apiRequest<RunStatus[]>("/api/runs");
}

// ==================================================
// Test script management
// ==================================================

export interface TestScript {
  filename: string;
  path: string;
  size_bytes: number;
  test_count: number | null;
  test_functions: string[];
  has_syntax_error?: boolean;
}

export interface ScriptListResponse {
  scripts: TestScript[];
  count: number;
}

export interface ScriptSyntaxError {
  line?: number;
  column?: number;
  message?: string;
}

export interface ScriptContentResponse {
  filename: string;
  content: string;
  syntax_valid: boolean;
  syntax_error: ScriptSyntaxError | null;
}

export interface ScriptMutationResponse {
  message: string;
  filename: string;
  path: string;
}

export function getScripts(): Promise<ScriptListResponse> {
  return apiRequest<ScriptListResponse>("/api/scripts");
}

export function getScript(
  filename: string
): Promise<ScriptContentResponse> {
  return apiRequest<ScriptContentResponse>(
    `/api/scripts/${encodeURIComponent(filename)}`
  );
}

export function createScript(payload: {
  filename: string;
  content: string;
}): Promise<ScriptMutationResponse> {
  return apiRequest<ScriptMutationResponse>("/api/scripts", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateScript(
  filename: string,
  content: string
): Promise<ScriptMutationResponse> {
  return apiRequest<ScriptMutationResponse>(
    `/api/scripts/${encodeURIComponent(filename)}`,
    {
      method: "PUT",
      body: JSON.stringify({ content }),
    }
  );
}
