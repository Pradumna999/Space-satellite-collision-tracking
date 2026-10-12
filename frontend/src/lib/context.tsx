import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError, setCsrf } from "../api/client";
import type { Me } from "../api/types";
import { applyTheme, loadTheme, saveTheme, type ThemeSettings } from "../theme/theme";

interface AuthCtx { me: Me | null; loading: boolean; login: (email: string, password: string) => Promise<void>; logout: () => Promise<void> }
const Auth = createContext<AuthCtx | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["me"],
    queryFn: async () => {
      try {
        const me = await api.get<Me>("/auth/me");
        setCsrf(me.csrf_token);
        return me;
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null;
        throw e;
      }
    },
    staleTime: 60_000,
  });
  const login = useCallback(async (email: string, password: string) => {
    const r = await api.post<Me>("/auth/login", { email, password });
    setCsrf(r.csrf_token);
    qc.setQueryData(["me"], r);
  }, [qc]);
  const logout = useCallback(async () => {
    await api.post("/auth/logout").catch(() => undefined);
    setCsrf(null);
    qc.clear();
    qc.setQueryData(["me"], null);
  }, [qc]);
  const value = useMemo(() => ({ me: q.data ?? null, loading: q.isLoading, login, logout }), [q.data, q.isLoading, login, logout]);
  return <Auth.Provider value={value}>{children}</Auth.Provider>;
}

export function useAuth(): AuthCtx {
  const c = useContext(Auth);
  if (!c) throw new Error("AuthProvider missing");
  return c;
}

interface ThemeCtx { theme: ThemeSettings; setTheme: (t: ThemeSettings) => void }
const Theme = createContext<ThemeCtx | null>(null);

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, set] = useState<ThemeSettings>(loadTheme);
  useEffect(() => { applyTheme(theme); saveTheme(theme); }, [theme]);
  return <Theme.Provider value={{ theme, setTheme: set }}>{children}</Theme.Provider>;
}

export function useTheme(): ThemeCtx {
  const c = useContext(Theme);
  if (!c) throw new Error("ThemeProvider missing");
  return c;
}
