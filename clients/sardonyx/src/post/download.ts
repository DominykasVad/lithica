/**
 * Downloading a post's file: fetched with the session's token when it is
 * on this site (a site may show posts only to users), saved under the name
 * the site gives it.
 */
import { authorization, getCredentials } from "@/api/client";
import { apiError, unreachable } from "@/api/errors";

/**
 * The file name of a `Content-Disposition` header: `filename*` (RFC 6266,
 * for a name that is not ASCII) before `filename`; null without one.
 */
export function fileNameOf(disposition: string | null): string | null {
  if (!disposition) {
    return null;
  }
  const extended = disposition.match(/filename\*\s*=\s*([^']*)'[^']*'([^;]+)/i);
  if (extended?.[2]) {
    try {
      return clean(decodeURIComponent(extended[2].trim()));
    } catch {
      // not percent-encoded right: the plain name, if there is one
    }
  }
  const plain = disposition.match(/filename\s*=\s*(?:"((?:[^"\\]|\\.)*)"|([^;]+))/i);
  const name = plain?.[1]?.replace(/\\(.)/g, "$1") ?? plain?.[2]?.trim();
  return name ? clean(name) : null;
}

// a name, not a path: the browser would take care of it too
function clean(name: string): string | null {
  const base = name.split(/[/\\]/).pop()?.trim() ?? "";
  return base && base !== "." && base !== ".." ? base : null;
}

/** `<post id>.<extension of its file>`: the name when the site gives none. */
export function fallbackName(id: number, contentUrl: string | undefined): string {
  const extension = contentUrl?.match(/\.([a-z0-9]+)(?:[?#]|$)/i)?.[1];
  return extension ? `${id}.${extension}` : String(id);
}

// how long a saved file's blob URL is kept: the browser reads the blob after
// the click, in its own time, and a large file may take a while
export const BLOB_URL_LIFETIME = 60_000;

/** Whether `url` is on the page's own origin, the one the session is for. */
export function isOwnSite(url: string): boolean {
  try {
    return new URL(url, window.location.href).origin === window.location.origin;
  } catch {
    return false;
  }
}

/**
 * Fetches the file at `url` and has the browser save it. The token goes
 * only to this site: a file elsewhere (a site may serve its files from
 * another host) is asked for without it.
 */
export async function download(url: string, fallback: string): Promise<void> {
  const credentials = isOwnSite(url) ? getCredentials() : null;
  let response: Response;
  try {
    response = await fetch(
      new Request(new URL(url, window.location.href), {
        headers: credentials ? { Authorization: authorization(credentials) } : {},
      }),
    );
  } catch (cause) {
    throw unreachable(cause);
  }
  if (!response.ok) {
    // the API's errors are JSON, even on this route
    const body: unknown = await response.json().catch(() => null);
    throw apiError(body, response);
  }
  const blob = await response.blob();
  const name = fileNameOf(response.headers.get("Content-Disposition")) ?? fallback;
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(link.href), BLOB_URL_LIFETIME);
}
