import { defineConfig } from "@eodash/eodash/config";

export default defineConfig({
  base: process.env.EODASH_BASE_PATH || "/",
  dev: {
    port: 3000,
    strictPort: true,
  },
  vite: {
    worker: {
      format: "es",
    },
  },
});
