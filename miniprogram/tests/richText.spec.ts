import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import CoachMessageList from '@/components/CoachMessageList.vue'
import RichContent from '@/components/RichContent.vue'
import {
  escapeHtml,
  isGarbledSnippetText,
  parseMathToNodes,
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
    expect(isGarbledSnippetText('样本集合包含 ħx1, ħx2, ..., ħxm 等向量')).toBe(true)
    expect(isGarbledSnippetText('集合公式 x \uf0ce A')).toBe(true)
    expect(isGarbledSnippetText('降维操作说明。\n1, xi\n2, ..., xi\nm\nm\nn\nd\nX')).toBe(true)
    expect(isGarbledSnippetText('正常数学表达式 $$P(Y=c_k) = \\frac{1}{2}$$ 与 **重点**')).toBe(false)
    expect(isGarbledSnippetText('Python 判断 `a !== b` 与 ***分隔***')).toBe(false)
    expect(isGarbledSnippetText('```python\nX =\na\nb\nc\nd\n```\n正常说明')).toBe(false)
    expect(isGarbledSnippetText('')).toBe(false)
    expect(isGarbledSnippetText(null)).toBe(false)
  })

  it('gently unwraps mid-sentence CJK PDF hard wraps while preserving markdown blocks', () => {
    const raw = [
      '### 核心内容',
      '降维的目的就是降低数据的维度从而方便后续对数据的存储、可',
      '视化、',
      '建模等操作。',
      '第二段说明。',
      '',
      '- 列表第一项',
      '$$x^2 + y^2 = r^2$$',
    ].join('\n')
    const nodes = parseRichContent(raw)
    expect(nodes[0]).toMatchObject({ name: 'div', attrs: { class: 'rt-h rt-h3' } })
    expect(nodes[1]).toMatchObject({ name: 'p', attrs: { class: 'rt-p' } })
    const paraText = flattenText([nodes[1]])
    expect(paraText).toContain('存储、可视化、建模等操作。')
    expect(paraText).toContain('第二段说明。')
    // 句末句号后的换行应保留 <br>，而行中可/视化、建模等操作不应产生多余 <br>
    const pChildren = (nodes[1] as RichTextElementNode).children ?? []
    expect(pChildren.filter((child) => 'name' in child && child.name === 'br')).toHaveLength(1)
    expect(nodes[2]).toMatchObject({ name: 'div', attrs: { class: 'rt-list' } })
    expect(nodes[3]).toMatchObject({ name: 'div', attrs: { class: 'rt-math-block' } })
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

  it('uses tightened heading sizes and passes compact prop in CoachMessageList assistant bubbles', () => {
    const h1 = parseRichContent('# 标题1')[0]
    const h2 = parseRichContent('## 标题2')[0]
    const h3 = parseRichContent('### 标题3')[0]
    const h4 = parseRichContent('#### 标题4')[0]

    expect('attrs' in h1 && h1.attrs?.style).toContain('font-size:1.10em;')
    expect('attrs' in h2 && h2.attrs?.style).toContain('font-size:1.06em;')
    expect('attrs' in h3 && h3.attrs?.style).toContain('font-size:1.03em;')
    expect('attrs' in h4 && h4.attrs?.style).toContain('font-size:1.0em;')

    const coachWrapper = mount(CoachMessageList, {
      props: {
        isThinking: false,
        messages: [
          { id: 'u1', role: 'user', content: '用大白话解释一下' },
          { id: 'a1', role: 'assistant', content: '**核心结论**：先看边界条件。' },
        ],
      },
      global: {
        stubs: {
          'scroll-view': { template: '<div><slot /></div>' },
          'rich-text': { template: '<div class="stub-rich-text" />' },
        },
      },
    })

    const richContents = coachWrapper.findAllComponents(RichContent)
    expect(richContents).toHaveLength(1)
    expect(richContents[0].props('compact')).toBe(true)
    coachWrapper.unmount()
  })
})

function findAll(nodes: RichTextNode[], name: string): RichTextElementNode[] {
  const found: RichTextElementNode[] = []
  for (const node of nodes) {
    if ('name' in node) {
      if (node.name === name) found.push(node)
      if (node.children) found.push(...findAll(node.children, name))
    }
  }
  return found
}

