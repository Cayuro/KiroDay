import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Build output goes to `dist/` so AWS Amplify Hosting can serve it directly.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "dist",
  },
});
