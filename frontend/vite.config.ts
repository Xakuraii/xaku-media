import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "path";

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  // Electron loads the production build via loadFile() (file:// protocol),
  // where absolute "/assets/..." URLs resolve to the drive root and the
  // renderer stays blank. Relative paths work under file://, the Vite dev
  // server, and root-hosted static deployments (Vercel) alike.
  base: "./",
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    strictPort: true,
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
