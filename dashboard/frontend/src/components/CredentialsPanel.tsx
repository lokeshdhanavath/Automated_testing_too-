import React, { useEffect, useState } from "react";
import {
  KeyRound,
  Plus,
  Trash2,
  Pencil,
  ShieldCheck,
  Search,
  Lock,
  RefreshCw,
  X,
  CheckCircle2,
  AlertCircle,
} from "lucide-react";
import {
  getProjectCredentials,
  createProjectCredential,
  updateProjectCredential,
  deleteProjectCredential,
} from "../services/api";
import type { CredentialItem, CredentialPayload } from "../services/api";

interface CredentialsPanelProps {
  projectId: string;
  projectName: string;
}

export const CredentialsPanel: React.FC<CredentialsPanelProps> = ({
  projectId,
  projectName,
}) => {
  const [credentials, setCredentials] = useState<CredentialItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  // Form modal state
  const [modalOpen, setModalOpen] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState<CredentialPayload>({
    name: "",
    username: "",
    secret: "",
    environment: "QA",
    description: "",
  });

  const loadCredentials = async () => {
    if (!projectId) return;
    setLoading(true);
    setError(null);
    try {
      const data = await getProjectCredentials(projectId);
      setCredentials(data);
    } catch (err: any) {
      setError(err?.message || "Failed to load credentials.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadCredentials();
  }, [projectId]);

  const handleOpenAdd = () => {
    setEditingId(null);
    setForm({
      name: "",
      username: "",
      secret: "",
      environment: "QA",
      description: "",
    });
    setModalOpen(true);
  };

  const handleOpenEdit = (item: CredentialItem) => {
    setEditingId(item.id);
    setForm({
      name: item.name,
      username: item.username,
      secret: "", // blank means keep unchanged on edit
      environment: item.environment,
      description: item.description,
    });
    setModalOpen(true);
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.name.trim() || !form.username.trim()) {
      setError("Name and username are required.");
      return;
    }
    if (!editingId && !form.secret.trim()) {
      setError("Secret/Password is required for new credentials.");
      return;
    }

    setSaving(true);
    setError(null);
    try {
      if (editingId) {
        await updateProjectCredential(editingId, {
          name: form.name.trim(),
          username: form.username.trim(),
          secret: form.secret.trim() || undefined,
          environment: form.environment,
          description: form.description?.trim() || undefined,
        });
        setSuccess("Credential updated successfully.");
      } else {
        await createProjectCredential(projectId, {
          name: form.name.trim(),
          username: form.username.trim(),
          secret: form.secret.trim(),
          environment: form.environment,
          description: form.description?.trim() || "",
        });
        setSuccess("Credential created and securely encrypted.");
      }
      setModalOpen(false);
      void loadCredentials();
      setTimeout(() => setSuccess(null), 4000);
    } catch (err: any) {
      setError(err?.message || "Failed to save credential.");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: string, name: string) => {
    if (!confirm(`Are you sure you want to delete credential "${name}"?`)) return;
    try {
      await deleteProjectCredential(id);
      setSuccess(`Credential "${name}" removed.`);
      void loadCredentials();
      setTimeout(() => setSuccess(null), 4000);
    } catch (err: any) {
      setError(err?.message || "Failed to delete credential.");
    }
  };

  const filtered = credentials.filter(
    (c) =>
      c.name.toLowerCase().includes(search.toLowerCase()) ||
      c.username.toLowerCase().includes(search.toLowerCase()) ||
      c.environment.toLowerCase().includes(search.toLowerCase()),
  );

  return (
    <div className="credentials-panel-wrap">
      <div className="card">
        <div className="card-heading-row" style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <div className="card-heading-icon" style={{ padding: 8, borderRadius: 8, background: "rgba(0, 214, 176, 0.12)", color: "#00d6b0" }}>
                <KeyRound size={22} />
              </div>
              <div>
                <h2 style={{ margin: 0, fontSize: "1.15rem", fontWeight: 700, color: "var(--vq-text, #fff)" }}>
                  Application Credentials
                </h2>
                <span className="muted-text" style={{ fontSize: "0.85rem" }}>
                  Manage authenticated secrets for <strong>{projectName}</strong>. Encrypted at rest via Fernet authenticated encryption.
                </span>
              </div>
            </div>
          </div>

          <div style={{ display: "flex", gap: 10 }}>
            <button
              className="button button-secondary button-small"
              onClick={() => void loadCredentials()}
              disabled={loading}
              title="Refresh credentials"
            >
              <RefreshCw size={15} className={loading ? "spin" : ""} />
              Refresh
            </button>
            <button
              className="button button-primary button-small"
              onClick={handleOpenAdd}
            >
              <Plus size={15} />
              Add Credential
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

        {/* Search Toolbar */}
        <div style={{ display: "flex", gap: 12, marginBottom: 16 }}>
          <div style={{ position: "relative", flex: 1 }}>
            <Search
              size={16}
              style={{ position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)", color: "var(--vq-muted, #7188a6)" }}
            />
            <input
              type="text"
              placeholder="Search by profile name, username, or environment..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              style={{ width: "100%", paddingLeft: 36, height: 38 }}
            />
          </div>
        </div>

        {/* Credentials Table */}
        {loading && credentials.length === 0 ? (
          <div style={{ padding: 40, textAlign: "center", color: "var(--vq-muted)" }}>
            Loading encrypted credentials...
          </div>
        ) : filtered.length === 0 ? (
          <div style={{ padding: 40, textAlign: "center", background: "var(--vq-surface-2, rgba(255,255,255,0.02))", borderRadius: 8, border: "1px dashed var(--vq-border)" }}>
            <Lock size={32} style={{ color: "var(--vq-muted)", marginBottom: 8, opacity: 0.7 }} />
            <div style={{ fontWeight: 600, color: "var(--vq-text)" }}>No credentials configured</div>
            <div className="muted-text" style={{ fontSize: "0.85rem", marginTop: 4, marginBottom: 16 }}>
              Add username and secret profiles to use with automated scenarios without exposing credentials in test definitions.
            </div>
            <button className="button button-primary button-small" onClick={handleOpenAdd}>
              <Plus size={15} /> Add Credential
            </button>
          </div>
        ) : (
          <div className="table-responsive" style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.9rem" }}>
              <thead>
                <tr style={{ borderBottom: "1px solid var(--vq-border)", textAlign: "left", color: "var(--vq-muted)" }}>
                  <th style={{ padding: "10px 12px" }}>PROFILE NAME</th>
                  <th style={{ padding: "10px 12px" }}>USERNAME</th>
                  <th style={{ padding: "10px 12px" }}>MASKED SECRET</th>
                  <th style={{ padding: "10px 12px" }}>ENVIRONMENT</th>
                  <th style={{ padding: "10px 12px" }}>DESCRIPTION</th>
                  <th style={{ padding: "10px 12px", textAlign: "right" }}>ACTIONS</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((c) => (
                  <tr
                    key={c.id}
                    style={{ borderBottom: "1px solid var(--vq-border)", transition: "background 0.2s" }}
                  >
                    <td style={{ padding: "12px", fontWeight: 600, color: "var(--v-text)" }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <ShieldCheck size={16} style={{ color: "var(--v-accent)" }} />
                        {c.name}
                      </div>
                    </td>
                    <td style={{ padding: "12px", fontFamily: "monospace" }}>{c.username}</td>
                    <td style={{ padding: "12px" }}>
                      <code style={{ background: "var(--v-surface-2)", border: "1px solid var(--v-border)", padding: "3px 8px", borderRadius: 4, letterSpacing: 2, color: "var(--v-text)" }}>
                        {c.masked_secret}
                      </code>
                    </td>
                    <td style={{ padding: "12px" }}>
                      <span
                        className="badge"
                        style={{
                          background: c.environment === "Production" ? "#FEE2E2" : "#DEF7EC",
                          color: c.environment === "Production" ? "#DC2626" : "#03543F",
                          padding: "3px 8px",
                          borderRadius: 6,
                          fontSize: "0.75rem",
                          fontWeight: 700,
                        }}
                      >
                        {c.environment}
                      </span>
                    </td>
                    <td style={{ padding: "12px", color: "var(--v-text-secondary)", fontSize: "0.85rem" }}>
                      {c.description || "—"}
                    </td>
                    <td style={{ padding: "12px", textAlign: "right" }}>
                      <div style={{ display: "inline-flex", gap: 6 }}>
                        <button
                          className="button button-secondary button-small"
                          onClick={() => handleOpenEdit(c)}
                          title="Edit Credential"
                          style={{ padding: "4px 8px" }}
                        >
                          <Pencil size={13} />
                        </button>
                        <button
                          className="button button-secondary button-small"
                          onClick={() => handleDelete(c.id, c.name)}
                          title="Delete Credential"
                          style={{ padding: "4px 8px", color: "#DC2626" }}
                        >
                          <Trash2 size={13} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div style={{ marginTop: 20, padding: "12px 16px", borderRadius: 8, background: "#EFF6FF", border: "1px solid #DBEAFE", display: "flex", gap: 10, alignItems: "flex-start" }}>
          <ShieldCheck size={18} style={{ color: "var(--v-accent)", marginTop: 2, flexShrink: 0 }} />
          <div style={{ fontSize: "0.82rem", color: "#1E40AF" }}>
            <strong style={{ color: "#1E3A8A" }}>Encryption Architecture: </strong>
            Secrets are encrypted at submission using 256-bit Fernet authenticated encryption before persistence into PostgreSQL. Decryption occurs strictly in-memory during test scenario playback. Credential values can be referenced dynamically in scenarios using <code style={{ color: "var(--v-accent)", fontWeight: 600 }}>{"{{username}}"}</code> and <code style={{ color: "var(--v-accent)", fontWeight: 600 }}>{"{{password}}"}</code>.
          </div>
        </div>
      </div>

      {/* Modal Dialog */}
      {modalOpen && (
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
              maxWidth: 520,
              boxShadow: "0 10px 40px rgba(0,0,0,0.6)",
              border: "1px solid var(--vq-border)",
            }}
          >
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <KeyRound size={20} style={{ color: "var(--v-accent)" }} />
                <h3 style={{ margin: 0, fontSize: "1.1rem", color: "var(--v-text)" }}>
                  {editingId ? "Edit Credential Profile" : "Register New Credential"}
                </h3>
              </div>
              <button
                className="button button-secondary button-small"
                onClick={() => setModalOpen(false)}
                style={{ padding: 4 }}
              >
                <X size={16} />
              </button>
            </div>

            <form onSubmit={handleSave} className="form-stack">
              <label className="field">
                <span>Profile Name *</span>
                <input
                  type="text"
                  placeholder="e.g. Standard QA User"
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  required
                />
              </label>

              <label className="field">
                <span>Username / Identifier *</span>
                <input
                  type="text"
                  placeholder="e.g. lokesh_test"
                  value={form.username}
                  onChange={(e) => setForm({ ...form, username: e.target.value })}
                  required
                />
              </label>

              <label className="field">
                <span>
                  Password / Secret {editingId ? "(Leave blank to keep unchanged)" : "*"}
                </span>
                <input
                  type="password"
                  placeholder={editingId ? "•••••••• (unchanged)" : "Enter secret password"}
                  value={form.secret}
                  onChange={(e) => setForm({ ...form, secret: e.target.value })}
                  required={!editingId}
                />
              </label>

              <label className="field">
                <span>Environment Profile</span>
                <select
                  value={form.environment}
                  onChange={(e) => setForm({ ...form, environment: e.target.value })}
                >
                  <option value="QA">QA</option>
                  <option value="Development">Development</option>
                  <option value="Staging">Staging</option>
                  <option value="Production">Production</option>
                </select>
              </label>

              <label className="field">
                <span>Description (Optional)</span>
                <input
                  type="text"
                  placeholder="Purpose of this account profile"
                  value={form.description || ""}
                  onChange={(e) => setForm({ ...form, description: e.target.value })}
                />
              </label>

              <div style={{ display: "flex", justifyContent: "flex-end", gap: 10, marginTop: 12 }}>
                <button
                  type="button"
                  className="button button-secondary"
                  onClick={() => setModalOpen(false)}
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="button button-primary"
                  disabled={saving}
                >
                  {saving ? "Encrypting & Saving..." : editingId ? "Update Profile" : "Save Credential"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};

