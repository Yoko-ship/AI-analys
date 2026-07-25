// Lint config with one job above all others: make Rules-of-Hooks violations
// impossible to ship.
//
// App.jsx is ~10k lines with ~60 components, and CompareTable shipped a `return
// null` sitting above two useMemo calls. That is not a style problem — a table
// toggling empty -> non-empty renders a different number of hooks than the
// previous pass, React throws, and the whole view blanks. A human reading a
// 10k-line file will not reliably catch the next one; this will.
//
// Everything else is set to `warn` (or off) on purpose: the existing code has its
// own conventions and this config is not a rewrite mandate. `react-hooks/*` is
// the error budget.
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";

export default [
  {
    ignores: ["web/dist/**", "node_modules/**", ".venv/**", "web/app.js", "**/*.min.js"],
  },
  {
    files: ["frontend/**/*.{js,jsx}"],
    languageOptions: {
      ecmaVersion: 2023,
      sourceType: "module",
      globals: { ...globals.browser, React: "readonly" },
      parserOptions: {
        ecmaFeatures: { jsx: true },
      },
    },
    plugins: { "react-hooks": reactHooks },
    rules: {
      // The whole point of this config.
      "react-hooks/rules-of-hooks": "error",
      // Advisory: stale-closure bugs are real but fixing every dep array in a
      // 10k-line file is a separate, deliberate piece of work.
      "react-hooks/exhaustive-deps": "warn",
      // Catches typo'd identifiers and accidental globals, which in a file this
      // size are otherwise found only at runtime.
      "no-undef": "error",
      "no-dupe-keys": "error",
      "no-unreachable": "error",
      "no-unsafe-negation": "error",
      "no-cond-assign": "error",
      "no-constant-condition": ["error", { checkLoops: false }],
    },
  },
  {
    files: ["tests/**/*.js", "*.config.js"],
    languageOptions: {
      ecmaVersion: 2023,
      sourceType: "module",
      globals: { ...globals.node },
    },
    rules: { "no-undef": "error" },
  },
];
