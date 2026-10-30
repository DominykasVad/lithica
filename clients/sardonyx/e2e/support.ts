/**
 * What the browser tests share: where the e2e stack is, its accounts, and
 * requests to its API and its mail catcher made without a browser.
 */
import { execFileSync } from "node:child_process";
import path from "node:path";
import { type APIRequestContext, expect, type Page } from "@playwright/test";

export const SITE = process.env.E2E_URL ?? "http://localhost:8092";
export const NSFW_SITE = process.env.E2E_NSFW_URL ?? "http://localhost:8093";
export const MAIL = process.env.E2E_MAIL_URL ?? "http://localhost:8095";

/** The tag of the posts made for auto load to page through. */
export const BULK_TAG = "e2e_bulk";
// more than a batch of auto load (100): it pages
export const BULK_COUNT = 160;
/** The card with a large lorebook, made by the setup. */
export const LARGE_LOREBOOK = "Archive of Tides";
export const LARGE_ENTRIES = 2500;

/** The first account of the site, so its administrator. */
export const ADMIN = { name: "e2e_admin", password: "e2e-admin-pass" };

const STACK = path.join(import.meta.dirname, "stack.sh");

/** A docker compose command on the e2e stack, its output. */
export function compose(...args: string[]): string {
  return execFileSync(STACK, ["compose", ...args], {
    encoding: "utf8",
    stdio: ["ignore", "pipe", "pipe"],
    maxBuffer: 64 * 1024 * 1024,
  });
}

const basic = (name: string, password: string) =>
  `Basic ${Buffer.from(`${name}:${password}`).toString("base64")}`;

/** A request to the API as this user (or as nobody), its JSON. */
export async function api(
  request: APIRequestContext,
  method: string,
  route: string,
  options: {
    user?: { name: string; password: string };
    data?: unknown;
    multipart?: Record<
      string,
      string | { name: string; mimeType: string; buffer: Buffer }
    >;
    site?: string;
  } = {},
): Promise<{ status: number; body: Record<string, unknown> }> {
  const response = await request.fetch(`${options.site ?? SITE}/api${route}`, {
    method,
    headers: {
      Accept: "application/json",
      ...(options.user
        ? { Authorization: basic(options.user.name, options.user.password) }
        : {}),
    },
    data: options.data,
    multipart: options.multipart,
  });
  const text = await response.text();
  return { status: response.status(), body: text ? JSON.parse(text) : {} };
}

/** An account made through the API, unless it is there already. */
export async function ensureUser(
  request: APIRequestContext,
  user: { name: string; password: string; email?: string },
): Promise<void> {
  const made = await api(request, "POST", "/users", {
    data: { name: user.name, password: user.password, email: user.email },
  });
  if (made.status !== 200 && made.body.name !== "UserAlreadyExistsError") {
    throw new Error(`could not make ${user.name}: ${JSON.stringify(made.body)}`);
  }
}

/** Upload a file as a post, as the administrator; its post. */
export async function upload(
  request: APIRequestContext,
  name: string,
  buffer: Buffer,
  tags: string[] = [],
): Promise<Record<string, unknown>> {
  const made = await api(request, "POST", "/posts", {
    user: ADMIN,
    multipart: {
      metadata: JSON.stringify({ safety: "safe", tags }),
      content: { name, mimeType: "application/octet-stream", buffer },
    },
  });
  if (made.status !== 200) {
    throw new Error(`could not upload ${name}: ${JSON.stringify(made.body)}`);
  }
  return made.body;
}

/** The id of the post a search finds first. */
export async function postId(
  request: APIRequestContext,
  query: string,
): Promise<number> {
  const found = await api(
    request,
    "GET",
    `/posts?query=${encodeURIComponent(query)}&limit=1&fields=id`,
    { user: ADMIN },
  );
  const id = (found.body.results as { id: number }[] | undefined)?.[0]?.id;
  if (!id) {
    throw new Error(`no post for ${query}`);
  }
  return id;
}

/** Log in through the login form. */
export async function logIn(
  page: Page,
  user: { name: string; password: string } = ADMIN,
): Promise<void> {
  await page.goto("/login");
  await page.getByLabel("User name").fill(user.name);
  await page.getByLabel("Password").fill(user.password);
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(
    page.getByRole("banner").getByRole("button", { name: user.name }),
  ).toBeVisible();
}

/** Whether the page scrolls sideways. */
export function scrollsSideways(page: Page): Promise<boolean> {
  return page.evaluate(
    () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
  );
}

/** The id of the post of the card with this name. */
export async function cardPost(
  request: APIRequestContext,
  name: string,
): Promise<number> {
  const found = await api(
    request,
    "GET",
    `/posts?query=${encodeURIComponent("card-spec:v1,v2,v3")}&limit=100&fields=id,card`,
    { user: ADMIN },
  );
  const results = found.body.results as { id: number; card?: { name?: string } }[];
  const post = results.find((one) => one.card?.name === name);
  if (!post) {
    throw new Error(`no card named ${name}`);
  }
  return post.id;
}
