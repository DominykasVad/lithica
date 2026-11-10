import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { fakeSite, INFO, renderApp, type Sent } from "@/test-utils";

function setup(
  privileges: Record<string, string> = {
    "shareLinks:list:self": "regular",
    "shareLinks:delete:self": "regular",
  },
) {
  sessionStorage.setItem(
    "sardonyx.session",
    JSON.stringify({ user: "ada", token: "token", tokenId: 1 }),
  );
  let revoked = false;
  return fakeSite({
    "GET /info": { body: { ...INFO, config: { ...INFO.config, privileges } } },
    "GET /user/ada": { body: { rank: "regular" } },
    "GET /user/ada/share-links": (sent: Sent) => ({
      body: {
        total: revoked ? 50 : 51,
        results: revoked
          ? []
          : [
              {
                id: sent.path.includes("offset=50") ? 8 : 7,
                postId: 5,
                note: "Account note",
                user: { name: "ada" },
                url: "/share/abc",
                expiresAt: null,
              },
            ],
      },
    }),
    "DELETE /share-link/8": () => {
      revoked = true;
      return { body: {} };
    },
  });
}
describe("account share links", () => {
  it("pages using the library size and revokes after confirmation", async () => {
    localStorage.setItem("sardonyx.perPage", "50");
    const sent = setup();
    renderApp("/account");
    const user = userEvent.setup();
    const region = await screen.findByRole("region", { name: "Share links" });
    await within(region).findByText("Account note");
    expect(within(region).getByRole("link", { name: "Post 5" })).toHaveAttribute(
      "href",
      "/posts/5",
    );
    expect(within(region).getByLabelText("Share link URL")).toHaveValue(
      `${window.location.origin}/share/abc`,
    );
    expect(within(region).getByRole("button", { name: "Previous" })).toBeDisabled();
    await user.click(within(region).getByRole("button", { name: "Next" }));
    await waitFor(() =>
      expect(sent.some((one) => one.path.includes("offset=50&limit=50"))).toBe(true),
    );
    await waitFor(() =>
      expect(within(region).getByRole("button", { name: "Previous" })).toBeEnabled(),
    );
    expect(within(region).getByRole("button", { name: "Next" })).toBeDisabled();
    await user.click(within(region).getByRole("button", { name: "Previous" }));
    await waitFor(() =>
      expect(within(region).getByRole("button", { name: "Next" })).toBeEnabled(),
    );
    await user.click(within(region).getByRole("button", { name: "Next" }));
    await waitFor(() =>
      expect(within(region).getByRole("button", { name: "Previous" })).toBeEnabled(),
    );
    await user.click(within(region).getByRole("button", { name: "Revoke" }));
    expect(sent.some((one) => one.method === "DELETE")).toBe(false);
    await user.click(within(region).getByRole("button", { name: "Confirm revoke" }));
    await within(region).findByText("No share links.");
    expect(sent.find((one) => one.method === "DELETE")?.path).toBe("/share-link/8");
    expect(within(region).queryByRole("button", { name: "Create link" })).toBeNull();
  });
  it("uses the library batch size for auto mode", async () => {
    const sent = setup();
    renderApp("/account");
    await screen.findByText("Account note");
    expect(sent.some((one) => one.path.includes("offset=0&limit=100"))).toBe(true);
  });
  it("hides without list:self", async () => {
    setup({});
    renderApp("/account");
    await screen.findByLabelText("Current password");
    expect(screen.queryByRole("region", { name: "Share links" })).toBeNull();
  });
});
