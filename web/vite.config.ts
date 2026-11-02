import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

const API = "http://localhost:8100";

export default defineConfig({
  plugins: [react()],
  server: { port: 5174, proxy: { "/api": { target: API, changeOrigin: false } } },
  test: { environment: "jsdom", globals: true, setupFiles: ["./src/vitest.setup.ts"] },
});
