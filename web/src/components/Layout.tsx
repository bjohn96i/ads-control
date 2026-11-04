import { useQuery } from "@tanstack/react-query";
import { NavLink, Outlet } from "react-router-dom";
import { getJson, type Live } from "../api/client";
import { PERIOD_LABEL } from "./format";

const PAGES = [
  { to: "/", label: "Home" },
  { to: "/energy", label: "Energy" },
  { to: "/climate", label: "Climate" },
  { to: "/cameras", label: "Cameras" },
  { to: "/bills", label: "Bills" },
  { to: "/maintenance", label: "Maintenance" },
];

export function Layout() {
  const { data } = useQuery({
    queryKey: ["live"],
    queryFn: () => getJson<Live>("/api/live"),
    refetchInterval: 5000,
  });
  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          ADS<span>·</span>CONTROL
        </div>
        <nav className="nav">
          {PAGES.map((page) => (
            <NavLink key={page.to} to={page.to} end>
              {page.label}
            </NavLink>
          ))}
        </nav>
        {data ? (
          <div className="foot">
            {data.outdoor_f !== null ? <div>{Math.round(data.outdoor_f)}°F outside</div> : null}
            <div>{PERIOD_LABEL[data.rate_period]}</div>
          </div>
        ) : null}
      </aside>
      <Outlet />
    </div>
  );
}