function cellTexts(rowNodes: RichTextElementNode[]): string[] {
  return rowNodes.map((row) => (row.children ?? []).map((cell) => flattenText([cell])))
    .map((cells) => cells.join('|'))
}

describe('richText GFM pipe tables', () => {
  const TABLE_MD = [
    '| 方法 | 复杂度 | 说明 |',
    '| :--- | :---: | ---: |',
    '| **快排** | $O(n\\log n)$ | 平均 |',
    '| 冒泡 | $O(n^2)$ | 最坏 |',
  ].join('\n')

  it('renders thead/tbody with th/td inside a horizontally scrollable wrapper', () => {
    const nodes = parseRichContent(TABLE_MD)
    expect(nodes).toHaveLength(1)
    expect(nodes[0]).toMatchObject({ name: 'div', attrs: { class: 'rt-table-wrap' } })
    expect((nodes[0] as RichTextElementNode).attrs?.style).toContain('overflow-x:auto')

    expect(findAll(nodes, 'table')).toHaveLength(1)
    expect(findAll(nodes, 'thead')).toHaveLength(1)
    expect(findAll(nodes, 'tbody')).toHaveLength(1)
    expect(findAll(nodes, 'th')).toHaveLength(3)
    expect(findAll(nodes, 'td')).toHaveLength(6)
    expect(findAll(nodes, 'tr')).toHaveLength(3)
    expect(flattenText(findAll(nodes, 'th'))).toBe('方法复杂度说明')
  })

  it('applies column alignment from the separator row and inline styles to every cell', () => {
    const nodes = parseRichContent(TABLE_MD)
    const headStyles = findAll(nodes, 'th').map((cell) => cell.attrs?.style ?? '')
    expect(headStyles[0]).toContain('text-align:left;')
    expect(headStyles[1]).toContain('text-align:center;')
    expect(headStyles[2]).toContain('text-align:right;')
    for (const cell of [...findAll(nodes, 'th'), ...findAll(nodes, 'td')]) {
      expect(cell.attrs?.style).toContain('padding:')
      expect(cell.attrs?.style).toContain('border:')
    }
    const rows = findAll(nodes, 'tbody')[0].children as RichTextElementNode[]
    const stripedCell = (rows[1].children?.[0] ?? { name: '' }) as RichTextElementNode
    expect(stripedCell.name).toBe('td')
    expect(stripedCell.attrs?.style).toContain('background:rgb(')
  })

  it('parses inline markdown and math inside cells', () => {
    const nodes = parseRichContent(TABLE_MD)
    const tags = collectTagNames(nodes)
    expect(tags).toContain('strong')
    expect(tags).toContain('sup')
    const bodyRows = findAll(findAll(nodes, 'tbody'), 'tr')
    expect(cellTexts(bodyRows)[0]).toContain('快排')
    expect(cellTexts(bodyRows)[0]).toContain('O(nlog n)')
  })

  it('keeps pipes inside math/code/escapes and converts <br> in cells', () => {
    const md = [
      '| 表达式 | 备注 |',
      '| --- | --- |',
      '| $|x| \\ge 0$ | 绝对值 |',
      '| `a | b` | 管道 |',
      '| a \\| b | 第一行<br>第二行 |',
    ].join('\n')
    const nodes = parseRichContent(md)
    const rows = findAll(findAll(nodes, 'tbody'), 'tr')
    expect(rows).toHaveLength(3)
    for (const row of rows) expect(row.children).toHaveLength(2)
    expect(cellTexts(rows)[0]).toContain('|x| ≥ 0')
    expect(cellTexts(rows)[1]).toContain('a | b')
    expect(cellTexts(rows)[2]).toContain('a | b')
    expect(collectTagNames(rows[2].children ?? [])).toContain('br')
    expect(flattenText(nodes)).not.toContain('&lt;br')
  })

  it('supports tables without outer pipes, pads short rows, truncates long rows', () => {
    const md = ['a | b | c', '--|--|--', '1 | 2', '1 | 2 | 3 | 4'].join('\n')
    const rows = findAll(findAll(parseRichContent(md), 'tbody'), 'tr')
    expect(rows).toHaveLength(2)
    expect(rows[0].children).toHaveLength(3)
    expect(rows[1].children).toHaveLength(3)
    expect(flattenText([rows[0]])).toBe('12')
  })

  it('splits surrounding paragraphs and stops at the first non-table line', () => {
    const md = ['结论如下：', TABLE_MD, '', '表后段落 | 保持纯文本'].join('\n')
    const nodes = parseRichContent(md)
    expect(nodes.map((node) => ('name' in node ? node.name : 'text'))).toEqual(['p', 'div', 'p'])
    expect(flattenText([nodes[2]])).toBe('表后段落 | 保持纯文本')
  })

  it('does not treat pipe text without a separator row as a table', () => {
    const nodes = parseRichContent('P(Y=c_k | X=x_j) 与 a | b\n--- 分隔 ---')
    expect(findAll(nodes, 'table')).toHaveLength(0)
    expect(nodes[0]).toMatchObject({ name: 'p' })
  })

  it('escapes HTML inside table cells', () => {
    const nodes = parseRichContent(['| h |', '| --- |', '| <b>x</b> |'].join('\n'))
    expect(flattenText(findAll(nodes, 'td'))).toBe('&lt;b&gt;x&lt;/b&gt;')
  })
})

