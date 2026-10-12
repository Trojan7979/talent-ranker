import { createContext, useContext, useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import "./recruiterNav.css";

type RecruiterSession = { token: string; setToken: (token: string) => void };
const SessionContext = createContext<RecruiterSession | null>(null);

export function useRecruiterSession(): RecruiterSession {
  const session = useContext(SessionContext);
  if (!session) throw new Error("Recruiter session requires RecruiterLayout");
  return session;
}

export function RecruiterLayout() {
  const [token, setToken] = useState("");
  return (
    <SessionContext.Provider value={{ token, setToken }}>
      <nav className="recruiter-nav" aria-label="Recruiter navigation">
        <NavLink to="/sources">Resume sources</NavLink>
        <NavLink to="/ranking">Ranking</NavLink>
        <NavLink to="/shortlists">Saved shortlists</NavLink>
        <NavLink to="/screening/campaigns">Screening campaigns</NavLink>
      </nav>
      <Outlet />
    </SessionContext.Provider>
  );
}
