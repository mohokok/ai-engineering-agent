import path from "node:path";
import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const repoRoot = path.resolve(__dirname, "..");
  const env = { ...loadEnv(mode, repoRoot, ""), ...process.env };
  const host = env.FRONTEND_HOST || "127.0.0.1";
  const backendHost = env.BACKEND_HOST || "127.0.0.1";
  const backendPort = env.BACKEND_PORT || "8000";
  const frontendPort = Number(env.FRONTEND_PORT || "5173");

  return {
    plugins: [react()],
    server: {
      host,
      port: frontendPort,
      proxy: {
        "/api": {
          target: `http://${backendHost}:${backendPort}`,
          changeOrigin: true,
        },
      },
    },
  };
});
