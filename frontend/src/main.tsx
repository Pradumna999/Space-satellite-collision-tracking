import React, { Suspense, lazy } from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "@fontsource/fjalla-one/400.css";
import "@fontsource/cantarell/400.css";
import "@fontsource/cantarell/700.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
import "@fontsource/quicksand/400.css";
import "@fontsource/quicksand/700.css";
import "./theme/global.css";
import { AuthProvider, ThemeProvider, useAuth } from "./lib/context";
import Layout from "./components/Layout";
import Login from "./pages/Login";
import Home from "./pages/Home";
import Overview from "./pages/Overview";
import Catalogue from "./pages/Catalogue";
import Screening from "./pages/Screening";
import Encounters from "./pages/Encounters";
import Analytics from "./pages/Analytics";
import Datasets from "./pages/Datasets";
import MlLab from "./pages/MlLab";
import Scenarios from "./pages/Scenarios";
import Reports from "./pages/Reports";
import Admin from "./pages/Admin";
import Guide from "./pages/Guide";
import { Loading } from "./components/ui";

// Three.js is large; load the 3D view on demand.
const Environment = lazy(() => import("./pages/Environment"));
const EncounterDetail = lazy(() => import("./pages/EncounterDetail"));

const qc = new QueryClient({ defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } } });

function Gate() {
  const { me, loading } = useAuth();
  if (loading) return <Loading what="Checking session" />;
  if (!me) return <Login />;
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/p/:pid" element={<Layout />}>
        <Route index element={<Navigate to="overview" replace />} />
        <Route path="overview" element={<Overview />} />
        <Route path="catalogue" element={<Catalogue />} />
        <Route path="environment" element={<Suspense fallback={<Loading what="Loading 3D environment" />}><Environment /></Suspense>} />
        <Route path="screening" element={<Screening />} />
        <Route path="encounters" element={<Encounters />} />
        <Route path="encounters/:eid" element={<Suspense fallback={<Loading what="Loading encounter" />}><EncounterDetail /></Suspense>} />
        <Route path="analytics" element={<Analytics />} />
        <Route path="datasets" element={<Datasets />} />
        <Route path="ml" element={<MlLab />} />
        <Route path="scenarios" element={<Scenarios />} />
        <Route path="reports" element={<Reports />} />
        <Route path="admin" element={<Admin />} />
        <Route path="guide" element={<Guide />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={qc}>
      <ThemeProvider>
        <AuthProvider>
          <BrowserRouter>
            <Gate />
          </BrowserRouter>
        </AuthProvider>
      </ThemeProvider>
    </QueryClientProvider>
  </React.StrictMode>,
);
