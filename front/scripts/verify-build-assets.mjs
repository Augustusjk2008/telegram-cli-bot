import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const frontRoot = path.resolve(scriptDir, '..');
const indexPath = path.join(frontRoot, 'dist', 'index.html');
const thirdPartyLicensesPath = path.join(frontRoot, 'dist', 'THIRD_PARTY_LICENSES.txt');

if (!fs.existsSync(indexPath)) {
  console.error('缺少 front/dist/index.html，请先构建前端。');
  process.exit(1);
}

if (!fs.existsSync(thirdPartyLicensesPath)) {
  console.error('缺少 front/dist/THIRD_PARTY_LICENSES.txt，请重新构建前端。');
  process.exit(1);
}
const thirdPartyLicenses = fs.readFileSync(thirdPartyLicensesPath, 'utf8');
if (!thirdPartyLicenses.startsWith('ORBIT SAFE CLAW - FRONTEND THIRD-PARTY LICENSES\n')
  || !/^Packages: [1-9][0-9]*$/m.test(thirdPartyLicenses)) {
  console.error('front/dist/THIRD_PARTY_LICENSES.txt 内容无效，请重新构建前端。');
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
