import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { DELETE_PRIVILEGE, EDIT_PRIVILEGES } from "@/post/edit";
import { CREATE_CATEGORY_PRIVILEGE, LIST_PRIVILEGE } from "@/tags/TagsPage";
import { UPLOAD_PRIVILEGES } from "./privileges";

// the privileges a site has: the server's configuration, all of them
const config = readFileSync(
  path.join(import.meta.dirname, "../../../../server/config.yaml.dist"),
  "utf8",
);

/** A privilege's name as GET /info gives it (util.snake_case_to_lower_camel_case). */
function asInfoNamesIt(name: string): string {
  const [first = "", ...rest] = name.split("_");
  return (
    first.toLowerCase() +
    rest
      .map((word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
      .join("")
  );
}

describe("the privileges the app asks about", () => {
  it("are named as GET /info names the site's privileges", () => {
    const known = [...config.matchAll(/^\s+'([a-z_:-]+)':\s+\w+\s*$/gm)].map((match) =>
      asInfoNamesIt(match[1] ?? ""),
    );
    expect(known.length).toBeGreaterThan(50);
    const used = [
      ...UPLOAD_PRIVILEGES,
      ...Object.values(EDIT_PRIVILEGES),
      DELETE_PRIVILEGE,
      LIST_PRIVILEGE,
      CREATE_CATEGORY_PRIVILEGE,
      "tags:create",
    ];
    expect(used.filter((name) => !known.includes(name))).toEqual([]);
  });

  it("are converted as the server converts them", () => {
    expect(asInfoNamesIt("tag_categories:create")).toBe("tagCategories:create");
    expect(asInfoNamesIt("tag_categories:set_default")).toBe(
      "tagCategories:setDefault",
    );
    expect(asInfoNamesIt("posts:edit:tags")).toBe("posts:edit:tags");
  });
});
