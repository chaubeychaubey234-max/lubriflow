"use client";
import { useEffect, useState, FormEvent } from "react";

async function request(path: string, body?: Record<string, string>) {
  const response = await fetch("/api/auth/mfa" + path, {
    method: body ? "POST" : "GET",
    credentials: "same-origin",
    headers: body
      ? { "Content-Type": "application/json", "X-Lubriflow-Request": "1" }
      : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const result = await response.json();
  if (!response.ok)
    throw new Error(
      typeof result.detail === "string"
        ? result.detail
        : "Security request failed.",
    );
  return result;
}

export default function AccountSecurity() {
  const [status, setStatus] = useState<{
    enabled: boolean;
    available: boolean;
    recovery_remaining: number;
  } | null>(null);
  const [secret, setSecret] = useState("");
  const [codes, setCodes] = useState<string[]>([]);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    request("")
      .then(setStatus)
      .catch((error) => setMessage(error.message));
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    const form = event.currentTarget;
    const data = new FormData(form);
    const action = String(data.get("action") || (secret ? "confirm" : "begin"));
    setBusy(true);
    setMessage("");
    setCodes([]);
    try {
      const result = await request("/" + action, {
        password: String(data.get("password") || ""),
        code: String(data.get("code") || ""),
      });
      form.reset();
      setSecret(result.secret || "");
      setCodes(result.recovery_codes || []);
      setStatus(await request(""));
      setMessage(
        action === "begin"
          ? "Add the setup key to your authenticator, then confirm with its six-digit code."
          : "Account security updated. Other sessions have been signed out.",
      );
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="panel">
      <h2>Two-step verification</h2>
      <p>
        Use an authenticator app to protect your account. Setup expires after
        ten minutes.
      </p>
      {message && (
        <p role="status" className="notice">
          {message}
        </p>
      )}
      {status && (
        <p>
          {status.enabled
            ? `Enabled · ${status.recovery_remaining} recovery codes remaining`
            : "Not enabled"}
        </p>
      )}
      {status && !status.available && (
        <p>
          Your administrator must configure the authenticator encryption key
          before setup.
        </p>
      )}
      {secret && (
        <div className="notice">
          <p>
            In your authenticator app, add a time-based account named LubriFlow
            using this private setup key:
          </p>
          <code style={{ overflowWrap: "anywhere" }}>{secret}</code>
          <p>Keep this key private. Codes change every 30 seconds.</p>
        </div>
      )}
      {codes.length > 0 && (
        <div className="notice">
          <strong>
            Save these recovery codes now. They will not be shown again.
          </strong>
          <p>
            Each code works once in place of an authenticator code. Keep them in
            a password manager or another secure place.
          </p>
          <pre style={{ overflowX: "auto" }}>{codes.join("\n")}</pre>
          <button type="button" onClick={() => setCodes([])}>
            I have saved my recovery codes
          </button>
        </div>
      )}
      {status?.available && (
        <form onSubmit={submit}>
          <div className="grid">
            <label>
              Current password
              <input
                type="password"
                name="password"
                required
                maxLength={128}
                autoComplete="current-password"
              />
            </label>
            {(secret || status.enabled) && (
              <label>
                Authenticator or recovery code
                <input
                  name="code"
                  required
                  maxLength={100}
                  autoComplete="one-time-code"
                  spellCheck={false}
                />
              </label>
            )}
            {status.enabled && (
              <label>
                Action
                <select name="action">
                  <option value="recovery">Replace recovery codes</option>
                  <option value="disable">Disable two-step verification</option>
                </select>
              </label>
            )}
          </div>
          <button disabled={busy || codes.length > 0}>
            {busy
              ? "Saving…"
              : status.enabled
                ? "Update security"
                : secret
                  ? "Confirm and enable"
                  : "Set up authenticator"}
          </button>
          {secret && (
            <button
              type="button"
              disabled={busy}
              onClick={() => {
                setSecret("");
                setMessage("");
              }}
            >
              Start again
            </button>
          )}
        </form>
      )}
    </section>
  );
}
