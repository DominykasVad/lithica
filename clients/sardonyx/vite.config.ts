import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// `pnpm dev` passes /api and /data on to a running Lithica, by default
// Sardonyx's image in the dev stack on port 8082, which hands them to the
// server and the data volume. LITHICA_URL points it elsewhere.
const lithica = process.env.LITHICA_URL ?? "http://localhost:8082";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { "@": path.resolve(import.meta.dirname, "src") },
  },
  server: {
    proxy: {
      "/api": { target: lithica, changeOrigin: true },
      "/data": { target: lithica, changeOrigin: true },
    },
  },
  test: {
    // the unit tests; the browser tests (e2e/) are Playwright's
    include: ["src/**/*.test.{ts,tsx}"],
    environment: "jsdom",
    setupFiles: ["./src/test-setup.ts"],
    // the tests say what they want from fetch; nothing goes out
    restoreMocks: true,
  },
});
