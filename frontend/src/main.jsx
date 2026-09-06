import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import ErrorBoundary from "./components/ErrorBoundary.jsx";
import { persistQueryCache, restoreQueryCache } from "./lib/queryPersistence.js";

// The three self-hosted families (§2.2). Variable builds, so one file per
// family covers every weight the interface uses.
import "@fontsource-variable/source-serif-4";
import "@fontsource-variable/archivo";
import "@fontsource-variable/jetbrains-mono";

import "./styles/index.css";
import App from "./App.jsx";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // A market app that silently retries a failed request forever is a market
      // app that shows you a blank panel and no reason. Fail fast, then let the
      // component say what went wrong (R5).
      retry: 1,
      refetchOnWindowFocus: false,
      throwOnError: (error) => error?.name === "ZodError",
    },
  },
});

function QueryPersistence({ children }) {
  const [ready, setReady] = useState(false);
  useEffect(() => {
    let active = true;
    let unsubscribe;
    restoreQueryCache(queryClient)
      .then((restored) => persistQueryCache(queryClient).then((stop) => {
        if (active) unsubscribe = stop;
        else stop();
        return restored;
      }))
      .then(() => {
        if (active) setReady(true);
      })
      .catch((error) => {
        console.error("Query cache persistence unavailable", error);
        if (active) setReady(true);
      });
    return () => {
      active = false;
      unsubscribe?.();
    };
  }, []);
  return ready ? children : null;
}

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <QueryPersistence>
          <BrowserRouter>
            <App />
          </BrowserRouter>
        </QueryPersistence>
      </QueryClientProvider>
    </ErrorBoundary>
  </StrictMode>,
);
