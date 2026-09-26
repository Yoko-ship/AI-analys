import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { parse } from "@babel/parser";

const root = path.resolve("frontend/src");
function importSpecifiers(node, result = []) {
  if (!node || typeof node !== "object") return result;
  if (["ImportDeclaration", "ExportNamedDeclaration", "ExportAllDeclaration", "ImportExpression"].includes(node.type) && node.source?.value) result.push(node.source.value);
  if (node.type === "CallExpression" && node.callee?.type === "Import" && node.arguments[0]?.value) result.push(node.arguments[0].value);
  for (const value of Object.values(node)) {
    if (Array.isArray(value)) value.forEach((child) => importSpecifiers(child, result));
    else if (value && typeof value === "object") importSpecifiers(value, result);
  }
  return result;
}
function sourceFiles(directory) {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    if (entry.name.startsWith(".")) return [];
    const file = path.join(directory, entry.name);
    return entry.isDirectory() ? sourceFiles(file) : /\.[jt]sx?$/.test(file) ? [file] : [];
  });
}

test("frontend imports respect feature interfaces and have no dependency cycles", () => {
  const graph = new Map();
  for (const file of sourceFiles(root)) {
    const name = path.relative(root, file).replaceAll("\\", "/");
    const ast = parse(fs.readFileSync(file, "utf8"), { sourceType: "module", plugins: ["jsx"] });
    const dependencies = importSpecifiers(ast.program)
      .filter((specifier) => specifier.startsWith("."))
      .map((specifier) => path.relative(root, path.resolve(path.dirname(file), specifier)).replaceAll("\\", "/"))
      .filter((specifier) => /\.[jt]sx?$/.test(specifier));
    graph.set(name, dependencies);
    for (const dependency of dependencies) {
      if (name !== "main.jsx") assert.notEqual(dependency, "App.jsx", `${name} must not import the composition root`);
      if (/^(shared|lib|session)\//.test(name)) {
        assert.ok(!/^(features|app)\//.test(dependency), `${name} cannot depend on feature or shell internals: ${dependency}`);
      }
      const feature = name.match(/^features\/([^/]+)\//)?.[1];
      const target = dependency.match(/^features\/([^/]+)\//)?.[1];
      if (target && target !== feature) {
        assert.equal(dependency, `features/${target}/index.js`, `${name} must use ${target}'s public interface`);
      }
    }
  }
  const seen = new Set();
  function visit(name, ancestors = []) {
    assert.ok(!ancestors.includes(name), `Circular dependency: ${[...ancestors, name].join(" -> ")}`);
    if (seen.has(name)) return;
    for (const dependency of graph.get(name) || []) visit(dependency, [...ancestors, name]);
    seen.add(name);
  }
  for (const name of graph.keys()) visit(name);
});
