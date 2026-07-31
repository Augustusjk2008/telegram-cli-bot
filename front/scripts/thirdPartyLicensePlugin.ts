import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import type { Plugin } from 'vite';

const LEGAL_FILE_PATTERN = /^(?:licen[cs]e|copying|notice|copyright|patents?)(?:$|[._-])/i;

type PackageMetadata = {
  name?: string;
  version?: string;
  license?: string | { type?: string };
  author?: string | { name?: string; email?: string; url?: string };
  repository?: string | { url?: string };
  homepage?: string;
};

type LicenseDocument = {
  label: string;
  text: string;
};

type PackageLicenseEntry = {
  identity: string;
  name: string;
  version: string;
  declaredLicense: string;
  source: string;
  documents: LicenseDocument[];
};

export function packageRootFromModuleId(moduleId: string) {
  const normalized = String(moduleId || '').replace(/\\/g, '/').split('?', 1)[0];
  const marker = '/node_modules/';
  const markerIndex = normalized.lastIndexOf(marker);
  if (markerIndex < 0) {
    return null;
  }

  const packagePath = normalized.slice(markerIndex + marker.length);
  const segments = packagePath.split('/').filter(Boolean);
  const packageSegmentCount = segments[0]?.startsWith('@') ? 2 : 1;
  if (segments.length < packageSegmentCount) {
    return null;
  }
  const root = `${normalized.slice(0, markerIndex + marker.length)}${segments.slice(0, packageSegmentCount).join('/')}`;
  return path.normalize(root);
}

function readTextFile(filePath: string) {
  return fs.readFileSync(filePath, 'utf8').replace(/^\uFEFF/, '').trimEnd();
}

function collectDirectoryFiles(directory: string, root: string): LicenseDocument[] {
  const documents: LicenseDocument[] = [];
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    const absolutePath = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      documents.push(...collectDirectoryFiles(absolutePath, root));
    } else if (entry.isFile()) {
      documents.push({
        label: path.relative(root, absolutePath).replace(/\\/g, '/'),
        text: readTextFile(absolutePath),
      });
    }
  }
  return documents;
}

function collectLegalDocuments(packageRoot: string) {
  const documents: LicenseDocument[] = [];
  for (const entry of fs.readdirSync(packageRoot, { withFileTypes: true })) {
    const absolutePath = path.join(packageRoot, entry.name);
    if (entry.isFile() && LEGAL_FILE_PATTERN.test(entry.name)) {
      documents.push({ label: entry.name, text: readTextFile(absolutePath) });
    } else if (entry.isDirectory() && /^licen[cs]es?$/i.test(entry.name)) {
      documents.push(...collectDirectoryFiles(absolutePath, packageRoot));
    }
  }
  return documents.sort((left, right) => left.label.localeCompare(right.label));
}

function metadataLicense(metadata: PackageMetadata) {
  if (typeof metadata.license === 'string') {
    return metadata.license.trim();
  }
  return String(metadata.license?.type || '').trim();
}

function metadataAuthor(metadata: PackageMetadata, packageName: string) {
  if (typeof metadata.author === 'string' && metadata.author.trim()) {
    return metadata.author.trim();
  }
  if (metadata.author && typeof metadata.author === 'object') {
    const details = [metadata.author.name, metadata.author.email, metadata.author.url]
      .map((value) => String(value || '').trim())
      .filter(Boolean);
    if (details.length > 0) {
      return details.join(' · ');
    }
  }
  return `${packageName} authors and contributors`;
}

function metadataSource(metadata: PackageMetadata) {
  if (typeof metadata.repository === 'string') {
    return metadata.repository;
  }
  return String(metadata.repository?.url || metadata.homepage || '').trim();
}

function mitFallback(attribution: string) {
  return `Copyright (c) ${attribution}

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.`;
}

function fallbackLicenseDocument(metadata: PackageMetadata, packageName: string) {
  const declaredLicense = metadataLicense(metadata);
  if (declaredLicense === 'MIT') {
    return {
      label: 'MIT (reproduced from declared package metadata)',
      text: mitFallback(metadataAuthor(metadata, packageName)),
    };
  }
  return null;
}

