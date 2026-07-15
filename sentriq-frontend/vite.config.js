import { defineConfig } from "vite"; // Vite config helper
import react from "@vitejs/plugin-react"; // JSX/Fast Refresh plugin

// Dev server proxies /api to the Django backend so the browser hits one origin.
// In prod the built bundle is served statically and talks to VITE_API_BASE.
export default defineConfig({
  plugins: [react()], // enable React transform
  server: {
    host: true, // listen on 0.0.0.0 for docker/LAN access
    port: 3000, // fixed frontend port
    strictPort: true, // fail if 3000 taken instead of picking another
    proxy: {
      "/api": {
        target: process.env.VITE_API_PROXY || "http://localhost:8000", // Django default
        changeOrigin: true, // rewrite Host header for backend
      },
    },
  },
});
