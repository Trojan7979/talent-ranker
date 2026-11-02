import { defineConfig, loadEnv } from "vite";

export default defineConfig(({ mode }) => {
  const apiTarget = loadEnv(mode, process.cwd(), "SIEVE_").SIEVE_API_TARGET || "http://127.0.0.1:8000";
  return {
    cacheDir: "../.vite-recruiter-cache",
    server: {
      host: "127.0.0.1",
      port: 5173,
      strictPort: true,
      proxy: Object.fromEntries(
        ["ranking", "screening", "sources", "agent", "auth"].map((name) => [
          `/api/${name}`, { target: apiTarget, changeOrigin: true },
        ]),
      ),
    },
  };
});
