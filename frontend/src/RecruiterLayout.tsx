import { createContext, useContext, useEffect, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import "./recruiterNav.css";

type RecruiterSession = { token: string; setToken: (token: string) => void; email: string | null };
const SessionContext = createContext<RecruiterSession | null>(null);

export function useRecruiterSession(): RecruiterSession {
  const session = useContext(SessionContext);
  if (!session) throw new Error("Recruiter session requires RecruiterLayout");
  return session;
}

export function RecruiterLayout() {
  const [email, setEmail] = useState<string | null>(null);
  const [provider, setProvider] = useState<string | null>(null);
  const [recruiterId, setRecruiterId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loginUrls, setLoginUrls] = useState<Record<string, string>>({});
  const [providerError, setProviderError] = useState(false);
  const [sessionError, setSessionError] = useState(false);
  const [signOutError, setSignOutError] = useState(false);
  useEffect(() => {
    fetch("/api/auth/providers").then((response) => {
      if (!response.ok) throw new Error("Sign-in service unavailable");
      return response.json();
    })
      .then((data: { login_urls: Record<string, string> }) => setLoginUrls(data.login_urls ?? {}))
      .catch(() => setProviderError(true));
    fetch("/api/auth/me").then((response) => {
      if (response.status === 401) return null;
      if (!response.ok) throw new Error("Could not check account");
      return response.json();
    }).then((account: { recruiter_id: string; email: string | null; provider: string } | null) => {
      setRecruiterId(account?.recruiter_id ?? null);
      setEmail(account?.email ?? null);
      setProvider(account?.provider ?? null);
    }).catch(() => setSessionError(true)).finally(() => setLoading(false));
  }, []);
  const token = recruiterId ?? "";
  const setToken = (value: string) => { void value; /* Legacy call sites cannot set recruiter identity. */ };
  async function signOut() {
    setSignOutError(false);
    try {
      const response = await fetch("/api/auth/logout", { method: "POST" });
      if (!response.ok) throw new Error("Sign-out failed");
      setRecruiterId(null); setEmail(null); setProvider(null);
    } catch { setSignOutError(true); }
  }
  if (loading) return <p className="recruiter-auth-loading" role="status">Checking your account...</p>;
  if (!recruiterId) return (
    <main className="recruiter-auth-page">
      <section className="recruiter-auth-card" aria-labelledby="recruiter-auth-title">
        <div className="recruiter-auth-brand"><span className="recruiter-auth-mark" aria-hidden="true">R</span>Recruitment Agent</div>
        <p className="recruiter-auth-eyebrow">Recruiter workspace</p>
        <h1 id="recruiter-auth-title">Sign in to Recruitment Agent</h1>
        <p className="recruiter-auth-intro">Sign in with your work account to continue to your jobs and conversations.</p>
        <div className="recruiter-auth-providers">
          {Object.entries(loginUrls).map(([provider, loginUrl]) => (
            <a className="recruiter-auth-provider" key={provider} href={loginUrl}>
              <span className={`recruiter-auth-provider-icon recruiter-auth-provider-icon-${provider}`} aria-hidden="true">
                {provider === "google" ? "G" : <span className="recruiter-auth-microsoft-mark" />}
              </span>
              Continue with {provider === "google" ? "Google" : "Microsoft"}
            </a>
          ))}
          {!Object.keys(loginUrls).length && <p className="recruiter-auth-unavailable" role="alert">
            {providerError ? "Sign-in service is unavailable. Check that the API is running, then refresh this page."
              : "Account sign-in is not configured. Ask your administrator to configure Google or Microsoft sign-in."}
          </p>}
        </div>
        {sessionError && <p className="recruiter-auth-unavailable" role="alert">Could not confirm your current account. Refresh this page to try again.</p>}
        <p className="recruiter-auth-note">Signing in does not connect your Drive, SharePoint, or Gmail account.</p>
      </section>
    </main>
  );
  return (
    <SessionContext.Provider value={{ token, setToken, email: email ?? recruiterId }}>
      <nav className="recruiter-nav" aria-label="Recruiter navigation">
        <div className="recruiter-nav-links">
          <NavLink to="/sources">Resume sources</NavLink>
          <NavLink to="/ranking">Ranking</NavLink>
          <NavLink to="/shortlists">Saved shortlists</NavLink>
          <NavLink to="/screening/campaigns">Screening campaigns</NavLink>
          <NavLink to="/agents">Agent Workforce</NavLink>
        </div>
        <div className="recruiter-account-actions">
          <div className="recruiter-account" aria-label={`Signed in as ${email ?? "recruiter"}`}>
            <span className="recruiter-account-avatar" aria-hidden="true">{(email ?? "R")[0].toUpperCase()}</span>
            <span className="recruiter-account-copy"><small>Signed in{provider ? ` with ${provider === "google" ? "Google" : "Microsoft"}` : ""}</small><strong>{email ?? "Recruiter account"}</strong></span>
          </div>
          <button className="recruiter-sign-out" type="button" onClick={() => void signOut()}>Sign out</button>
        </div>
        {signOutError && <p className="recruiter-sign-out-error" role="alert">Could not sign out. Please try again.</p>}
      </nav>
      <Outlet />
    </SessionContext.Provider>
  );
}
