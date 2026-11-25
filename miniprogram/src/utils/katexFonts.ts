/**
 * 自托管 KaTeX 数学字体异步加载器（微信小程序 `wx.loadFontFace`）。
 *
 * 从 `API_BASE_URL` 推导同源静态资源前缀 `${origin}/static/fonts/katex/`，
 * 在生产 HTTPS 环境下静默注册全局数学字体；非微信宿主、Vitest 或本地 HTTP
 * 开发环境静默跳过，绝不抛出异常或阻塞冷启动。
 */
import { API_BASE_URL } from './request'

interface KatexFontSpec {
  family: string
  file: string
  style: 'normal' | 'italic'
  weight: 'normal' | 'bold'
}

interface WxLoadFontFaceOptions {
  global?: boolean
  family: string
  source: string
  desc?: {
    style?: string
    weight?: string
  }
  success?: () => void
  fail?: (err: unknown) => void
}

interface WxFontHost {
  loadFontFace?: (options: WxLoadFontFaceOptions) => void
}

const KATEX_CORE_FONTS: readonly KatexFontSpec[] = [
  { family: 'KaTeX_Main', file: 'KaTeX_Main-Regular.woff2', style: 'normal', weight: 'normal' },
  { family: 'KaTeX_Math', file: 'KaTeX_Math-Italic.woff2', style: 'italic', weight: 'normal' },
  { family: 'KaTeX_Main', file: 'KaTeX_Main-Bold.woff2', style: 'normal', weight: 'bold' },
  { family: 'KaTeX_Main', file: 'KaTeX_Main-Italic.woff2', style: 'italic', weight: 'normal' },
  { family: 'KaTeX_Main', file: 'KaTeX_Main-BoldItalic.woff2', style: 'italic', weight: 'bold' },
  { family: 'KaTeX_Math', file: 'KaTeX_Math-BoldItalic.woff2', style: 'italic', weight: 'bold' },
  { family: 'KaTeX_Size1', file: 'KaTeX_Size1-Regular.woff2', style: 'normal', weight: 'normal' },
  { family: 'KaTeX_Size2', file: 'KaTeX_Size2-Regular.woff2', style: 'normal', weight: 'normal' },
  { family: 'KaTeX_Size3', file: 'KaTeX_Size3-Regular.woff2', style: 'normal', weight: 'normal' },
  { family: 'KaTeX_Size4', file: 'KaTeX_Size4-Regular.woff2', style: 'normal', weight: 'normal' },
  { family: 'KaTeX_AMS', file: 'KaTeX_AMS-Regular.woff2', style: 'normal', weight: 'normal' },
  {
    family: 'KaTeX_Caligraphic',
    file: 'KaTeX_Caligraphic-Regular.woff2',
    style: 'normal',
    weight: 'normal',
  },
  {
    family: 'KaTeX_SansSerif',
    file: 'KaTeX_SansSerif-Regular.woff2',
    style: 'normal',
    weight: 'normal',
  },
  {
    family: 'KaTeX_Typewriter',
    file: 'KaTeX_Typewriter-Regular.woff2',
    style: 'normal',
    weight: 'normal',
  },
]

let fontsInitialized = false

/**
 * 从后端 API 基础地址推导 HTTPS 静态字体目录；非 HTTPS（如本地 127.0.0.1）返回 `null`。
 */
export function resolveKatexFontBaseUrl(apiBaseUrl: string = API_BASE_URL): string | null {
  const match = /^(https:\/\/[^/]+)/i.exec(apiBaseUrl.trim())
  if (!match) return null
  return `${match[1]}/static/fonts/katex`
}

/**
 * 在小程序启动时静默加载 KaTeX 核心字体（幂等、异步、绝不抛错）。
 */
export function initKatexFonts(apiBaseUrl: string = API_BASE_URL): void {
  if (fontsInitialized) return
  try {
    if (typeof wx === 'undefined' || !wx) return
    const wxHost = wx as unknown as WxFontHost
    if (typeof wxHost.loadFontFace !== 'function') return

    const baseUrl = resolveKatexFontBaseUrl(apiBaseUrl)
    if (!baseUrl) return

    fontsInitialized = true
    for (const font of KATEX_CORE_FONTS) {
      try {
        wxHost.loadFontFace({
          global: true,
          family: font.family,
          source: `url("${baseUrl}/${font.file}")`,
          desc: { style: font.style, weight: font.weight },
          fail: () => {},
        })
      } catch {
        // 单个字体注册失败不影响其余字体与正文降级渲染
      }
    }
  } catch {
    // 静默兜底，绝不阻塞 App.onLaunch
  }
}

export function resetKatexFontsForTest(): void {
  fontsInitialized = false
}
