/**
 * What went wrong with a request, as the API says it: every error the API
 * returns has a `name` (for programs), a `title` and a `description` (for
 * people). A request that did not reach the API at all becomes one too, so
 * that the app shows every failure the same way.
 */
export class ApiError extends Error {
  constructor(
    readonly name: string,
    readonly title: string,
    readonly description: string,
    /** the HTTP status; 0 when the site could not be reached */
    readonly status: number,
  ) {
    super(description);
  }
}

interface ErrorBody {
  name?: unknown;
  title?: unknown;
  description?: unknown;
}

function text(value: unknown): string | undefined {
  return typeof value === "string" && value ? value : undefined;
}

/** The ApiError of a failed response and the body openapi-fetch made of it. */
export function apiError(body: unknown, response: Response): ApiError {
  const fields = (typeof body === "object" && body ? body : {}) as ErrorBody;
  return new ApiError(
    text(fields.name) ?? "HttpError",
    text(fields.title) ?? response.statusText ?? "Error",
    text(fields.description) ?? `The site answered with status ${response.status}.`,
    response.status,
  );
}

/** For a request that never got an answer: the site is down, or the network. */
export function unreachable(cause: unknown): ApiError {
  return new ApiError(
    "NetworkError",
    "The site cannot be reached",
    cause instanceof Error ? cause.message : String(cause),
    0,
  );
}

/**
 * The data of a successful request, or the request's ApiError thrown: for
 * code that wants the result or an exception, as TanStack Query does.
 */
export async function unwrap<T>(
  request: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  let result: Awaited<typeof request>;
  try {
    result = await request;
  } catch (cause) {
    throw unreachable(cause);
  }
  if (result.error !== undefined || !result.response.ok) {
    throw apiError(result.error, result.response);
  }
  return result.data as T;
}

/** Any error as an ApiError, for showing it. */
export function asApiError(error: unknown): ApiError {
  if (error instanceof ApiError) {
    return error;
  }
  return new ApiError(
    "Error",
    "Something went wrong",
    error instanceof Error ? error.message : String(error),
    0,
  );
}
