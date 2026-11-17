import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import RichContent from '@/components/RichContent.vue'
import {
  escapeHtml,
  isGarbledSnippetText,
  parseMathToNodes,
  parseRichContent,
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

function collectTagNames(nodes: RichTextNode[]): string[] {
  const tags: string[] = []
  for (const node of nodes) {
    if ('name' in node) {
      tags.push(node.name)
      if (node.children) tags.push(...collectTagNames(node.children))
    }
  }
  return tags
}

describe('richText AST parser', () => {
  it('returns empty array for null, undefined, or blank strings', () => {
    expect(parseRichContent(null)).toEqual([])
    expect(parseRichContent(undefined)).toEqual([])
    expect(parseRichContent('   \n  ')).toEqual([])
  })

  it('parses headings, multiline paragraphs, lists, blockquotes, and fenced code blocks', () => {
    const md = [
      '### 核心定理',
      '第一行内容',
      '第二行内容',
      '',
      '- **条件独立**：特征互不影响',
      '1. 先验概率统计',
      '',
      '> 引用提示：**注意边界**',
      '',
      '```python',
      'x = "**not bold**" < 10',
      '```',
    ].join('\n')

    const nodes = parseRichContent(md)
    expect(nodes[0]).toMatchObject({ name: 'div', attrs: { class: 'rt-h rt-h3' } })
    expect(nodes[1]).toMatchObject({ name: 'p', attrs: { class: 'rt-p' } })
    expect(collectTagNames([nodes[1]])).toContain('br')
    expect(nodes[2]).toMatchObject({ name: 'div', attrs: { class: 'rt-list' } })
    expect(nodes[3]).toMatchObject({ name: 'blockquote', attrs: { class: 'rt-quote' } })
    expect(nodes[4]).toMatchObject({ name: 'div', attrs: { class: 'rt-code-block' } })

    const codeText = flattenText([nodes[4]])
    expect(codeText).toContain('&lt; 10')
    expect(codeText).toContain('**not bold**')
    expect(collectTagNames([nodes[4]])).not.toContain('strong')
  })

  it('parses inline bold, italic, code, and avoids corrupting snake_case identifiers', () => {
    const nodes = parseRichContent('支持 **加粗**、*斜体*、`code_val` 与 single_choice_a')
    const tags = collectTagNames(nodes)
    expect(tags).toContain('strong')
    expect(tags).toContain('em')
    expect(tags).toContain('code')
    expect(tags).not.toContain('sub')
    expect(flattenText(nodes)).toContain('single_choice_a')
  })

  it('parses fenced and un-fenced math, subscripts, superscripts, fractions, Greek letters, and operators', () => {
    const expr = String.raw`$$P(Y=c_k | X=x_j) \propto P(Y=c_k) \prod_{j=1}^{n} \frac{\alpha + x_j^2}{\Sigma}$$`
    const nodes = parseRichContent(expr)
    expect(nodes[0]).toMatchObject({ name: 'div', attrs: { class: 'rt-math-block' } })
    const tags = collectTagNames(nodes)
    expect(tags).toContain('sub')
    expect(tags).toContain('sup')

    const text = flattenText(nodes)
    expect(text).toContain('∝')
    expect(text).toContain('∏')
    expect(text).toContain('(α + xj2)/(Σ)')

    const unfenced = parseRichContent('计算 P(Y=c_k | X=x_j) 且 x_{i}^{2}，\\sum \\le \\ge \\ne \\approx \\in \\times \\cdot')
    expect(collectTagNames(unfenced)).toContain('sub')
    expect(collectTagNames(unfenced)).toContain('sup')
    const unfencedText = flattenText(unfenced)
    expect(unfencedText).toContain('∑')
    expect(unfencedText).toContain('≤')
    expect(unfencedText).toContain('≥')
    expect(unfencedText).toContain('≠')
    expect(unfencedText).toContain('≈')
    expect(unfencedText).toContain('∈')
    expect(unfencedText).toContain('×')
    expect(unfencedText).toContain('·')
  })

  it('escapes HTML entities safely and converts sqrt', () => {
    const nodes = parseRichContent('<script>alert("xss")</script> 且 a < b & c > d')
    const text = flattenText(nodes)
    expect(text).toContain('&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;')
    expect(text).toContain('a &lt; b &amp; c &gt; d')
    expect(escapeHtml("a'b")).toBe('a&#39;b')

    const mathNodes = parseMathToNodes(String.raw`\sqrt{a^2 + b^2}`)
    expect(flattenText(mathNodes)).toContain('√(a2 + b2)')
    expect(collectTagNames(mathNodes)).toContain('sup')
  })

  it('detects legacy SymbolMT garbled snippet soup without false positives on normal math', () => {
    expect(isGarbledSnippetText('!"\n!"!#" =\n!"#!#!#\n#AB#BAB !=')).toBe(true)
    expect(isGarbledSnippetText('AB&A&\nAB&A&\nB&\n"#$"$\n!" ! #')).toBe(true)
    expect(isGarbledSnippetText('正常数学表达式 $$P(Y=c_k) = \\frac{1}{2}$$ 与 **重点**')).toBe(false)
    expect(isGarbledSnippetText('Python 判断 `a !== b` 与 ***分隔***')).toBe(false)
    expect(isGarbledSnippetText('')).toBe(false)
    expect(isGarbledSnippetText(null)).toBe(false)
  })
})

describe('RichContent component', () => {
  it('passes parsed AST nodes and typography classes to native rich-text', () => {
    const wrapper = mount(RichContent, {
      props: {
        content: '**贝叶斯** 公式 $x^2$',
        compact: true,
        muted: true,
      },
      global: {
        stubs: {
          'rich-text': {
            props: ['nodes', 'userSelect'],
            template: '<div class="stub-rich-text" :data-count="nodes.length" />',
          },
        },
      },
    })

    expect(wrapper.find('.rich-content.compact.muted').exists()).toBe(true)
    expect(wrapper.find('.stub-rich-text').attributes('data-count')).toBe('1')
    wrapper.unmount()
  })
})
