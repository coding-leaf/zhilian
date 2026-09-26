import { resolve } from 'path';
import { defineConfig } from 'vite';
import uniPkg from '@dcloudio/vite-plugin-uni';

// Handle CJS/ESM interop for @dcloudio/vite-plugin-uni
const uniPkgRecord = uniPkg as unknown as { default?: { default?: unknown } | unknown };
const uni =
  typeof uniPkg === 'function'
    ? uniPkg
    : (uniPkgRecord.default as { default?: unknown })?.default || uniPkgRecord.default || uniPkg;

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [uni()],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  css: {
    preprocessorOptions: {
      scss: {
        api: 'modern-compiler',
        silenceDeprecations: ['legacy-js-api', 'import'],
      },
    },
  },
  server: {
    port: 3000,
    open: false,
  },
});
