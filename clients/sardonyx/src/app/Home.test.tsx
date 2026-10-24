import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Home } from "./Home";

function renderHome() {
  // no retries: a failure is to be shown, not waited out
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <Home />
    </QueryClientProvider>,
  );
}

function answering(body: unknown, status = 200) {
  return vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

const INFO = {
  postCount: 67,
  diskUsage: null,
  serverTime: "2026-10-24T09:00:00Z",
  modules: ["cards"],
  config: { name: "My cards" },
};

describe("the start page", () => {
  it("shows what GET /info says", async () => {
    const fetch = answering(INFO);
    renderHome();
    expect(await screen.findByText("My cards")).toBeInTheDocument();
    expect(screen.getByText("67")).toBeInTheDocument();
    expect(screen.getByText("cards")).toBeInTheDocument();
    const request = fetch.mock.calls[0]?.[0];
    expect(request instanceof Request && new URL(request.url).pathname).toBe(
      "/api/info",
    );
  });

  it("says so when the site has no module", async () => {
    answering({ ...INFO, modules: [] });
    renderHome();
    expect(await screen.findByText("none")).toBeInTheDocument();
  });

  it("says so when the site does not answer", async () => {
    answering(
      {
        name: "HttpError",
        title: "Service unavailable",
        description: "Down for a bit.",
      },
      503,
    );
    renderHome();
    expect(await screen.findByRole("alert")).toHaveTextContent("Down for a bit.");
  });
});
