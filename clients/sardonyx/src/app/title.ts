import { useEffect } from "react";

const APP = "Sardonyx";

/** The browser tab's title while a page is shown: "<what> · Sardonyx". */
export function useDocumentTitle(what: string | null): void {
  useEffect(() => {
    document.title = what ? `${what} · ${APP}` : APP;
    return () => {
      document.title = APP;
    };
  }, [what]);
}
