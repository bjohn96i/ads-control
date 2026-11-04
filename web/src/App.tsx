import { Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { BillsView } from "./views/BillsView";
import { CamerasView } from "./views/CamerasView";
import { ClimateView } from "./views/ClimateView";
import { EnergyView } from "./views/EnergyView";
import { HomeView } from "./views/HomeView";
import { MaintenanceView } from "./views/MaintenanceView";

export function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<HomeView />} />
        <Route path="/bills" element={<BillsView />} />
        <Route path="/cameras" element={<CamerasView />} />
        <Route path="/climate" element={<ClimateView />} />
        <Route path="/energy" element={<EnergyView />} />
        <Route path="/maintenance" element={<MaintenanceView />} />
      </Route>
    </Routes>
  );
}
