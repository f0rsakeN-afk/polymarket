import { defineConfig } from "vitest/config";
import { fileURLToPath } from "node:url";

const r = (p: string) => fileURLToPath(new URL(p, import.meta.url));

export default defineConfig({
  // No @vitejs/plugin-react: v6 requires Vite 7 while vitest 3 ships Vite 5/6,
  // and the plugin only adds Fast Refresh, which tests do not need. Vitest
  // transforms .tsx through esbuild with the automatic JSX runtime.
  esbuild: { jsx: "automatic" },
  resolve: {
    // packages/ui pins react 19.2.4 but apps/web pins 19.2.8, and @workspace/ui
    // components import "react" relative to their own package. Two copies in one
    // module graph makes every hook throw "Invalid hook call", so both are pinned
    // to apps/web's copy here. Order matters: Vite takes the first match and a
    // string alias also matches on a "/" prefix, so the most specific key wins.
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
    server: {
      deps: {
        // Vitest externalises node_modules by default, and an externalised
        // module is loaded by Node's resolver - which bypasses the aliases
        // above. framer-motion (behind motion/react) then pulled in
        // packages/ui's react 19.2.4 alongside apps/web's 19.2.8, and every
        // hook threw "Cannot read properties of null (reading 'useContext')".
        // Inlining pushes those deps through Vite so the aliases apply.
        inline: [/framer-motion/, /^motion/, /@visx/, /d3-[a-z]+/, /cmdk/],
      },
    },
    // The live chart runs a perpetual rAF loop; a leaked timer would hang the run.
    teardownTimeout: 10_000,
  },
});