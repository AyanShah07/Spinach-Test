import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTypescript from "eslint-config-next/typescript";
export default defineConfig([
  ...nextVitals,
  ...nextTypescript,
  {
    settings: {
      react: {
        version: "19.0",
      },
    },
  },
  globalIgnores([".next/**", "out/**", "next-env.d.ts"]),
]);
