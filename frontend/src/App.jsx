import { Navigate, Route, Routes } from "react-router-dom";
import AppShell from "./components/shell/AppShell.jsx";
import TokensPage from "./pages/TokensPage.jsx";
import Brief from "./routes/Brief.jsx";
import Overview from "./routes/Overview.jsx";
import Landing from "./routes/Landing.jsx";
import Auth from "./routes/Auth.jsx";
import Watchlist from "./routes/Watchlist.jsx";
import Symbol from "./routes/Symbol.jsx";
import Eval from "./routes/Eval.jsx";
import Settings from "./routes/Settings.jsx";

/**
 * App.jsx — the route table.
 *
 * Stage 1 builds the foundation only, so /tokens is the one real route. The
 * remaining routes from FRONTEND_SPEC §5 arrive in their own stages and are
 * absent until then rather than stubbed: a route that renders "coming soon" is
 * a lie the router tells the reviewer.
 */
export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/login" element={<Auth mode="login" />} />
      <Route path="/register" element={<Auth mode="register" />} />
      <Route element={<AppShell />}>
        <Route path="/tokens" element={<TokensPage />} />
        <Route path="/brief" element={<Brief />} />
        <Route path="/overview" element={<Overview />} />
        <Route path="/watchlist/:id" element={<Watchlist />} />
        <Route path="/symbol/:symbol" element={<Symbol />} />
        <Route path="/eval" element={<Eval />} />
        <Route path="/settings" element={<Settings />} />
      </Route>
      {/* Stage 5 replaces this with the landing page at "/". */}
      <Route path="*" element={<Navigate to="/tokens" replace />} />
    </Routes>
  );
}
