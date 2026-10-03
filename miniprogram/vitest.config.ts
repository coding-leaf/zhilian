import { defineConfig } from 'vitest/config'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  test: {
    environment: 'happy-dom',
    globals: true,
    setupFiles: ['./tests/setup.ts'],
    // 覆盖率只统计与留档，暂不设 thresholds —— 首次接入无历史基线，
    // 直接设阈值会让 CI 立刻变红，把「未基线化」误读成「代码有问题」。
    // 阈值在 M0 基线化取到实测值后再定（见 中期质量检查/单测计划.md）。
    coverage: {
      provider: 'v8',
      reporter: ['text', 'lcov'],
      reportsDirectory: './coverage',
      include: ['src/**/*.{ts,vue}'],
      exclude: [
        'src/main.ts',
        'src/env.d.ts',
        'src/pages.json',
        'src/manifest.json',
        'src/types/**',
      ],
    },
  },
})
