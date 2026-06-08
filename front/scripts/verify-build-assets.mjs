import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const frontRoot = path.resolve(scriptDir, '..');
const indexPath = path.join(frontRoot, 'dist', 'index.html');

if (!fs.existsSync(indexPath)) {
  console.error('缺少 front/dist/index.html，请先构建前端。');
  process.exit(1);
}

const indexHtml = fs.readFileSync(indexPath, 'utf8');
const pollutedAssetPattern = /\/node\/[^"'<> \t\r\n]*\/assets\//g;
const matches = [...new Set(indexHtml.match(pollutedAssetPattern) || [])];

if (matches.length > 0) {
  console.error('front/dist/index.html 含本机 /node/.../assets/ 前缀：');
  for (const match of matches.slice(0, 10)) {
    console.error(`- ${match}`);
  }
  process.exit(1);
}
