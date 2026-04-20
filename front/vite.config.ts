/// <reference types="vitest" />
import fs from 'fs';
import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import path from 'path';
import {defineConfig, loadEnv} from 'vite';

function getNodeModulePackageName(id: string) {
  const normalized = id.replace(/\\/g, '/');
  const nodeModulesMarker = '/node_modules/';
  const startIndex = normalized.lastIndexOf(nodeModulesMarker);
  if (startIndex < 0) {
    return null;
  }

  const packagePath = normalized.slice(startIndex + nodeModulesMarker.length);
  const segments = packagePath.split('/');
  if (segments[0]?.startsWith('@')) {
    return segments.length >= 2 ? `${segments[0]}/${segments[1]}` : segments[0];
  }
  return segments[0] || null;
}

function isMarkdownVendor(packageName: string) {
  return (
    packageName === 'katex'
    || packageName === 'react-markdown'
    || packageName === 'unified'
    || packageName === 'vfile'
    || packageName === 'bail'
    || packageName === 'devlop'
    || packageName === 'trough'
    || packageName === 'zwitch'
    || packageName === 'is-plain-obj'
    || packageName === 'property-information'
    || packageName === 'space-separated-tokens'
    || packageName === 'comma-separated-tokens'
    || packageName === 'html-url-attributes'
    || packageName === 'decode-named-character-reference'
    || packageName === 'longest-streak'
    || packageName === 'ccount'
    || packageName === 'markdown-table'
    || packageName === 'trim-lines'
    || packageName === 'extend'
    || packageName === 'style-to-object'
    || packageName === 'style-to-js'
    || packageName === 'inline-style-parser'
    || packageName === 'vfile-message'
    || packageName === 'escape-string-regexp'
    || packageName === 'estree-util-is-identifier-name'
    || packageName.startsWith('remark-')
    || packageName.startsWith('rehype-')
    || packageName.startsWith('micromark')
    || packageName.startsWith('mdast-')
    || packageName.startsWith('hast-')
    || packageName.startsWith('unist-')
    || packageName.startsWith('character-entities')
  );
}

function isMermaidVendor(packageName: string) {
  return (
    packageName === 'mermaid'
    || packageName === '@braintree/sanitize-url'
    || packageName === '@iconify/utils'
    || packageName === '@upsetjs/venn.js'
    || packageName === '@mermaid-js/parser'
    || packageName === 'cytoscape'
    || packageName === 'cytoscape-cose-bilkent'
    || packageName === 'cytoscape-fcose'
    || packageName === 'dagre-d3-es'
    || packageName === 'dayjs'
    || packageName === 'dompurify'
    || packageName === 'khroma'
    || packageName === 'lodash-es'
    || packageName === 'marked'
    || packageName === 'roughjs'
    || packageName === 'stylis'
    || packageName === 'ts-dedent'
    || packageName === 'uuid'
    || packageName === 'd3'
    || packageName.startsWith('d3-')
  );
}

function isEditorVendor(packageName: string) {
  return (
    packageName === '@babel/runtime'
    || packageName === 'codemirror'
    || packageName === 'crelt'
    || packageName === 'style-mod'
    || packageName === 'w3c-keyname'
    || packageName === 'marijn-find-cluster-break'
    || packageName === 'orderedmap'
    || packageName.startsWith('@uiw/')
    || packageName.startsWith('@codemirror/')
    || packageName.startsWith('@lezer/')
  );
}

function isEditorLanguageVendor(packageName: string) {
  return (
    packageName.startsWith('@codemirror/lang-')
    || packageName === '@lezer/css'
    || packageName === '@lezer/html'
    || packageName === '@lezer/javascript'
    || packageName === '@lezer/json'
    || packageName === '@lezer/markdown'
    || packageName === '@lezer/python'
  );
}

function resolveVendorChunk(id: string) {
  const packageName = getNodeModulePackageName(id);
  if (!packageName) {
    return undefined;
  }

  if (packageName === 'react' || packageName === 'react-dom' || packageName === 'scheduler') {
    return 'react-vendor';
  }

  if (packageName === 'lucide-react') {
    return 'icons-vendor';
  }

  if (packageName.startsWith('@xterm/')) {
    return 'terminal-vendor';
  }

  if (isMermaidVendor(packageName)) {
    return 'mermaid-vendor';
  }

  if (isMarkdownVendor(packageName)) {
    return 'markdown-vendor';
  }

  if (isEditorLanguageVendor(packageName)) {
    return 'editor-language-vendor';
  }

  if (isEditorVendor(packageName)) {
    return 'editor-vendor';
  }

  return 'vendor';
}

export default defineConfig(({mode}) => {
  const repoRoot = path.resolve(__dirname, '..');
  const frontRoot = path.resolve(__dirname, '.');
  const appVersion = fs.readFileSync(path.resolve(repoRoot, 'VERSION'), 'utf-8').trim();
  const env = {
    ...loadEnv(mode, repoRoot, ''),
    ...loadEnv(mode, frontRoot, ''),
  };
  const publicEnv = Object.fromEntries(
    Object.entries(env).filter(([key]) => key.startsWith('VITE_')),
  );
  return {
    plugins: [react(), tailwindcss()],
    test: {
      globals: true,
      environment: 'jsdom',
      setupFiles: ['./src/test/setup.ts'],
      include: ['src/test/**/*.test.ts', 'src/test/**/*.test.tsx'],
    },
    define: {
      'process.env.GEMINI_API_KEY': JSON.stringify(env.GEMINI_API_KEY),
      __PUBLIC_ENV__: JSON.stringify(publicEnv),
      __APP_VERSION__: JSON.stringify(appVersion),
    },
    resolve: {
      alias: {
        '@': path.resolve(__dirname, '.'),
      },
    },
    build: {
      rollupOptions: {
        output: {
          manualChunks(id) {
            return resolveVendorChunk(id);
          },
        },
      },
    },
    server: {
      host: '0.0.0.0',
      port: 3000,
      // HMR is disabled in AI Studio via DISABLE_HMR env var.
      // Do not modifyâfile watching is disabled to prevent flickering during agent edits.
      hmr: process.env.DISABLE_HMR !== 'true',
      proxy: {
        '/api': {
          target: 'http://127.0.0.1:8765',
          changeOrigin: true,
        },
      },
    },
  };
});
