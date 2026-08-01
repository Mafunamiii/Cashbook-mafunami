import "./sentry";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import * as Sentry from "@sentry/react";

import { App } from "./App";
import "./styles/global.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <Sentry.ErrorBoundary
      fallback={
        <p role="alert">Something went wrong. Please reload the page.</p>
      }
    >
      <App />
    </Sentry.ErrorBoundary>
  </StrictMode>,
);
