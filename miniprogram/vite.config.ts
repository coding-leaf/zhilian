import { resolve } from 'path';
import { defineConfig } from 'vite';
import uniPkg from '@dcloudio/vite-plugin-uni';

// Handle CJS/ESM interop for @dcloudio/vite-plugin-uni
const uni =
  typeof uniPkg === 'function'
    ? uniPkg
    : (uniPkg as any).default?.default || (uniPkg as any).default || uniPkg;

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
