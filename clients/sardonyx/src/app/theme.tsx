import { createContext, type ReactNode, useContext, useEffect, useState } from "react";

export type Theme = "light" | "dark" | "dracula" | "system";

const STORAGE_KEY = "sardonyx.theme";

function storedTheme(): Theme {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "light" || stored === "dark" || stored === "dracula") {
      return stored;
    }
  } catch {
    // storage may be blocked
  }
  return "system";
}

function systemIsDark(): boolean {
  return (
    typeof matchMedia === "function" &&
    matchMedia("(prefers-color-scheme: dark)").matches
  );
}

const ThemeContext = createContext<{
  theme: Theme;
  setTheme(theme: Theme): void;
} | null>(null);

/**
 * Light, dark, Dracula, or as the system is. The choice is this browser's, kept in
 * localStorage; public/theme.js applies it before the page is drawn.
 */
export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setThemeState] = useState<Theme>(storedTheme);

  useEffect(() => {
    // Dracula is a dark theme: drawn as dark, in its own colours
    const apply = () => {
      document.documentElement.classList.toggle(
        "dark",
        theme === "dark" ||
          theme === "dracula" ||
          (theme === "system" && systemIsDark()),
      );
      document.documentElement.classList.toggle("dracula", theme === "dracula");
    };
    apply();
    if (theme !== "system" || typeof matchMedia !== "function") {
      return;
    }
    const media = matchMedia("(prefers-color-scheme: dark)");
    media.addEventListener("change", apply);
    return () => media.removeEventListener("change", apply);
  }, [theme]);

  const setTheme = (next: Theme) => {
    setThemeState(next);
    try {
      if (next === "system") {
        localStorage.removeItem(STORAGE_KEY);
      } else {
        localStorage.setItem(STORAGE_KEY, next);
      }
    } catch {
      // not kept; it lasts as long as the tab
    }
  };
  return (
    <ThemeContext.Provider value={{ theme, setTheme }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  const context = useContext(ThemeContext);
  if (!context) {
    throw new Error("useTheme outside of ThemeProvider");
  }
  return context;
}
