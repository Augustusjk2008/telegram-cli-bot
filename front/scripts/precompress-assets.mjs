import fs from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {promisify} from 'node:util';
import {brotliCompress, constants, gzip} from 'node:zlib';

const brotliCompressAsync = promisify(brotliCompress);
const gzipAsync = promisify(gzip);
const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const distRoot = path.resolve(scriptDir, '..', 'dist');
const manifestPath = path.join(distRoot, '.vite', 'manifest.json');

function collectCompressibleAssets(manifest) {
  const files = new Set();
  for (const entry of Object.values(manifest)) {
    if (!entry || typeof entry !== 'object') {
      continue;
    }
    const candidates = [entry.file, ...(Array.isArray(entry.css) ? entry.css : [])];
    for (const candidate of candidates) {
      if (typeof candidate === 'string' && /\.(?:js|css)$/i.test(candidate)) {
        files.add(candidate);
      }
    }
  }
  return [...files].sort();
}

function resolveDistAsset(relativePath) {
  const absolutePath = path.resolve(distRoot, relativePath);
  if (!absolutePath.startsWith(`${distRoot}${path.sep}`)) {
    throw new Error(`Vite manifest 含越界资源路径: ${relativePath}`);
  }
  return absolutePath;
}

const manifest = JSON.parse(await fs.readFile(manifestPath, 'utf8'));
const assetFiles = collectCompressibleAssets(manifest);
if (assetFiles.length === 0) {
  throw new Error('Vite manifest 未列出可预压缩的 JS/CSS 资源。');
}

for (const relativePath of assetFiles) {
  const sourcePath = resolveDistAsset(relativePath);
  const source = await fs.readFile(sourcePath);
  const [brotli, gzipped] = await Promise.all([
    brotliCompressAsync(source, {
      params: {[constants.BROTLI_PARAM_QUALITY]: 11},
    }),
    gzipAsync(source, {level: constants.Z_BEST_COMPRESSION}),
  ]);
  await Promise.all([
    fs.writeFile(`${sourcePath}.br`, brotli),
    fs.writeFile(`${sourcePath}.gz`, gzipped),
  ]);
}

console.log(`已为 ${assetFiles.length} 个 Vite JS/CSS 资源生成 Brotli 和 gzip 副本。`);
