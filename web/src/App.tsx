import { Link, Route, Routes } from "react-router-dom";
import { HomeView } from "./views/HomeView";

const LATER = ["energy", "maintenance", "bills", "climate", "cameras"];

export function App() {
  return (
    <Routes>
      <Route path="/" element={<HomeView />} />
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
