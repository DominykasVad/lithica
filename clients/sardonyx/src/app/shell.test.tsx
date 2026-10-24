import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { fakeSite, INFO, renderApp } from "@/test-utils";

describe("the app shell", () => {
  it("carries the name and the mark of Sardonyx", async () => {
    fakeSite({ "GET /info": { body: INFO }, "GET /posts": { body: { total: 0 } } });
    renderApp("/");
    const banner = await screen.findByRole("banner");
    expect(within(banner).getByRole("link", { name: "Sardonyx" })).toBeInTheDocument();
    expect(banner.querySelector("svg")).not.toBeNull();
  });

  it("on a site with cards, shows what is about cards", async () => {
    const sent = fakeSite({
      "GET /info": { body: INFO },
      "GET /posts": { body: { total: 12, results: [] } },
    });
    renderApp("/");
    expect(
      await screen.findByText("Character cards", { selector: "span" }),
    ).toBeInTheDocument();
    expect(await screen.findByText("12 cards on this site")).toBeInTheDocument();
    expect(sent.map((one) => one.path)).toContain(
      "/posts?query=card-spec%3Av1%2Cv2%2Cv3&limit=1&fields=id",
    );
  });

  it("on a site without cards, shows nothing of them and asks nothing about them", async () => {
    const sent = fakeSite({ "GET /info": { body: { ...INFO, modules: [] } } });
    renderApp("/");
    expect(
      await screen.findByRole("heading", { name: "My cards" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/card/i, { selector: "span, h2, p, [data-slot=card-title]" }),
    ).toBeNull();
    expect(screen.queryByText("Character cards")).toBeNull();
    expect(sent.map((one) => one.path)).toEqual(["/info"]);
  });

  it("asks GET /info once at the start, whatever the page", async () => {
    const sent = fakeSite({
      "GET /info": { body: INFO },
      "GET /posts": { body: { total: 0 } },
    });
    renderApp("/login");
    await waitFor(() => expect(sent.map((one) => one.path)).toContain("/info"));
    expect(sent.filter((one) => one.path === "/info")).toHaveLength(1);
    expect(
      screen.getByText("Character cards", { selector: "span" }),
    ).toBeInTheDocument();
  });

  it("shows a page that is not there as such", async () => {
    fakeSite({ "GET /info": { body: INFO } });
    renderApp("/no/such/page");
    expect(
      await screen.findByRole("heading", { name: "Not found" }),
    ).toBeInTheDocument();
  });

  it("switches between light, dark and the system's theme, and keeps the choice", async () => {
    fakeSite({ "GET /info": { body: INFO }, "GET /posts": { body: { total: 0 } } });
    renderApp("/");
    const user = userEvent.setup();
    expect(document.documentElement).not.toHaveClass("dark");

    await user.click(await screen.findByRole("button", { name: "Theme" }));
    await user.click(await screen.findByRole("menuitemradio", { name: "Dark" }));
    expect(document.documentElement).toHaveClass("dark");
    expect(localStorage.getItem("sardonyx.theme")).toBe("dark");

    await user.click(screen.getByRole("button", { name: "Theme" }));
    await user.click(
      await screen.findByRole("menuitemradio", { name: "As the system" }),
    );
    expect(document.documentElement).not.toHaveClass("dark");
    expect(localStorage.getItem("sardonyx.theme")).toBeNull();
  });
});
