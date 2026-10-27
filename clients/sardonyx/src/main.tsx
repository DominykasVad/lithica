import { QueryClientProvider } from "@tanstack/react-query";
import { RouterProvider } from "@tanstack/react-router";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { NsfwProvider } from "./app/nsfw";
import { queryClient } from "./app/queryClient";
import { ThemeProvider } from "./app/theme";
import { AuthProvider } from "./auth/AuthProvider";
import { router } from "./router";
import "./index.css";

const root = document.getElementById("root");
if (!root) {
  throw new Error("index.html has no #root");
}
createRoot(root).render(
  <StrictMode>
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <NsfwProvider>
            <RouterProvider router={router} />
          </NsfwProvider>
        </AuthProvider>
      </QueryClientProvider>
    </ThemeProvider>
  </StrictMode>,
);