function loadPackageEntry(packageRoot: string, frontRoot: string): PackageLicenseEntry {
  const packageJsonPath = path.join(packageRoot, 'package.json');
  if (!fs.existsSync(packageJsonPath)) {
    throw new Error(`第三方模块缺少 package.json: ${packageRoot}`);
  }
  const metadata = JSON.parse(readTextFile(packageJsonPath)) as PackageMetadata;
  const name = String(metadata.name || path.basename(packageRoot));
  const version = String(metadata.version || 'unknown');
  const declaredLicense = metadataLicense(metadata) || 'UNDECLARED';
  const documents = collectLegalDocuments(packageRoot);
  const fallback = documents.length === 0 ? fallbackLicenseDocument(metadata, name) : null;
  if (fallback) {
    documents.push(fallback);
  }

  const overrideRoot = path.join(frontRoot, 'scripts', 'license-overrides', name.replace('/', '__'));
  if (fs.existsSync(overrideRoot)) {
    documents.push(...collectDirectoryFiles(overrideRoot, overrideRoot).map((document) => ({
      ...document,
      label: `project override/${document.label}`,
    })));
  }
  if (documents.length === 0) {
    throw new Error(`${name}@${version} 未随包提供许可证文本，且没有项目 override（声明: ${declaredLicense}）`);
  }

  return {
    identity: `${name}@${version}`,
    name,
    version,
    declaredLicense,
    source: metadataSource(metadata),
    documents,
  };
}

export function createThirdPartyLicenseReport(moduleIds: Iterable<string>, frontRoot: string) {
  const packageRoots = new Set<string>();
  for (const moduleId of moduleIds) {
    const packageRoot = packageRootFromModuleId(moduleId);
    if (packageRoot && fs.existsSync(packageRoot)) {
      packageRoots.add(packageRoot);
    }
  }

  const byIdentity = new Map<string, PackageLicenseEntry>();
  const errors: string[] = [];
  for (const packageRoot of [...packageRoots].sort()) {
    try {
      const entry = loadPackageEntry(packageRoot, frontRoot);
      const existing = byIdentity.get(entry.identity);
      if (!existing) {
        byIdentity.set(entry.identity, entry);
      }
    } catch (error) {
      errors.push(error instanceof Error ? error.message : String(error));
    }
  }
  if (errors.length > 0) {
    throw new Error(`无法生成完整的前端第三方许可证合集:\n- ${errors.join('\n- ')}`);
  }

  const lockfile = fs.readFileSync(path.join(frontRoot, 'package-lock.json'));
  const lockfileSha256 = crypto.createHash('sha256').update(lockfile).digest('hex');
  const entries = [...byIdentity.values()].sort((left, right) => left.identity.localeCompare(right.identity));
  const sections = entries.map((entry) => {
    const heading = [
      '='.repeat(80),
      entry.identity,
      `Declared license: ${entry.declaredLicense}`,
      entry.source ? `Upstream: ${entry.source}` : '',
    ].filter(Boolean).join('\n');
    const documents = entry.documents.map((document) => [
      `--- ${document.label} ---`,
      document.text,
    ].join('\n')).join('\n\n');
    return `${heading}\n\n${documents}`;
  });

  return [
    'ORBIT SAFE CLAW - FRONTEND THIRD-PARTY LICENSES',
    '',
    'This file is generated from the third-party modules included by the final Vite build.',
    'Package license files are reproduced verbatim; explicitly labelled fallbacks are used',
    'only when installed package metadata declares MIT but ships no standalone license file.',
    `package-lock.json SHA-256: ${lockfileSha256}`,
    `Packages: ${entries.length}`,
    '',
    ...sections,
    '',
  ].join('\n');
}

export function thirdPartyLicensePlugin(frontRoot: string): Plugin {
  return {
    name: 'orbit-third-party-licenses',
    apply: 'build',
    generateBundle(_outputOptions, bundle) {
      const moduleIds = new Set<string>();
      for (const output of Object.values(bundle)) {
        if (output.type !== 'chunk') {
          continue;
        }
        for (const moduleId of Object.keys(output.modules)) {
          moduleIds.add(moduleId);
        }
      }
      const source = createThirdPartyLicenseReport(moduleIds, frontRoot);
      this.emitFile({
        type: 'asset',
        fileName: 'THIRD_PARTY_LICENSES.txt',
        source,
      });
    },
  };
}
