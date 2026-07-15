import React from "react"; // React core for JSX components
import { createRoot } from "react-dom/client"; // React 18 root API
import App from "./App.jsx"; // top-level Sentriq SPA shell
import "./styles.css"; // global Tailwind + theme CSS

// Mount the app into #root from index.html.
createRoot(document.getElementById("root")).render(
  <React.StrictMode> {/* double-invoke effects in dev to catch bugs */}
    <App /> {/* full dashboard: auth, scans, findings, HITL */}
  </React.StrictMode>
);
