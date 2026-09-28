import { defineConfig } from 'vite'
import uniPlugin from '@dcloudio/vite-plugin-uni'

// Uni-app Vite 插件兼容处理
const uni = (uniPlugin as any).default || uniPlugin

export default defineConfig({
  plugins: [
    uni(),
  ],
  resolve: {
    alias: {
      '@': '/src',
    },
  },
  server: {
    port: 5173,
    host: '0.0.0.0',
  },
})
