import { NavLink, Outlet } from "react-router-dom";
import "./recruiterNav.css";

export function RecruiterLayout() {
  return (
    <>
      <nav className="recruiter-nav" aria-label="Recruiter navigation">
        <NavLink to="/ranking">Ranking</NavLink>
        <NavLink to="/shortlists">Saved shortlists</NavLink>
      </nav>
      <Outlet />
    </>
  );
}
