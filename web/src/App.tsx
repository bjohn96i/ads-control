import { Link, Route, Routes } from "react-router-dom";
import { EnergyView } from "./views/EnergyView";
import { HomeView } from "./views/HomeView";
import { MaintenanceView } from "./views/MaintenanceView";

const LATER = ["bills", "climate", "cameras"];

export function App() {
  return (
    <Routes>
      <Route path="/" element={<HomeView />} />
      <Route path="/energy" element={<EnergyView />} />
      <Route path="/maintenance" element={<MaintenanceView />} />
      {LATER.map((page) => (
        <Route
          key={page}
          path={`/${page}`}
          element={
            <main className="home">
              <h1>{page[0].toUpperCase() + page.slice(1)}</h1>
              <p className="sub">This page comes in a later part of the build.</p>
              <Link to="/">Back to the house</Link>
            </main>
          }
        />
      ))}
    </Routes>
  );
}
