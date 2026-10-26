import { defineConfig } from "vitest/config";
import { fileURLToPath } from "node:url";

const r = (p: string) => fileURLToPath(new URL(p, import.meta.url));

export default defineConfig({
  esbuild: { jsx: "automatic" },
  resolve: {
    // Same reasoning as apps/web: @workspace/ui and @workspace/api-client
    // resolve `react` relative to their own package, and two copies in one graph
    // makes every hook throw "Invalid hook call".
    alias: [
      { find: /^react-dom\/client$/, replacement: r("./node_modules/react-dom/client.js") },
      { find: /^react-dom\/server$/, replacement: r("./node_modules/react-dom/server.js") },
      { find: /^react-dom\//, replacement: r("./node_modules/react-dom/") },
      { find: /^react-dom$/, replacement: r("./node_modules/react-dom") },
      { find: /^react\/jsx-runtime$/, replacement: r("./node_modules/react/jsx-runtime.js") },
      { find: /^react\/jsx-dev-runtime$/, replacement: r("./node_modules/react/jsx-dev-runtime.js") },
      { find: /^react\//, replacement: r("./node_modules/react/") },
      { find: /^react$/, replacement: r("./node_modules/react") },
      { find: /^@workspace\/ui\//, replacement: r("../../packages/ui/src/") },
      { find: /^@workspace\/api-client$/, replacement: r("../../packages/api-client/src/index.ts") },
      { find: /^@workspace\/api-client\//, replacement: r("../../packages/api-client/src/") },
      { find: /^@workspace\/schemas$/, replacement: r("../../packages/schemas/src/index.ts") },
      { find: /^@workspace\/schemas\//, replacement: r("../../packages/schemas/src/") },
      { find: /^@\//, replacement: r("./") },
    ],
    dedupe: ["react", "react-dom"],
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./vitest.setup.ts"],
    include: ["__tests__/**/*.test.{ts,tsx}"],
    exclude: ["node_modules/**", ".next/**"],
    server: { deps: { inline: [/framer-motion/, /^motion/, /^@base-ui\//] } },
  },
});
