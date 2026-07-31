import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {afterEach, describe, expect, test} from 'vitest';
import {
  createThirdPartyLicenseReport,
  packageRootFromModuleId,
} from '../../scripts/thirdPartyLicensePlugin';

const temporaryRoots: string[] = [];

afterEach(() => {
  for (const root of temporaryRoots.splice(0)) {
    fs.rmSync(root, {recursive: true, force: true});
  }
});

function createFixturePackage(options: {licenseFile?: string; license?: string} = {}) {
  const frontRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'orbit-license-plugin-'));
  temporaryRoots.push(frontRoot);
  fs.writeFileSync(path.join(frontRoot, 'package-lock.json'), '{"lockfileVersion":3}\n');
  const packageRoot = path.join(frontRoot, 'node_modules', '@scope', 'fixture');
  fs.mkdirSync(packageRoot, {recursive: true});
  fs.writeFileSync(path.join(packageRoot, 'package.json'), JSON.stringify({
    name: '@scope/fixture',
    version: '1.2.3',
    license: options.license ?? 'MIT',
    author: 'Fixture Author',
    repository: 'https://example.invalid/fixture',
  }));
  if (options.licenseFile) {
    fs.writeFileSync(path.join(packageRoot, 'LICENSE'), options.licenseFile);
  }
  return {frontRoot, packageRoot};
}

describe('third-party license bundle', () => {
  test('resolves scoped package roots from Windows and POSIX module ids', () => {
    expect(packageRootFromModuleId('C:\\repo\\front\\node_modules\\@scope\\pkg\\dist\\index.js'))
      .toBe(path.normalize('C:/repo/front/node_modules/@scope/pkg'));
    expect(packageRootFromModuleId('/repo/front/node_modules/plain/index.js?commonjs-proxy'))
      .toBe(path.normalize('/repo/front/node_modules/plain'));
    expect(packageRootFromModuleId('/repo/front/src/app.ts')).toBeNull();
  });

  test('reproduces an upstream license file in the report', () => {
    const {frontRoot, packageRoot} = createFixturePackage({licenseFile: 'UPSTREAM LICENSE TEXT'});
    const report = createThirdPartyLicenseReport([path.join(packageRoot, 'index.js')], frontRoot);

    expect(report).toContain('@scope/fixture@1.2.3');
    expect(report).toContain('--- LICENSE ---');
    expect(report).toContain('UPSTREAM LICENSE TEXT');
  });

  test('uses labelled MIT terms when upstream metadata has no license file', () => {
    const {frontRoot, packageRoot} = createFixturePackage();
    const report = createThirdPartyLicenseReport([path.join(packageRoot, 'index.js')], frontRoot);

    expect(report).toContain('MIT (reproduced from declared package metadata)');
    expect(report).toContain('Copyright (c) Fixture Author');
    expect(report).toContain('Permission is hereby granted');
  });

  test('rejects packages without usable license terms', () => {
    const {frontRoot, packageRoot} = createFixturePackage({license: 'SEE LICENSE IN MISSING FILE'});

    expect(() => createThirdPartyLicenseReport([path.join(packageRoot, 'index.js')], frontRoot))
      .toThrow('未随包提供许可证文本');
  });
});
