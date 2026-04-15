/// <reference types="vitest" />
import fs from 'fs';
import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import path from 'path';
import {defineConfig, loadEnv} from 'vite';

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
