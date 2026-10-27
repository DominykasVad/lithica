import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { fakeSite, INFO, renderApp, type Sent } from "@/test-utils";
import { CREATOR_COLOR } from "./categories";
import { tagQuery } from "./search";

const TOKEN = "f5a2c0de-0000-4000-8000-000000000001";

const PRIVILEGES = {
  "tags:list": "regular",
  // GET /info writes the names in camelCase (tag_categories:create in the config)
  "tagCategories:create": "moderator",
};

const CATEGORIES = [
  { name: "meta", color: "#336699", order: 3, usages: 1, default: false },
  { name: "default", color: "default", order: 1, usages: 9, default: true },
  { name: "character", color: "#aa3366", order: 2, usages: 4, default: false },
];

function tag(name: string, category: string, usages: number) {
  return { names: [name], category, usages };
}

/** A site with 120 tags (one page here: what it was asked is the test's). */
function site({
  rank = "regular" as string | null,
  modules = ["cards"],
  categories = CATEGORIES,
} = {}) {
  if (rank !== null) {
    sessionStorage.setItem(
      "sardonyx.session",
      JSON.stringify({ user: "ada", token: TOKEN }),
    );
  }
  const state = { categories: [...categories] };
  const sent = fakeSite({
    "GET /info": {
      body: { ...INFO, modules, config: { ...INFO.config, privileges: PRIVILEGES } },
    },
    "GET /user/ada": { body: { name: "ada", rank } },
    "GET /tag-categories": () => ({ body: { results: state.categories } }),
    "POST /tag-categories": (one: Sent) => {
      const created = { ...(one.body as object), usages: 0, default: false };
      state.categories.push(created as never);
      return { body: created };
    },
    "GET /tags": {
      body: {
        total: 120,
        results: [
          tag("coastal", "default", 120),
          tag("mira_vell", "character", 3),
          tag("a:b", "default", 1),
        ],
      },
    },
  } as never);
  return { sent, state };
}

const asked = (sent: Sent[]) =>
  sent
    .filter((one) => one.method === "GET" && one.path.startsWith("/tags?"))
    .map((one) => Object.fromEntries(new URLSearchParams(one.path.split("?")[1])));

describe("the tags page", () => {
  it("lists the tags with their category and usages, the most used first", async () => {
    const { sent } = site();
    renderApp("/tags");
    const table = await screen.findByRole("table");
    const rows = within(table).getAllByRole("row").slice(1);
    expect(rows.map((row) => row.textContent)).toEqual([
      "coastaldefault120",
      "mira_vellcharacter3",
      "a:bdefault1",
    ]);
    // a tag leads to its posts, escaped as a query
    expect(
      within(rows[2] as HTMLElement).getByRole("link", { name: "a:b" }),
    ).toHaveAttribute("href", "/posts?q=a%5C%3Ab");
    expect(screen.getByText("120 tags")).toBeInTheDocument();
    expect(asked(sent).at(-1)).toMatchObject({
      query: "sort:usages",
      offset: "0",
      limit: "50",
      fields: "names,category,usages",
    });
  });

  it("filters by category, in the categories' order and colours", async () => {
    const { sent } = site();
    renderApp("/tags?q=mira*");
    const filter = await screen.findByRole("navigation", { name: "Categories" });
    await waitFor(() =>
      expect(
        within(filter)
          .getAllByRole("link")
          .map((link) => link.textContent),
      ).toEqual(["All", "default", "character", "meta"]),
    );
    const character = within(filter).getByRole("link", { name: "character" });
    expect(character.querySelector("[data-color]")).toHaveAttribute(
      "data-color",
      "#aa3366",
    );
    await userEvent.setup().click(character);
    await waitFor(() =>
      expect(asked(sent).at(-1)?.query).toBe("mira* category:character sort:usages"),
    );
    expect(within(filter).getByRole("link", { name: "character" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("searches with the engine's query, and keeps a sort the query names", async () => {
    const { sent } = site();
    renderApp("/tags");
    const user = userEvent.setup();
    const field = await screen.findByRole("combobox", { name: "Search tags" });
    await user.type(field, "usages:10.. sort:name");
    await user.click(screen.getByRole("button", { name: "Search" }));
    await waitFor(() =>
      expect(asked(sent).at(-1)?.query).toBe("usages:10.. sort:name"),
    );
  });

  it("pages as the library does", async () => {
    const { sent } = site();
    renderApp("/tags?at=50");
    const pages = await screen.findByRole("navigation", { name: "Pages" });
    expect(within(pages).getByRole("link", { name: "Page 2" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(within(pages).getByRole("link", { name: "Page 3" })).toHaveAttribute(
      "href",
      "/tags?at=100",
    );
    expect(asked(sent).at(-1)?.offset).toBe("50");
  });

  it("is not offered to who may not list tags, and says why", async () => {
    site({ rank: null });
    renderApp("/tags");
    expect(
      await screen.findByText(/The list of tags is for members/),
    ).toBeInTheDocument();
    const banner = screen.getByRole("banner");
    await within(banner).findByRole("link", { name: "Library" });
    expect(within(banner).queryByRole("link", { name: "Tags" })).toBeNull();
  });

  it("is in the header for who may", async () => {
    site();
    renderApp("/");
    const banner = await screen.findByRole("banner");
    expect(await within(banner).findByRole("link", { name: "Tags" })).toHaveAttribute(
      "href",
      "/tags",
    );
  });
});

describe("the creator category", () => {
  const offer = () => screen.queryByRole("region", { name: "The creator category" });

  it("is offered to who may create it, made on request, then no longer offered", async () => {
    const { sent } = site({ rank: "moderator" });
    renderApp("/tags");
    const section = await screen.findByRole("region", { name: "The creator category" });
    expect(section).toHaveTextContent("The cards module files each card's creator");
    await userEvent
      .setup()
      .click(
        within(section).getByRole("button", { name: "Create the creator category" }),
      );
    await waitFor(() => expect(offer()).toBeNull());
    const created = sent.find(
      (one) => one.method === "POST" && one.path === "/tag-categories",
    );
    expect(created?.body).toEqual({ name: "creator", color: CREATOR_COLOR, order: 4 });
    // the new category is among the filters
    const filter = screen.getByRole("navigation", { name: "Categories" });
    expect(
      await within(filter).findByRole("link", { name: "creator" }),
    ).toBeInTheDocument();
  });

  it("is hidden from who may not create categories", async () => {
    site({ rank: "regular" });
    renderApp("/tags");
    await screen.findByRole("table");
    expect(offer()).toBeNull();
  });

  it("is hidden once the category exists, whatever its case", async () => {
    site({
      rank: "moderator",
      categories: [
        ...CATEGORIES,
        { ...CATEGORIES[0], name: "Creator", order: 4 } as never,
      ],
    });
    renderApp("/tags");
    await screen.findByRole("link", { name: "Creator" });
    expect(offer()).toBeNull();
  });

  it("is hidden on a site without cards", async () => {
    site({ rank: "moderator", modules: [] });
    renderApp("/tags");
    await screen.findByRole("table");
    expect(offer()).toBeNull();
  });
});

describe("the query of the tags page", () => {
  it("adds the category as its own token, escaped, and the most used first", () => {
    expect(tagQuery("", undefined)).toBe("sort:usages");
    expect(tagQuery(" fan* ", "a:b")).toBe("fan* category:a\\:b sort:usages");
    expect(tagQuery("-sort:name x", undefined)).toBe("-sort:name x");
  });
});
