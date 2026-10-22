-- ====================================================================
-- Migration: 002_generic_scenario_platform.sql
-- Adds generic configuration-driven testing platform tables:
-- 1. app_credentials (encrypted credentials with metadata & masking)
-- 2. test_scenarios (UI-defined scenarios per application)
-- 3. test_scenario_steps (ordered browser actions & assertions)
-- 4. test_data_profiles (parameterized test datasets)
-- 5. step_execution_results (step-level execution outcomes)
-- Plus non-breaking extensions to projects and test_runs tables.
-- ====================================================================

-- 1. Projects optional columns extension
ALTER TABLE projects ADD COLUMN IF NOT EXISTS description TEXT;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS test_timeout_seconds INTEGER DEFAULT 60;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS navigation_timeout_seconds INTEGER DEFAULT 30;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS default_wait_ms INTEGER DEFAULT 500;
ALTER TABLE projects ADD COLUMN IF NOT EXISTS auth_method VARCHAR(50) DEFAULT 'form';

-- 2. Credentials Table (Secure Authenticated Encryption via Fernet)
CREATE TABLE IF NOT EXISTS app_credentials (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    credential_type VARCHAR(50) NOT NULL DEFAULT 'username_password',
    username VARCHAR(255) NOT NULL,
    encrypted_secret TEXT NOT NULL,
    masked_secret VARCHAR(50) NOT NULL,
    description TEXT,
    environment VARCHAR(50) NOT NULL DEFAULT 'QA',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_project_credential_name UNIQUE (project_id, name)
);

CREATE INDEX IF NOT EXISTS idx_app_credentials_project_id ON app_credentials(project_id);

-- 3. Test Scenarios Table
CREATE TABLE IF NOT EXISTS test_scenarios (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name VARCHAR(200) NOT NULL,
    description TEXT,
    tags JSONB NOT NULL DEFAULT '[]'::jsonb,
    failure_policy VARCHAR(20) NOT NULL DEFAULT 'stop',
    timeout_seconds INTEGER NOT NULL DEFAULT 60,
    environment VARCHAR(50) NOT NULL DEFAULT 'QA',
    credential_id UUID REFERENCES app_credentials(id) ON DELETE SET NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_project_scenario_name UNIQUE (project_id, name)
);

CREATE INDEX IF NOT EXISTS idx_test_scenarios_project_id ON test_scenarios(project_id);

-- 4. Test Scenario Steps Table
CREATE TABLE IF NOT EXISTS test_scenario_steps (
    id BIGSERIAL PRIMARY KEY,
    scenario_id UUID NOT NULL REFERENCES test_scenarios(id) ON DELETE CASCADE,
    step_order INTEGER NOT NULL,
    action_type VARCHAR(50) NOT NULL,
    locator_type VARCHAR(30),
    locator_value TEXT,
    action_params JSONB NOT NULL DEFAULT '{}'::jsonb,
    description TEXT,
    is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    timeout_ms INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_scenario_step_order UNIQUE (scenario_id, step_order)
);

CREATE INDEX IF NOT EXISTS idx_test_scenario_steps_scenario_id ON test_scenario_steps(scenario_id);

-- 5. Test Data Profiles Table (Reusable parameterized datasets)
CREATE TABLE IF NOT EXISTS test_data_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name VARCHAR(100) NOT NULL,
    description TEXT,
    dataset_rows JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_project_dataset_name UNIQUE (project_id, name)
);

CREATE INDEX IF NOT EXISTS idx_test_data_profiles_project_id ON test_data_profiles(project_id);

-- 6. Test Runs Extensions
ALTER TABLE test_runs ADD COLUMN IF NOT EXISTS scenario_id UUID REFERENCES test_scenarios(id) ON DELETE SET NULL;
ALTER TABLE test_runs ADD COLUMN IF NOT EXISTS dataset_name VARCHAR(100);
ALTER TABLE test_runs ADD COLUMN IF NOT EXISTS dataset_row_index INTEGER;

-- 7. Step Execution Results Table (Granular step-level reporting)
CREATE TABLE IF NOT EXISTS step_execution_results (
    id BIGSERIAL PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES test_runs(id) ON DELETE CASCADE,
    scenario_id UUID REFERENCES test_scenarios(id) ON DELETE SET NULL,
    step_order INTEGER NOT NULL,
    action_type VARCHAR(50) NOT NULL,
    description TEXT,
    status VARCHAR(20) NOT NULL,
    duration_ms INTEGER DEFAULT 0,
    actual_value TEXT,
    expected_value TEXT,
    error_message TEXT,
    screenshot_artifact_id BIGINT REFERENCES artifacts(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_step_execution_results_run_id ON step_execution_results(run_id);