describe('richText LaTeX environments', () => {
  const assertNoLeak = (nodes: RichTextNode[]): void => {
    const text = flattenText(nodes)
    expect(text).not.toContain('begin')
    expect(text).not.toContain('end{')
    expect(text).not.toContain('\\')
    expect(text).not.toContain('&amp;')
  }

  it('renders pmatrix as a 2x2 grid with paren delimiters', () => {
    const nodes = parseRichContent(String.raw`$$\begin{pmatrix} a & b \\ c & d \end{pmatrix}$$`)
    expect(nodes[0]).toMatchObject({ attrs: { class: 'rt-math-block' } })
    expect(findAll(nodes, 'table')).toHaveLength(1)
    expect(findAll(nodes, 'tr')).toHaveLength(2)
    expect(findAll(nodes, 'td')).toHaveLength(4)
    expect(flattenText(findAll(nodes, 'td'))).toBe('abcd')
    expect(findAll(nodes, 'span').find((n) => n.attrs?.class?.includes('rt-math-matrix'))?.attrs?.style)
      .toContain('border-radius')
    assertNoLeak(nodes)
  })

  it('distinguishes bmatrix / vmatrix delimiters and plain matrix', () => {
    const style = (env: string): string => {
      const nodes = parseRichContent(String.raw`$$\begin{${env}} 1 & 0 \\ 0 & 1 \end{${env}}$$`)
      return findAll(nodes, 'span').find((n) => n.attrs?.class?.includes('rt-math-env'))?.attrs?.style ?? ''
    }
    expect(style('bmatrix')).toContain('border-left:2px solid')
    expect(style('vmatrix')).toContain('border-left:1px solid')
    expect(style('matrix')).not.toContain('border-left')
    expect(style('bmatrix')).not.toBe(style('vmatrix'))
    expect(style('Vmatrix')).toContain('double')
  })

  it('renders cases with a left brace and left-aligned cells', () => {
    const nodes = parseRichContent(
      String.raw`$$f(x)=\begin{cases} x^2 & x>0 \\ 0 & \text{otherwise} \end{cases}$$`,
    )
    expect(findAll(nodes, 'tr')).toHaveLength(2)
    expect(findAll(nodes, 'td')).toHaveLength(4)
    const wrapper = findAll(nodes, 'span').find((n) => n.attrs?.class?.includes('rt-math-cases'))
    expect(wrapper?.attrs?.style).toContain('border-left:2px solid')
    expect(wrapper?.attrs?.style).not.toContain('border-right')
    expect(findAll(nodes, 'td')[0].attrs?.style).toContain('text-align:left')
    const text = flattenText(nodes)
    expect(text).toContain('f(x)=')
    expect(text).toContain('x&gt;0')
    expect(text).toContain('otherwise')
    expect(collectTagNames(nodes)).toContain('sup')
    assertNoLeak(nodes)
  })

  it('aligns aligned rows on & with right/left alternating columns', () => {
    const nodes = parseRichContent(
      String.raw`$$\begin{aligned} a &= b + c \\ &= d \end{aligned}$$`,
    )
    const rows = findAll(nodes, 'tr')
    expect(rows).toHaveLength(2)
    expect(rows[0].children).toHaveLength(2)
    expect(rows[1].children).toHaveLength(2)
    const cells = findAll(nodes, 'td')
    expect(cells[0].attrs?.style).toContain('text-align:right')
    expect(cells[1].attrs?.style).toContain('text-align:left')
    expect(flattenText([rows[1]])).toBe('= d')
    assertNoLeak(nodes)
  })

  it('handles multi-line fenced environments, trailing row breaks, and \\\\[pt] spacing', () => {
    const md = [
      '$$',
      String.raw`\begin{bmatrix}`,
      String.raw`1 & 2 \\[4pt]`,
      String.raw`3 & 4 \\`,
      String.raw`\end{bmatrix}`,
      '$$',
    ].join('\n')
    const nodes = parseRichContent(md)
    expect(findAll(nodes, 'tr')).toHaveLength(2)
    expect(flattenText(findAll(nodes, 'td'))).toBe('1234')
    assertNoLeak(nodes)
  })

  it('renders bare (unfenced) environment lines as math blocks', () => {
    const md = [
      '结果为：',
      String.raw`\begin{aligned}`,
      String.raw`x &= 1 \\`,
      String.raw`y &= 2`,
      String.raw`\end{aligned}`,
      '完毕',
    ].join('\n')
    const nodes = parseRichContent(md)
    expect(nodes.map((node) => ('attrs' in node ? node.attrs?.class : ''))).toEqual([
      'rt-p',
      'rt-math-block',
      'rt-p',
    ])
    expect(findAll(nodes, 'tr')).toHaveLength(2)
    assertNoLeak(nodes)
  })

  it('renders inline $...$ environments and nested environments', () => {
    const inline = parseRichContent(String.raw`矩阵 $A=\begin{pmatrix}1\\2\end{pmatrix}$ 的列向量`)
    expect(findAll(inline, 'td')).toHaveLength(2)
    expect(flattenText(inline)).toContain('A=')
    expect(flattenText(inline)).toContain('的列向量')
    assertNoLeak(inline)

    const nested = parseMathToNodes(
      String.raw`\begin{pmatrix} \begin{pmatrix}1&2\\3&4\end{pmatrix} & 0 \\ 0 & 1 \end{pmatrix}`,
    )
    expect(findAll(nested, 'table')).toHaveLength(2)
    expect(findAll(nested, 'tr')).toHaveLength(4)
    assertNoLeak(nested)
  })

  it('reads array column alignment and tolerates unknown or unterminated environments', () => {
    const arr = parseMathToNodes(String.raw`\begin{array}{lr} 1 & 2 \\ 30 & 40 \end{array}`)
    const cells = findAll(arr, 'td')
    expect(cells[0].attrs?.style).toContain('text-align:left')
    expect(cells[1].attrs?.style).toContain('text-align:right')
    expect(flattenText(arr)).toBe('1230' + '40')

    const unknown = parseMathToNodes(String.raw`\begin{foo} x + y \end{foo}`)
    expect(flattenText(unknown)).toBe(' x + y ')

    const truncated = parseMathToNodes(String.raw`\begin{pmatrix} 1 & 2 \\ 3 & 4`)
    expect(findAll(truncated, 'td')).toHaveLength(4)
    assertNoLeak(truncated)
  })

  it('turns a stray \\\\ outside environments into a line break', () => {
    const nodes = parseMathToNodes(String.raw`a = 1 \\ b = 2`)
    expect(collectTagNames(nodes)).toContain('br')
    expect(flattenText(nodes)).toBe('a = 1  b = 2')
  })
})

