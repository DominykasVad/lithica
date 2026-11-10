import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { fakeSite, INFO, renderApp, type Sent } from "@/test-utils";

const LINK = {
  id: 7,
  postId: 5,
  user: { name: "ada" },
  note: "For a friend",
  creationTime: "2026-11-01T10:00:00Z",
  expiresAt: null,
  expired: false,
  url: "/share/abc",
};
const PRIVILEGES = {
  "shareLinks:create": "regular",
  "shareLinks:list:self": "regular",
  "shareLinks:delete:self": "regular",
};
function setup({
  privileges = PRIVILEGES as Record<string, string>,
  anonymous = false,
  nsfw = false,
  allowed = false,
  error = false,
} = {}) {
  if (!anonymous)
    sessionStorage.setItem(
      "sardonyx.session",
      JSON.stringify({ user: "ada", token: "token", tokenId: 1 }),
    );
  let links = [
    LINK,
    {
      ...LINK,
      id: 8,
      note: "",
      user: { name: "other" },
      expiresAt: "2020-01-01T00:00:00Z",
      expired: true,
      url: "https://example.com/share/absolute",
    },
    { ...LINK, id: 9, note: "Future", expiresAt: "2099-01-01T00:00:00Z" },
  ];
  return fakeSite({
    "GET /info": {
      body: {
        ...INFO,
        modules: [],
        shareLinksNsfw: allowed,
        config: { ...INFO.config, privileges },
      },
    },
    "GET /user/ada": { body: { rank: "regular" } },
    "GET /post/5": { body: { id: 5, type: "image", nsfw } },
    "GET /post/5/share-links": () => ({ body: { results: links } }),
    "POST /post/5/share-links": (sent: Sent) => {
      if (error)
        return {
          status: 409,
          body: {
            name: "Conflict",
            title: "Conflict",
            description: "Link limit reached.",
          },
        };
      const made = { ...LINK, id: 10, ...(sent.body as object) };
      links = [...links, made];
      return { body: made };
    },
    "DELETE /share-link/10": () => {
      links = links.filter((link) => link.id !== 10);
      return { body: {} };
    },
    "DELETE /share-link/7": () => {
      links = links.filter((link) => link.id !== 7);
      return { body: {} };
    },
  });
}
describe("post share links", () => {
  it.each([{ anonymous: true }, { privileges: {} }])(
    "hides without an authorized account: %j",
    async (options) => {
      setup(options);
      renderApp("/posts/5");
      await screen.findByRole("heading", { name: "Post 5" });
      expect(screen.queryByRole("region", { name: "Share links" })).toBeNull();
    },
  );
  it("lists notes, creators, dates and absolute URLs for a list-only rank", async () => {
    setup({ privileges: { "shareLinks:list:any": "regular" } });
    renderApp("/posts/5");
    await screen.findByText("For a friend");
    const list = screen.getByRole("list", { name: "Post share links" });
    for (const text of [
      "No note",
      "Expired",
      "Never",
      "Jan 1, 2099",
      "Nov 1, 2026",
      "By other",
    ])
      expect(list).toHaveTextContent(text);
    expect(within(list).queryByText("By ada")).toBeNull();
    expect(within(list).getAllByLabelText("Share link URL")[0]).toHaveValue(
      `${window.location.origin}/share/abc`,
    );
    expect(within(list).getAllByLabelText("Share link URL")[1]).toHaveValue(
      "https://example.com/share/absolute",
    );
    expect(screen.queryByRole("button", { name: "Create link" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Revoke" })).toBeNull();
  });
  it("creates with a bounded note and local end-of-day expiry, then focuses and copies", async () => {
    const sent = setup();
    renderApp("/posts/5");
    const user = userEvent.setup();
    const note = await screen.findByLabelText("Note (optional)");
    await user.type(note, "x".repeat(130));
    expect(note).toHaveValue("x".repeat(128));
    await user.clear(note);
    await user.type(note, "New note");
    await user.type(screen.getByLabelText("Expires (optional)"), "2099-01-02");
    await user.click(screen.getByRole("button", { name: "Create link" }));
    const row = (await screen.findByText("New note")).closest("li") as HTMLElement;
    const copy = within(row).getByRole("button", { name: "Copy share link" });
    await waitFor(() => expect(copy).toHaveFocus());
    expect(sent.find((one) => one.method === "POST")?.body).toEqual({
      note: "New note",
      expiresAt: new Date("2099-01-02T23:59:59").toISOString(),
    });
    await user.click(copy);
    expect(await navigator.clipboard.readText()).toBe(
      `${window.location.origin}/share/abc`,
    );
  });
  it("confirms before revoking an owned link", async () => {
    const sent = setup();
    renderApp("/posts/5");
    const user = userEvent.setup();
    await user.click(
      (await screen.findAllByRole("button", { name: "Revoke" }))[0] as HTMLElement,
    );
    expect(sent.some((one) => one.method === "DELETE")).toBe(false);
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("alertdialog")).toBeNull();
    await user.click(
      screen.getAllByRole("button", { name: "Revoke" })[0] as HTMLElement,
    );
    await user.click(screen.getByRole("button", { name: "Confirm revoke" }));
    await waitFor(() => expect(screen.queryByText("For a friend")).toBeNull());
    expect(sent.find((one) => one.method === "DELETE")?.path).toBe("/share-link/7");
  });
  it.each([false, true])("respects NSFW sharing enabled=%s", async (allowed) => {
    setup({ nsfw: true, allowed });
    renderApp("/posts/5");
    await screen.findByText("For a friend");
    if (allowed)
      expect(screen.getByRole("button", { name: "Create link" })).toBeInTheDocument();
    else {
      expect(
        screen.getByText("Share links for NSFW posts are off on this site."),
      ).toBeInTheDocument();
      expect(screen.getAllByText("Not delivered while the post is NSFW")).toHaveLength(
        3,
      );
      expect(screen.queryByRole("button", { name: "Create link" })).toBeNull();
    }
  });
  it("allows create-only accounts to copy and revoke the link they just made", async () => {
    const sent = setup({
      privileges: {
        "shareLinks:create": "regular",
        "shareLinks:delete:self": "regular",
      },
    });
    renderApp("/posts/5");
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Note (optional)"), "Only created");
    await user.click(screen.getByRole("button", { name: "Create link" }));
    expect(await screen.findByText("Only created")).toBeInTheDocument();
    expect(
      sent.some((one) => one.path.includes("share-links") && one.method === "GET"),
    ).toBe(false);
    await user.click(screen.getByRole("button", { name: "Revoke" }));
    await user.click(screen.getByRole("button", { name: "Confirm revoke" }));
    await waitFor(() => expect(screen.queryByText("Only created")).toBeNull());
    expect(sent.find((one) => one.method === "DELETE")?.path).toBe("/share-link/10");
  });
  it("offers revoke for others only with delete:any", async () => {
    setup({
      privileges: {
        "shareLinks:list:any": "regular",
        "shareLinks:delete:any": "regular",
      },
    });
    renderApp("/posts/5");
    await screen.findByText("By other");
    expect(screen.getAllByRole("button", { name: "Revoke" })).toHaveLength(3);
  });
  it("shows API errors", async () => {
    setup({ error: true });
    renderApp("/posts/5");
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "Create link" }));
    expect(await screen.findByText("Link limit reached.")).toBeInTheDocument();
  });
});
