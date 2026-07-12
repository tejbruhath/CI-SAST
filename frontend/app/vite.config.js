import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    host: true,
    // In local dev, proxy /artifacts to a static server or the nginx box so the
    // data layer behaves the same as production. Override via VITE_ARTIFACTS_PROXY.
    proxy: process.env.VITE_ARTIFACTS_PROXY
      ? { "/artifacts": { target: process.env.VITE_ARTIFACTS_PROXY, changeOrigin: true } }
      : undefined,
  },
  preview: { port: 3000, host: true },
});
