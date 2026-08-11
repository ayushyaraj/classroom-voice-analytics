import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In dev the API runs on 8000; the proxy keeps fetch("/api/...") identical
// between dev and the single container production build.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8000",
    },
  },
});
