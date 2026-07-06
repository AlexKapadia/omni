/**
 * React entry point. Mounts the app shell; nothing else lives here.
 */
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles/app.css";

const rootElement = document.getElementById("root");
if (rootElement === null) {
  // Fail loudly: a missing mount point means index.html drifted from main.tsx.
  throw new Error("Root element #root not found");
}

createRoot(rootElement).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
