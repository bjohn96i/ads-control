import { useQuery, useQueryClient } from "@tanstack/react-query";
import { NavLink, Outlet } from "react-router-dom";
import { getJson, send } from "../api/client";

const PAGES = [
  { to: "/", label: "Home" },
  { to: "/energy", label: "Energy" },
  { to: "/climate", label: "Climate" },
  { to: "/cameras", label: "Cameras" },
  { to: "/bills", label: "Bills" },
  { to: "/maintenance", label: "Maintenance" },
];

/** Unlocking lasts 90 days on a device; this ends it now, for a shared or borrowed screen. */
function LockButton() {
  const client = useQueryClient();
  const { data } = useQuery({
    queryKey: ["auth-status"],
    queryFn: () => getJson<{ pin_set: boolean; unlocked: boolean }>("/api/auth/status"),
  });
  if (!data?.unlocked) return null;
  const lock = async () => {
    await send("POST", "/api/auth/lock");
    client.invalidateQueries({ queryKey: ["auth-status"] });
  };
  return (
    <div className="foot">
      <span>Unlocked</span>
      <button type="button" onClick={lock}>
        Lock
      </button>
    </div>
  );
}

export function Layout() {
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
        <LockButton />
      </aside>
      <Outlet />
    </div>
  );
}
