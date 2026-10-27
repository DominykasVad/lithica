/**
 * Sending one file the way the API offers (doc/API.md, file uploads): the
 * file to temporary storage (POST /uploads), then a post made from its
 * token (POST /posts). The first step goes by XMLHttpRequest, the one way
 * a browser reports how much of a request body has been sent.
 */
import { API_BASE_URL, api, authorization, getCredentials } from "@/api/client";
import { ApiError, apiError, unreachable } from "@/api/errors";
import type { components } from "@/api/schema";

export type Post = components["schemas"]["Post"];

export type Outcome =
  | { kind: "created"; post: Post }
  /** the site has this file already, as that post */
  | { kind: "duplicate"; postId: number }
  /** the site said no: its reason, e.g. a type it does not take */
  | { kind: "refused"; error: ApiError }
  /** no answer that settles it: the network, or the site failing; worth a retry */
  | { kind: "failed"; error: ApiError }
  | { kind: "cancelled" };

export interface Batch {
  safety: "safe" | "sketchy" | "unsafe";
  tags: string[];
}

const DUPLICATE = "PostAlreadyUploadedError";
// what the post of a file is asked with: enough for its result line; `card`
// only where the site has cards, which refuses a field it does not know
const CREATED_FIELDS = "id,type,thumbnailUrl";

/** A failure the site answered with is a refusal; one of the site's own (5xx) is not. */
function answered(error: ApiError): Outcome {
  return error.status >= 400 && error.status < 500
    ? { kind: "refused", error }
    : { kind: "failed", error };
}

function body(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

/** POST /uploads: the file put up for a while; its token, or how it ended. */
function putUp(
  file: File,
  onProgress: (sent: number) => void,
  signal: AbortSignal,
): Promise<{ token: string } | Outcome> {
  // cancelled before it went: nothing is sent
  if (signal.aborted) {
    return Promise.resolve({ kind: "cancelled" });
  }
  return new Promise((resolve) => {
    const request = new XMLHttpRequest();
    request.open("POST", `${API_BASE_URL}/uploads`);
    request.setRequestHeader("Accept", "application/json");
    const credentials = getCredentials();
    if (credentials) {
      request.setRequestHeader("Authorization", authorization(credentials));
    }
    request.upload.onprogress = (event) => {
      if (event.lengthComputable && event.total > 0) {
        onProgress(event.loaded / event.total);
      }
    };
    request.onload = () => {
      const data = body(request.responseText);
      if (request.status >= 200 && request.status < 300) {
        const token =
          typeof data === "object" && data && "token" in data ? data.token : null;
        resolve(
          typeof token === "string"
            ? { token }
            : {
                kind: "failed",
                error: new ApiError(
                  "HttpError",
                  "Unexpected answer",
                  "The site took the file but gave no token for it.",
                  request.status,
                ),
              },
        );
        return;
      }
      resolve(
        answered(
          apiError(
            data,
            new Response(null, {
              status: request.status,
              statusText: request.statusText,
            }),
          ),
        ),
      );
    };
    request.onerror = () =>
      resolve({
        kind: "failed",
        error: unreachable(new Error("The upload did not get through.")),
      });
    request.onabort = () => resolve({ kind: "cancelled" });
    signal.addEventListener("abort", () => request.abort(), { once: true });
    const form = new FormData();
    form.append("content", file, file.name);
    request.send(form);
  });
}

/**
 * Sends the file and makes its post; resolves to how it ended, never
 * throws. `signal` cancels the sending only: once the post is being made
 * (`onCreating`), it is let finish, and its outcome is the site's. `onProgress` gets the share of the file sent, 0 to 1; `onCreating`
 * says when the post is being made. `cards`: the site has the cards module.
 */
export async function send(
  file: File,
  batch: Batch,
  {
    signal,
    cards,
    onProgress,
    onCreating,
  }: {
    signal: AbortSignal;
    cards: boolean;
    onProgress(sent: number): void;
    onCreating(): void;
  },
): Promise<Outcome> {
  const upload = await putUp(file, onProgress, signal);
  if (!("token" in upload)) {
    return upload;
  }
  if (signal.aborted) {
    return { kind: "cancelled" };
  }
  onCreating();
  try {
    const { data, error, response } = await api.POST("/posts", {
      params: { query: { fields: cards ? `${CREATED_FIELDS},card` : CREATED_FIELDS } },
      body: { safety: batch.safety, tags: batch.tags, contentToken: upload.token },
      // never aborted: a post the site has begun to make may be made all the
      // same, and only its answer says
    });
    if (data && response.ok) {
      return { kind: "created", post: data };
    }
    const failure = error as Record<string, unknown> | undefined;
    if (failure?.name === DUPLICATE && typeof failure.otherPostId === "number") {
      return { kind: "duplicate", postId: failure.otherPostId };
    }
    return answered(apiError(error, response));
  } catch (cause) {
    return { kind: "failed", error: unreachable(cause) };
  }
}