const TABLE_FOR_STYLE = ['| a | b |', '| --- | --- |', '| 1 | 2 |'].join('\n')

describe('richText extended LaTeX commands', () => {
  const text = (expr: string): string => flattenText(parseMathToNodes(expr))

  it('applies accents with combining marks or overline spans', () => {
    expect(text(String.raw`\hat{x}`)).toBe('x\u0302')
    expect(text(String.raw`\hat{\theta}`)).toBe('θ\u0302')
    expect(text(String.raw`\bar{x}`)).toBe('x\u0304')
    expect(text(String.raw`\vec{v}`)).toBe('v\u20D7')
    expect(text(String.raw`\tilde y`)).toBe('y\u0303')
    const multi = parseMathToNodes(String.raw`\overline{AB}`)
    expect(findAll(multi, 'span')[0].attrs?.style).toContain('text-decoration:overline')
    expect(flattenText(multi)).toBe('AB')
  })

  it('renders operator names upright with scripts attached', () => {
    expect(text(String.raw`\det(A)`)).toBe('det(A)')
    expect(text(String.raw`\sin\theta + \cos 2x`)).toBe('sin θ + cos 2x')
    expect(text(String.raw`\log_2 n`)).toBe('log2 n')
    expect(text(String.raw`\ln x = \exp(y)`)).toBe('ln x = exp(y)')
    expect(text(String.raw`\tan x`)).toBe('tan x')
    expect(text(String.raw`\arg\max_{\theta} \min_x`)).toBe('arg maxθ minx')
    expect(collectTagNames(parseMathToNodes(String.raw`\lim_{x \to 0}`))).toContain('sub')
    expect(text(String.raw`\lim_{x \to 0} \frac{\sin x}{x}`)).toBe('limx → 0 (sin x)/(x)')
  })

  it('renders binom as a stacked paren grid', () => {
    const nodes = parseMathToNodes(String.raw`\binom{n}{k}`)
    expect(findAll(nodes, 'tr')).toHaveLength(2)
    expect(flattenText(nodes)).toBe('nk')
    expect(findAll(nodes, 'span')[0].attrs?.style).toContain('border-radius')
  })

  it('maps mathbb to double-struck glyphs', () => {
    expect(text(String.raw`\mathbb{R}^n`)).toBe('ℝn')
    expect(collectTagNames(parseMathToNodes(String.raw`\mathbb{R}^n`))).toContain('sup')
    expect(text(String.raw`\mathbb{N}, \mathbb Z, \mathbb{Q}`)).toBe('ℕ, ℤ, ℚ')
    expect(text(String.raw`\mathbb{E}`)).toBe(String.fromCodePoint(0x1d53c))
  })

  it('supports sqrt with optional index and unbraced operands', () => {
    const cube = parseMathToNodes(String.raw`\sqrt[3]{x}`)
    expect(flattenText(cube)).toBe('3√(x)')
    expect(findAll(cube, 'sup')).toHaveLength(1)
    expect(text(String.raw`\sqrt[n]{x+1}`)).toBe('n√(x+1)')
    expect(text(String.raw`\sqrt{a^2 + b^2}`)).toBe('√(a2 + b2)')
    expect(text(String.raw`\sqrt2`)).toBe('√2')
  })

  it('recognises extended commands inline in prose and ignores \\left./\\right.', () => {
    const nodes = parseRichContent(String.raw`令 $\hat{y}=\arg\max_k p_k$，且 \mathbb{R}`)
    const out = flattenText(nodes)
    expect(out).toContain('y\u0302=arg maxk')
    expect(out).toContain('ℝ')
    expect(text(String.raw`\left. x \right|_{0}`)).toBe(' x |0')
  })

  it('stays backward compatible for existing symbols, fractions, and plain pipes', () => {
    expect(text(String.raw`\alpha + \beta \le \gamma`)).toBe('α + β ≤ γ')
    expect(text(String.raw`\frac{a}{b}`)).toBe('(a)/(b)')
    expect(text(String.raw`\text{if } x \in A`)).toBe('if  x ∈ A')
    expect(text(String.raw`\unknowncmd`)).toBe('unknowncmd')
    expect(flattenText(parseRichContent('普通段落 a | b | c'))).toBe('普通段落 a | b | c')
  })

  it('never emits bare hex colors or emoji in generated styles', () => {
    const nodes = parseRichContent(
      [
        TABLE_FOR_STYLE,
        String.raw`$$\begin{cases} 1 & x>0 \\ 0 & \text{else} \end{cases}$$`,
      ].join('\n\n'),
    )
    const styles: string[] = []
    const walk = (list: RichTextNode[]): void => {
      for (const node of list) {
        if ('name' in node) {
          if (node.attrs?.style) styles.push(node.attrs.style)
          if (node.children) walk(node.children)
        }
      }
    }
    walk(nodes)
    expect(styles.length).toBeGreaterThan(5)
    for (const style of styles) {
      expect(style).not.toMatch(/#[0-9a-fA-F]{3,8}\b/)
      expect(style).not.toContain('var(')
    }
  })
})
