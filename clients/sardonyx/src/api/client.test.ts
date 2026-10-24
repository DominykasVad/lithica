import { afterEach, describe, expect, it, vi } from "vitest";
import { authorization, createApiClient, setCredentials } from "./client";

function answering(body: unknown, status = 200) {
  return vi.spyOn(globalThis, "fetch").mockResolvedValue(
    new Response(JSON.stringify(body), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
}

function sent(fetch: ReturnType<typeof answering>): Request {
  const request = fetch.mock.calls[0]?.[0];
  if (!(request instanceof Request)) {
    throw new Error("no request was sent");
  }
  return request;
}

afterEach(() => setCredentials(null));

describe("the API client", () => {
  it("asks the API beside the app, and says it accepts JSON", async () => {
    const fetch = answering({ postCount: 0 });
    const { data } = await createApiClient("http://site.test/api").GET("/info");
    expect(data).toEqual({ postCount: 0 });
    const request = sent(fetch);
    expect(request.url).toBe("http://site.test/api/info");
    expect(request.headers.get("Accept")).toBe("application/json");
  });

  it("sends no credentials while nobody is logged in", async () => {
    const fetch = answering({});
    await createApiClient("http://site.test/api").GET("/info");
    expect(sent(fetch).headers.has("Authorization")).toBe(false);
  });

  it("sends the token of the user who is logged in", async () => {
    setCredentials({ user: "ada", token: "abc-123" });
    const fetch = answering({});
    await createApiClient("http://site.test/api").GET("/info");
    expect(sent(fetch).headers.get("Authorization")).toBe(
      `Token ${btoa("ada:abc-123")}`,
    );
  });

  it("gives the API's error body for a refused request", async () => {
    answering(
      {
        name: "PostNotFoundError",
        title: "Not found",
        description: "Post 9 not found.",
      },
      404,
    );
    const { data, error, response } = await createApiClient("http://site.test/api").GET(
      "/post/{post_id}",
      { params: { path: { post_id: "9" } } },
    );
    expect(data).toBeUndefined();
    expect(response.status).toBe(404);
    expect(error?.description).toBe("Post 9 not found.");
  });
});

describe("authorization", () => {
  it("is the base64 of user:token", () => {
    expect(authorization({ user: "ada", token: "t" })).toBe(`Token ${btoa("ada:t")}`);
  });

  it("encodes a name that is not Latin-1 as UTF-8", () => {
    // btoa alone would throw on these
    const header = authorization({ user: "アダ", token: "t" });
    const decoded = new TextDecoder().decode(
      Uint8Array.from(atob(header.slice("Token ".length)), (c) => c.charCodeAt(0)),
    );
    expect(decoded).toBe("アダ:t");
  });
});
