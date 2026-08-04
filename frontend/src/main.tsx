import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App";
import "./index.css";

// React 19: createRoot from react-dom/client is the entry; StrictMode double-invokes
// effects in dev only to surface impure logic.
createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);

// Production only: a service worker in front of the Vite dev server serves stale modules
// and makes HMR behave in ways that cost more time than the offline test is worth.
if (import.meta.env.PROD && "serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {
      // A failed registration is not fatal — the app just stays online-only.
    });
  });
}
