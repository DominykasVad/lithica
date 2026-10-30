/**
 * Once, before the browsers: the accounts, the import of the sample cards
 * (the first step of the phase-5 exit check), a card with a large lorebook
 * and enough posts for auto load to page. Safe to run again on the same
 * stack: what is there already is left as it is.
 */
import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import { expect, test as setup } from "@playwright/test";
import { picture, pngCard, v3Card } from "./cards.ts";
import {
  ADMIN,
  api,
  BULK_COUNT,
  BULK_TAG,
  compose,
  ensureUser,
  LARGE_ENTRIES,
  LARGE_LOREBOOK,
} from "./support.ts";

setup("the administrator's account", async ({ request }) => {
  await ensureUser(request, ADMIN);
  const user = await api(request, "GET", `/user/${ADMIN.name}`, { user: ADMIN });
  // the first account of a site is its administrator
  expect(user.body.rank).toBe("administrator");
  // where the cards module files creators, as the site's administrator
  // makes it (INSTALL.md); there already on a second run
  await api(request, "POST", "/tag-categories", {
    user: ADMIN,
    data: { name: "creator", color: "#8a5a12" },
  });
});

/** An admin command in the server's container (`lithica-admin`), its output. */
function admin(...args: string[]): string {
  return compose("exec", "-T", "server", "./lithica-admin", ...args);
}

setup("phase 5 exit check: import the sample cards", async ({ request }) => {
  const output = admin(
    "import",
    "/e2e-fixtures/cards",
    "--user",
    ADMIN.name,
    "--safety",
    "safe",
  );
  // six files, each a post now or one already (a run before this one)
  expect(output).toMatch(
    /import: 6 files: \d+ created, \d+ skipped, 0 refused, 0 failed/,
  );
  for (const [query, total] of [
    ["card-spec:v2", 3],
    ["card-spec:v3", 2],
    ["card-format:charx", 1],
    ["-card-spec:v1,v2,v3 -e2e_bulk", undefined],
  ] as const) {
    const found = await api(
      request,
      "GET",
      `/posts?query=${encodeURIComponent(query)}&limit=1&fields=id`,
      { user: ADMIN },
    );
    if (total !== undefined) {
      expect(found.body.total, query).toBeGreaterThanOrEqual(total);
    }
  }
});

/** Upload, or find it is there already: the same file is a post once. */
async function uploadOnce(
  request: Parameters<typeof api>[0],
  name: string,
  buffer: Buffer,
  tags: string[],
): Promise<void> {
  const made = await api(request, "POST", "/posts", {
    user: ADMIN,
    multipart: {
      metadata: JSON.stringify({ safety: "safe", tags }),
      content: { name, mimeType: "application/octet-stream", buffer },
    },
  });
  if (made.status !== 200 && made.body.name !== "PostAlreadyUploadedError") {
    throw new Error(`could not upload ${name}: ${JSON.stringify(made.body)}`);
  }
}

setup("a card with a large lorebook", async ({ request }) => {
  setup.setTimeout(120_000);
  // made here, not committed: megabytes of JSON
  const card = v3Card({
    name: LARGE_LOREBOOK,
    creator: "e2e_maker",
    entries: LARGE_ENTRIES,
  });
  await uploadOnce(request, "archive-of-tides.png", pngCard(card, 7), []);
});

setup("posts for auto load to page through", async ({ request }) => {
  setup.setTimeout(300_000);
  const found = await api(
    request,
    "GET",
    `/posts?query=${BULK_TAG}&limit=1&fields=id`,
    {
      user: ADMIN,
    },
  );
  if (Number(found.body.total ?? 0) >= BULK_COUNT) {
    return;
  }
  // through the import: twice as fast as uploading them one by one
  const folder = path.join(import.meta.dirname, ".stack", "bulk");
  mkdirSync(folder, { recursive: true });
  for (let i = 0; i < BULK_COUNT; i++) {
    writeFileSync(
      path.join(folder, `bulk-${String(i).padStart(3, "0")}.png`),
      picture(1000 + i, 32, 32),
    );
  }
  const output = admin(
    "import",
    "/e2e-stack/bulk",
    "--user",
    ADMIN.name,
    "--safety",
    "safe",
    "--tags",
    BULK_TAG,
  );
  expect(output).toMatch(
    new RegExp(`import: ${BULK_COUNT} files: .* 0 refused, 0 failed`),
  );
});
