import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./styles/style.css";
import "./styles/studio.css";
import "./styles/workbench.css";
import "./styles/clip-library.css";
import "./styles/editor-layout.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
