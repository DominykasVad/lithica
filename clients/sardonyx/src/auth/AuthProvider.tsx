import { useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import { type Credentials, onSessionEnded } from "@/api/client";
import { forgetSession, logIn, logOut, restoreSession } from "./session";

interface Auth {
  /** the user who is logged in, or null */
  user: string | null;
  logIn(user: string, password: string, remember: boolean): Promise<void>;
  /** resolves to the site's error if it could not be told, else null */
  logOut(): Promise<unknown>;
  /** set when the site refused the token the app had: shown once */
  ended: boolean;
}

const AuthContext = createContext<Auth | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  // restored once, before the first request goes out
  const [session, setSession] = useState<Credentials | null>(() => restoreSession());
  const [ended, setEnded] = useState(false);

  // What a user may see depends on who they are: nothing asked as someone
  // else is kept, and what is on the page is asked for again.
  const changeUser = useCallback(
    (next: Credentials | null) => {
      setSession(next);
      void queryClient.resetQueries();
    },
    [queryClient],
  );

  useEffect(() => {
    onSessionEnded(() => {
      forgetSession();
      setEnded(true);
      changeUser(null);
    });
  }, [changeUser]);

  const value: Auth = {
    user: session?.user ?? null,
    ended,
    async logIn(user, password, remember) {
      const credentials = await logIn(user, password, remember);
      setEnded(false);
      changeUser(credentials);
    },
    async logOut() {
      if (!session) {
        return null;
      }
      const error = await logOut(session);
      changeUser(null);
      return error;
    },
  };
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): Auth {
  const auth = useContext(AuthContext);
  if (!auth) {
    throw new Error("useAuth outside of AuthProvider");
  }
  return auth;
}
