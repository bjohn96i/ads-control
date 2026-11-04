import { NavLink, Outlet } from "react-router-dom";

const PAGES = [
  { to: "/", label: "Home" },
  { to: "/energy", label: "Energy" },
  { to: "/climate", label: "Climate" },
  { to: "/cameras", label: "Cameras" },
  { to: "/bills", label: "Bills" },
  { to: "/maintenance", label: "Maintenance" },
];

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
      </aside>
      <Outlet />
    </div>
  );
}
