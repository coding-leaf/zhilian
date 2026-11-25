import { afterEach, describe, expect, it, vi } from 'vitest'
import katex from 'katex'
import { renderKatexToNodes } from '@/utils/katexRichText'
import {
  initKatexFonts,
  resetKatexFontsForTest,
  resolveKatexFontBaseUrl,
} from '@/utils/katexFonts'
import {
  parseRichContent,
  type RichTextElementNode,
  type RichTextNode,
} from '@/utils/richText'

function flattenText(nodes: RichTextNode[]): string {
  return nodes
    .map((node) => {
      if ('type' in node && node.type === 'text') return node.text
      if ('children' in node && node.children) return flattenText(node.children)
      return ''
    })
    .join('')
}

function collectElements(nodes: RichTextNode[]): RichTextElementNode[] {
  const out: RichTextElementNode[] = []
  for (const node of nodes) {
    if ('name' in node) {
      out.push(node)
      if (node.children) out.push(...collectElements(node.children))
    }
  }
  return out
}

function collectClasses(nodes: RichTextNode[]): string[] {
  return collectElements(nodes)
    .flatMap((el) => (el.attrs?.class ? el.attrs.class.split(/\s+/) : []))
    .filter(Boolean)
}

describe('katexRichText AST adapter & Image 4 regressions', () => {
  it('renders Image 4 SVM dual problem \\[...\\] at line start, mid-line, list item, multi-line, and with trailing 。', () => {
    const svmExpr = String.raw`\min_{\vec{\alpha}} \frac{1}{2} \sum_{i=1}^{m} \sum_{j=1}^{m} \alpha_i \alpha_j y_i y_j \phi(\vec{x}_i)^T \phi(\vec{x}_j) - \sum_{i=1}^{m} \alpha_i`

    const blockNodes = parseRichContent(`\\[ ${svmExpr} \\]`)
    expect(blockNodes[0]).toMatchObject({ name: 'div', attrs: { class: 'rt-math-block' } })
    expect((blockNodes[0] as RichTextElementNode).attrs?.style).toContain('overflow-x:auto')
    const blockClasses = collectClasses(blockNodes)
    expect(blockClasses).toContain('katex-display')
    expect(blockClasses).toContain('katex')
    expect(blockClasses).toContain('mfrac')
    expect(flattenText(blockNodes)).not.toContain('\\[')
    expect(flattenText(blockNodes)).not.toContain('\\]')
    expect(flattenText(blockNodes)).not.toContain('\\frac')

    const trailingPunctNodes = parseRichContent(`\\[ ${svmExpr} \\]。`)
    expect(trailingPunctNodes[0]).toMatchObject({ name: 'div', attrs: { class: 'rt-math-block' } })
    expect(collectClasses(trailingPunctNodes)).toContain('katex')
    expect(flattenText(trailingPunctNodes)).toContain('。')
    expect(flattenText(trailingPunctNodes)).not.toContain('\\]')

    const inlineMidLine = parseRichContent(`对偶优化目标为：\\[ ${svmExpr} \\]，求解即可。`)
    expect(collectClasses(inlineMidLine)).toContain('katex-display')
    expect(flattenText(inlineMidLine)).toContain('对偶优化目标为：')
    expect(flattenText(inlineMidLine)).toContain('求解即可。')
    expect(flattenText(inlineMidLine)).not.toContain('\\[')

    const listWithBracket = parseRichContent(`- 对偶目标：\\[ ${svmExpr} \\]`)
    expect(listWithBracket[0]).toMatchObject({ name: 'div', attrs: { class: 'rt-list' } })
    expect(collectClasses(listWithBracket)).toContain('katex-display')
    expect(flattenText(listWithBracket)).not.toContain('\\[')

    const multiLine = parseRichContent(['\\[', svmExpr, '\\]。'].join('\n'))
    expect(multiLine[0]).toMatchObject({ name: 'div', attrs: { class: 'rt-math-block' } })
    expect(collectClasses(multiLine)).toContain('katex')
    expect(flattenText(multiLine)).not.toContain('\\[')
  })

  it('renders inline hyperplane formula, preserves soft-wrapped math, and handles \\$ and $5/$10 currency', () => {
    const inlineNodes = parseRichContent(String.raw`划分超平面 $\vec{w}^T \vec{x} + b = 0$ 将样本分开`)
    expect(collectClasses(inlineNodes)).toContain('katex')
    const flat = flattenText(inlineNodes)
    expect(flat).toContain('划分超平面 ')
    expect(flat).toContain('w')
    expect(flat).toContain('x')
    expect(flat).toContain('b')
    expect(flat).not.toContain('$')

    const softWrapped = parseRichContent('划分超平面 $w^T x +\nb = 0$ 且有 $x_i * y_i + a_1$')
    expect(collectClasses(softWrapped)).toContain('katex')
    expect(collectElements(softWrapped).filter((el) => el.name === 'em')).toHaveLength(0)
    const wrappedFlat = flattenText(softWrapped)
    expect(wrappedFlat).toContain('w')
    expect(wrappedFlat).toContain('b')
    expect(wrappedFlat).not.toContain('$')

    const escapedCurrency = parseRichContent(String.raw`成本 \$5，满足 $w^T x + b = 0$`)
    const escapedFlat = flattenText(escapedCurrency)
    expect(escapedFlat).toContain('成本 $5，满足 ')
    expect(escapedFlat).toContain('w')
    expect(collectClasses(escapedCurrency)).toContain('katex')

    const englishCurrency = parseRichContent('Items cost $5 and $10 respectively.')
    expect(collectClasses(englishCurrency)).not.toContain('katex')
    expect(flattenText(englishCurrency)).toBe('Items cost $5 and $10 respectively.')

    const chineseCurrency = parseRichContent('成本 $5 和 $10 的两本书，售价 $5，公式 $x + y = 1$')
    expect(flattenText(chineseCurrency)).toContain('$5 和 $10')
    expect(flattenText(chineseCurrency)).toContain('售价 $5')
    expect(collectClasses(chineseCurrency)).toContain('katex')
  })

  it('renders SvgNode (\\sqrt, \\overrightarrow, \\cancel) as properly encoded data-URI <img> nodes', () => {
    for (const expr of [
      String.raw`\sqrt{x^2 + y^2}`,
      String.raw`\sqrt[3]{a+b}`,
      String.raw`\overrightarrow{AB}`,
      String.raw`\cancel{x}`,
    ]) {
      const nodes = renderKatexToNodes(expr, false)
      const imgs = collectElements(nodes).filter((el) => el.name === 'img')
      expect(imgs.length).toBeGreaterThan(0)
      for (const img of imgs) {
        expect(img.attrs?.class).toBe('katex-svg')
        const src = img.attrs?.src ?? ''
        expect(src.startsWith('data:image/svg+xml;charset=utf-8,')).toBe(true)
        expect(src).toContain('xmlns=%22http://www.w3.org/2000/svg%22')
        expect(src.slice('data:image/svg+xml;charset=utf-8,'.length)).not.toMatch(/[#<>"]/)
      }
    }
  })

  it('renders pmatrix, cases, bare environments, and ```latex fenced blocks', () => {
    const pmatrixNodes = parseRichContent(String.raw`$$\begin{pmatrix} 1 & 2 \\ 3 & 4 \end{pmatrix}$$`)
    expect(pmatrixNodes[0]).toMatchObject({ name: 'div', attrs: { class: 'rt-math-block' } })
    expect(collectClasses(pmatrixNodes)).toContain('mtable')
    expect(flattenText(pmatrixNodes)).not.toContain('\\begin')

    const casesNodes = parseRichContent(
      String.raw`$$f(x)=\begin{cases} x^2, & x \ge 0 \\ -x, & x < 0 \end{cases}$$`,
    )
    expect(collectClasses(casesNodes)).toContain('mtable')
    expect(flattenText(casesNodes)).toContain('f(x)=')

    const bareEnv = parseRichContent(
      ['推导如下：', String.raw`\begin{aligned}`, String.raw`x &= 1 \\`, String.raw`y &= 2`, String.raw`\end{aligned}`].join('\n'),
    )
    expect(bareEnv[0]).toMatchObject({ name: 'p', attrs: { class: 'rt-p' } })
    expect(bareEnv[1]).toMatchObject({ name: 'div', attrs: { class: 'rt-math-block' } })
    expect(collectClasses([bareEnv[1]])).toContain('mtable')

    const fencedLatex = parseRichContent(
      ['```latex', String.raw`\[ \frac{\partial L}{\partial w} = \sum_{i=1}^{m} \alpha_i y_i x_i = 0 \]`, '```'].join('\n'),
    )
    expect(fencedLatex[0]).toMatchObject({ name: 'div', attrs: { class: 'rt-math-block' } })
    expect(collectClasses(fencedLatex)).toContain('mfrac')
  })

  it('handles malformed or truncated LaTeX and unexpected render errors without throwing or emitting hex colors', () => {
    for (const bad of [
      String.raw`\frac{1}{`,
      String.raw`\min_{\vec{\alpha`,
      String.raw`\begin{pmatrix} 1 & 2`,
      'x ☒ y \ufffd z',
    ]) {
      expect(() => renderKatexToNodes(bad, true)).not.toThrow()
      const nodes = renderKatexToNodes(bad, true)
      expect(nodes.length).toBeGreaterThan(0)
      for (const el of collectElements(nodes)) {
        if (el.attrs?.style) {
          expect(el.attrs.style).not.toMatch(/#[0-9a-fA-F]{3,8}\b/)
        }
      }
    }

    const spy = vi
      .spyOn(katex as unknown as { __renderToDomTree: () => unknown }, '__renderToDomTree')
      .mockImplementationOnce(() => {
        throw new Error('simulated boom')
      })
    const fallback = renderKatexToNodes('x^2 + y^2', false)
    spy.mockRestore()
    expect(fallback[0]).toMatchObject({ name: 'span', attrs: { class: 'katex-fallback' } })
    expect(flattenText(fallback)).toContain('x^2 + y^2')
  })
})

describe('katexFonts loader', () => {
  afterEach(() => {
    resetKatexFontsForTest()
    vi.unstubAllGlobals()
  })

  it('derives HTTPS static font base URL and skips non-HTTPS origins', () => {
    expect(resolveKatexFontBaseUrl('https://api.zhilian.edu.cn/api/v1')).toBe(
      'https://api.zhilian.edu.cn/static/fonts/katex',
    )
    expect(resolveKatexFontBaseUrl('http://127.0.0.1:8000/api/v1')).toBeNull()
    expect(resolveKatexFontBaseUrl('/api/v1')).toBeNull()
  })

  it('is a silent no-op without wx host or on HTTP dev URLs, and loads core fonts on HTTPS wx host', () => {
    expect(() => initKatexFonts('https://api.zhilian.edu.cn/api/v1')).not.toThrow()

    const loadFontFace = vi.fn()
    vi.stubGlobal('wx', { loadFontFace })

    initKatexFonts('http://127.0.0.1:8000/api/v1')
    expect(loadFontFace).not.toHaveBeenCalled()

    initKatexFonts('https://api.zhilian.edu.cn/api/v1')
    expect(loadFontFace).toHaveBeenCalled()
    expect(loadFontFace.mock.calls[0][0]).toMatchObject({
      global: true,
      family: 'KaTeX_Main',
      source: 'url("https://api.zhilian.edu.cn/static/fonts/katex/KaTeX_Main-Regular.woff2")',
    })

    // 幂等性校验：重复调用不再重复注册
    const countAfterFirst = loadFontFace.mock.calls.length
    initKatexFonts('https://api.zhilian.edu.cn/api/v1')
    expect(loadFontFace.mock.calls.length).toBe(countAfterFirst)
  })
})
