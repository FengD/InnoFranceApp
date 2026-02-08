import { useState } from "react";

interface LoginPanelProps {
  onLogin: (username: string, password: string) => Promise<void>;
  onWeChatLogin: () => Promise<void>;
  error?: string | null;
}

export function LoginPanel({ onLogin, onWeChatLogin, error }: LoginPanelProps) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [wechatBusy, setWechatBusy] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!username.trim() || !password.trim()) return;
    setSubmitting(true);
    try {
      await onLogin(username.trim(), password);
    } finally {
      setSubmitting(false);
    }
  };

  const handleWeChat = async () => {
    setWechatBusy(true);
    try {
      await onWeChatLogin();
    } finally {
      setWechatBusy(false);
    }
  };

  return (
    <div className="login-panel">
      <div className="login-panel-inner">
        <h2>Sign in</h2>
        <p className="muted">Use your account to access your pipelines.</p>
        <form onSubmit={handleSubmit} className="login-form">
          <div className="form-group">
            <label htmlFor="login-username">Username</label>
            <input
              id="login-username"
              type="text"
              autoComplete="username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="admin"
            />
          </div>
          <div className="form-group">
            <label htmlFor="login-password">Password</label>
            <input
              id="login-password"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="admin"
            />
          </div>
          <button
            type="submit"
            className="btn btn-primary"
            disabled={submitting || !username.trim() || !password.trim()}
          >
            {submitting ? "Signing in…" : "Sign in"}
          </button>
        </form>
        <div className="login-divider">
          <span>or</span>
        </div>
        <button
          type="button"
          className="btn btn-ghost"
          onClick={handleWeChat}
          disabled={wechatBusy}
        >
          {wechatBusy ? "Opening WeChat…" : "Sign in with WeChat"}
        </button>
        {error && (
          <div className="banner banner-error" role="alert">
            {error}
          </div>
        )}
      </div>
    </div>
  );
}
