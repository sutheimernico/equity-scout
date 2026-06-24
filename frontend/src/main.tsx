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
