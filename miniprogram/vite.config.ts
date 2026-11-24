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
  build: {
    // es2018 同时降级 ES2020 `??`/`?.` 与 ES2019 optional catch binding `catch {}`，兼容低版本微信基础库与旧 iOS JSCore
    target: 'es2018',
  },
  server: {
    port: 5173,
    host: '0.0.0.0',
  },
})
