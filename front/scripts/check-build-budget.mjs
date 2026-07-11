import fs from 'node:fs';
import path from 'node:path';

const root = process.cwd();
const dist = path.resolve(root, 'dist');
const manifestPath = path.resolve(dist, '.vite', 'manifest.json');
const limits = {
  entry: 650 * 1024,
  vendor: 500 * 1024,
  mermaid: 650 * 1024,
};

if (!fs.existsSync(manifestPath)) {
  throw new Error(`Vite manifest 不存在：${manifestPath}`);
}

const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
const entries = Object.entries(manifest);
const failures = [];

function assetSize(file) {
  const target = path.resolve(dist, file);
  return fs.existsSync(target) ? fs.statSync(target).size : 0;
}

function assertBudget(label, file, limit) {
  const size = assetSize(file);
  if (size > limit) {
    failures.push(`${label} ${file} 为 ${size} bytes，超过 ${limit} bytes`);
  }
}

const entryChunks = entries.filter(([, item]) => item.isEntry);
if (entryChunks.length === 0) {
  failures.push('manifest 中没有 isEntry chunk');
}
for (const [, item] of entryChunks) {
  assertBudget('entry', item.file, limits.entry);
}

for (const [, item] of entries) {
  if (/vendor/i.test(item.file) && !/mermaid/i.test(item.file)) {
    assertBudget('vendor', item.file, limits.vendor);
  }
  if (/mermaid/i.test(item.file) || /mermaid/i.test(item.name || '')) {
    assertBudget('mermaid', item.file, limits.mermaid);
  }
}

const entryImports = new Set();
const visitImports = (key) => {
  if (entryImports.has(key)) return;
  entryImports.add(key);
  for (const imported of manifest[key]?.imports || []) visitImports(imported);
};
for (const [key] of entryChunks) visitImports(key);
for (const key of entryImports) {
  const item = manifest[key];
  if (/mermaid/i.test(key) || /mermaid/i.test(item?.file || '') || /mermaid/i.test(item?.name || '')) {
    failures.push(`Mermaid chunk 被首屏静态 preload：${item?.file || key}`);
  }
}

const html = fs.readFileSync(path.resolve(dist, 'index.html'), 'utf8');
if (/modulepreload[^>]+mermaid/i.test(html)) {
  failures.push('index.html 预加载了 Mermaid chunk');
}

if (failures.length > 0) {
  throw new Error(`前端构建预算检查失败：\n- ${failures.join('\n- ')}`);
}

console.log(`构建预算通过：${entryChunks.length} 个 entry，${entries.length} 个 manifest chunk，Mermaid 保持懒加载。`);
