import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// `pnpm dev` passes /api and /data on to a running Lithica, by default the
// dev stack's client on port 8080, which hands them to the server and the
// data volume. LITHICA_URL points it elsewhere.
const lithica = process.env.LITHICA_URL ?? "http://localhost:8080";

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
    environment: "jsdom",
    setupFiles: ["./src/test-setup.ts"],
    // the tests say what they want from fetch; nothing goes out
    restoreMocks: true,
  },
});
