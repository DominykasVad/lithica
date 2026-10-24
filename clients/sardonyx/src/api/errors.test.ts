import { describe, expect, it } from "vitest";
import { ApiError, asApiError, unwrap } from "./errors";

const response = (status: number, statusText = "") =>
  new Response(null, { status, statusText });

describe("unwrap", () => {
  it("gives the data of a success", async () => {
    await expect(
      unwrap(Promise.resolve({ data: { a: 1 }, response: response(200) })),
    ).resolves.toEqual({
      a: 1,
    });
  });

  it("throws the API's error, with its title, description and status", async () => {
    const failed = unwrap(
      Promise.resolve({
        error: {
          name: "TagNotFoundError",
          title: "Not found",
          description: "Tag 'x' not found.",
        },
        response: response(404),
      }),
    );
    await expect(failed).rejects.toMatchObject({
      name: "TagNotFoundError",
      title: "Not found",
      description: "Tag 'x' not found.",
      status: 404,
    });
    await expect(failed).rejects.toBeInstanceOf(ApiError);
  });

  it("makes a readable error of an answer that is not the API's", async () => {
    await expect(
      unwrap(
        Promise.resolve({
          error: "<html>Bad Gateway</html>",
          response: response(502, "Bad Gateway"),
        }),
      ),
    ).rejects.toMatchObject({
      title: "Bad Gateway",
      description: "The site answered with status 502.",
      status: 502,
    });
  });

  it("says when the site cannot be reached at all", async () => {
    await expect(
      unwrap(Promise.reject(new TypeError("Failed to fetch"))),
    ).rejects.toMatchObject({
      name: "NetworkError",
      title: "The site cannot be reached",
      description: "Failed to fetch",
      status: 0,
    });
  });
});

describe("asApiError", () => {
  it("keeps an ApiError and wraps anything else", () => {
    const error = new ApiError("X", "T", "D", 400);
    expect(asApiError(error)).toBe(error);
    expect(asApiError(new Error("boom"))).toMatchObject({
      title: "Something went wrong",
      description: "boom",
    });
  });
});
