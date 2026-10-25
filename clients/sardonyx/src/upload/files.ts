/**
 * What the client can tell of a file before sending it, from what the
 * site says it takes (GET /info: `maxUploadSize`, `acceptedTypes`). Those
 * are hints: the server decides by the file's content. So a file is
 * refused here only when it surely would be there: it is too large, or
 * its extension is a well-known one of a type the site does not take. A
 * file the client cannot place (no extension, or one it does not know) is
 * sent, and the server answers.
 */
import type { components } from "@/api/schema";

export type AcceptedType = components["schemas"]["AcceptedType"];

// extensions whose type is clear, that a site might not take; one the site
// lists is never refused (a module may take any of them)
const WELL_KNOWN = new Set([
  "7z",
  "aac",
  "avi",
  "charx",
  "csv",
  "doc",
  "docx",
  "dmg",
  "epub",
  "exe",
  "flac",
  "flv",
  "gz",
  "htm",
  "html",
  "iso",
  "jpg",
  "jpeg",
  "json",
  "jxl",
  "m4a",
  "md",
  "mkv",
  "mp3",
  "ogg",
  "pdf",
  "png",
  "ppt",
  "pptx",
  "psd",
  "rar",
  "rtf",
  "svg",
  "tar",
  "tif",
  "tiff",
  "txt",
  "wav",
  "webm",
  "wmv",
  "xls",
  "xlsx",
  "yaml",
  "zip",
]);

export function extensionOf(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot > 0 ? name.slice(dot + 1).toLowerCase() : "";
}

const UNITS = ["bytes", "KB", "MB", "GB", "TB"];

export function formatBytes(bytes: number): string {
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < UNITS.length - 1) {
    value /= 1024;
    unit++;
  }
  return unit === 0
    ? `${bytes} bytes`
    : `${value.toFixed(value < 10 ? 1 : 0)} ${UNITS[unit]}`;
}

/** Why the site would surely refuse the file, or null: then it is sent. */
export function refusal(
  file: Pick<File, "name" | "size" | "type">,
  maxUploadSize: number | null | undefined,
  acceptedTypes: readonly AcceptedType[] | undefined,
): string | null {
  if (typeof maxUploadSize === "number" && file.size > maxUploadSize) {
    return `It is larger than this site takes (${formatBytes(maxUploadSize)}).`;
  }
  if (!acceptedTypes) {
    return null;
  }
  const extension = extensionOf(file.name);
  const listed = acceptedTypes.some(
    (type) =>
      (extension && type.extensions?.includes(extension)) ||
      (file.type && type.mime?.includes(file.type)),
  );
  if (!listed && WELL_KNOWN.has(extension)) {
    return `This site does not take .${extension} files.`;
  }
  return null;
}
