import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

const SRC_ROOT = path.resolve(__dirname, '../src')
const MANIFEST_PATH = path.resolve(SRC_ROOT, 'manifest.json')
const VITE_CONFIG_PATH = path.resolve(__dirname, '../vite.config.ts')

function walkFiles(dir: string, exts: Set<string>, out: string[] = []): string[] {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name)
    if (entry.isDirectory()) {
      walkFiles(full, exts, out)
    } else if (exts.has(path.extname(entry.name))) {
      out.push(full)
    }
  }
  return out
}

function rel(file: string): string {
  return path.relative(SRC_ROOT, file).replace(/\\/g, '/')
}

function stripComments(source: string): string {
  return source
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(^|[^:\\])\/\/[^\n]*/g, '$1')
}

describe('mp-weixin static compatibility guardrails', () => {
  const tsAndVueFiles = walkFiles(SRC_ROOT, new Set(['.ts', '.vue']))
  const styleFiles = walkFiles(SRC_ROOT, new Set(['.scss', '.css', '.vue']))
  const vueFiles = walkFiles(SRC_ROOT, new Set(['.vue']))

  it('forbids dynamic import() in miniprogram/src (breaks mp-weixin CJS build)', () => {
    const hits: string[] = []
    for (const file of tsAndVueFiles) {
      const content = stripComments(fs.readFileSync(file, 'utf8'))
      if (/\bimport\s*\(/.test(content)) {
        hits.push(rel(file))
      }
    }
    expect(hits).toEqual([])
  })

  it('forbids HTTP PATCH method in miniprogram/src (unsupported by wx.request)', () => {
    const hits: string[] = []
    for (const file of tsAndVueFiles) {
      const content = stripComments(fs.readFileSync(file, 'utf8'))
      if (/method\s*:\s*['"]PATCH['"]|['"]PATCH['"]/.test(content)) {
        hits.push(rel(file))
      }
    }
    expect(hits).toEqual([])
  })

  it('forbids deprecated uni.chooseImage (use uni.chooseMedia)', () => {
    const hits: string[] = []
    for (const file of tsAndVueFiles) {
      const content = stripComments(fs.readFileSync(file, 'utf8'))
      if (/\b(?:uni|wx)\.chooseImage\b/.test(content)) {
        hits.push(rel(file))
      }
    }
    expect(hits).toEqual([])
  })

  it('forbids Web-only globals and Unicode property escapes \\p{...} in miniprogram/src', () => {
    const webGlobalRe =
      /\b(?:window|document|localStorage|sessionStorage|URLSearchParams|AbortController|structuredClone)\b/
    const unicodePropRe = /\\p\{/
    const hits: string[] = []
    for (const file of tsAndVueFiles) {
      const content = fs.readFileSync(file, 'utf8')
      // Only inspect script sections for .vue files to avoid false matches in prose/template text
      const scriptOnly = stripComments(
        file.endsWith('.vue')
          ? (content.match(/<script[\s\S]*?<\/script>/g) || []).join('\n')
          : content,
      )
      if (webGlobalRe.test(scriptOnly)) {
        hits.push(`${rel(file)}:web-global`)
      }
      if (unicodePropRe.test(scriptOnly)) {
        hits.push(`${rel(file)}:unicode-prop-regex`)
      }
    }
    expect(hits).toEqual([])
  })

  it('forbids unsupported WXSS selectors ([disabled], :deep(, universal *, local url())', () => {
    const hits: string[] = []
    for (const file of styleFiles) {
      const raw = fs.readFileSync(file, 'utf8')
      const css = file.endsWith('.vue')
        ? (raw.match(/<style[\s\S]*?<\/style>/g) || []).join('\n')
        : raw
      if (!css) continue
      if (/\[disabled\]/.test(css)) hits.push(`${rel(file)}:[disabled]`)
      if (/:deep\(|::v-deep/.test(css)) hits.push(`${rel(file)}::deep`)
      if (/(?:^|[},\s])\*\s*\{/m.test(css)) hits.push(`${rel(file)}:universal-*`)
      if (/url\(\s*['"]?(?!https?:|data:)/i.test(css)) hits.push(`${rel(file)}:local-url`)
    }
    expect(hits).toEqual([])
  })

  it('requires every <button :loading="..."> to also bind :disabled', () => {
    const hits: string[] = []
    for (const file of vueFiles) {
      const raw = fs.readFileSync(file, 'utf8')
      const template = (raw.match(/<template[\s\S]*?<\/template>/) || [''])[0]
      const buttonTags = template.match(/<button\b[\s\S]*?>/g) || []
      for (const tag of buttonTags) {
        if (/:loading\s*=/.test(tag) && !/:disabled\s*=/.test(tag)) {
          hits.push(`${rel(file)}:${tag.replace(/\s+/g, ' ').slice(0, 80)}`)
        }
      }
    }
    expect(hits).toEqual([])
  })

  it('enforces manifest.json privacy, lazyCodeLoading, enhance, and <=60000ms networkTimeout', () => {
    const manifest = JSON.parse(fs.readFileSync(MANIFEST_PATH, 'utf8'))
    const mp = manifest['mp-weixin']
    expect(mp.__usePrivacyCheck__).toBe(true)
    expect(mp.lazyCodeLoading).toBe('requiredComponents')
    expect(mp.setting?.enhance).toBe(true)
    expect(mp.networkTimeout?.request).toBeLessThanOrEqual(60000)
    expect(mp.networkTimeout?.uploadFile).toBeLessThanOrEqual(60000)

    const viteConfig = fs.readFileSync(VITE_CONFIG_PATH, 'utf8')
    expect(viteConfig).toMatch(/target\s*:\s*['"]es2018['"]/)
  })
})
