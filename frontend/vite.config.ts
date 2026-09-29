import { defineConfig } from "vite";

export default defineConfig({
  server: {
    proxy: {
      "/api/ranking": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
      "/api/screening": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
});
