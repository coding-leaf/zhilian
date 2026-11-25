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
    const classes = findAll(nodes, 'span')
      .flatMap((n) => (n.attrs?.class ? n.attrs.class.split(/\s+/) : []))
    expect(classes).toContain('katex')
    expect(classes).toContain('mfrac')
    expect(classes).toContain('msupsub')

    const text = flattenText(nodes)
    expect(text).toContain('∝')
    expect(text).toContain('∏')
    expect(text).toContain('α')
    expect(text).toContain('Σ')
    expect(text).not.toContain('\\frac')

    const inlineFormula = parseRichContent(
      String.raw`计算 $P(Y=c_k | X=x_j)$ 且 $x_{i}^{2}，\sum \le \ge \ne \approx \in \times \cdot$`,
    )
    const inlineText = flattenText(inlineFormula)
    expect(inlineText).toContain('∑')
    expect(inlineText).toContain('≤')
    expect(inlineText).toContain('≥')
    expect(inlineText).toContain('=')
    expect(inlineText).toContain('≈')
    expect(inlineText).toContain('∈')
    expect(inlineText).toContain('×')
    expect(inlineText).toContain('⋅')
  })

  it('escapes HTML entities safely and converts sqrt', () => {
    const nodes = parseRichContent('<script>alert("xss")</script> 且 a < b & c > d')
    const text = flattenText(nodes)
    expect(text).toContain('&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;')
    expect(text).toContain('a &lt; b &amp; c &gt; d')
    expect(escapeHtml("a'b")).toBe('a&#39;b')

    const mathNodes = parseMathToNodes(String.raw`\sqrt{a^2 + b^2}`)
    expect(findAll(mathNodes, 'img').some((img) => img.attrs?.class === 'katex-svg')).toBe(true)
    expect(flattenText(mathNodes)).toContain('a2+b2')
  })

  it('detects legacy SymbolMT garbled snippet soup without false positives on normal math', () => {
    expect(isGarbledSnippetText('!"\n!"!#" =\n!"#!#!#\n#AB#BAB !=')).toBe(true)
    expect(isGarbledSnippetText('AB&A&\nAB&A&\nB&\n"#$"$\n!" ! #')).toBe(true)
    expect(isGarbledSnippetText('样本集合包含 ħx1, ħx2, ..., ħxm 等向量')).toBe(true)
    expect(isGarbledSnippetText('集合公式 x \uf0ce A')).toBe(true)
    expect(isGarbledSnippetText('降维操作说明。\n1, xi\n2, ..., xi\nm\nm\nn\nd\nX')).toBe(true)
    expect(isGarbledSnippetText('目标函数包含 ☒_{i=1}^n 约束')).toBe(true)
    expect(isGarbledSnippetText('包含损坏替换符 \ufffd 的切片')).toBe(true)
    expect(isGarbledSnippetText('缺失字形豆腐块 ▯ 测试')).toBe(true)
    expect(isGarbledSnippetText('软间隔约束 C □ ξ_i ≥ 0')).toBe(true)
    expect(isGarbledSnippetText('求和公式 □_{i=1}^n x_i = 0')).toBe(true)
    expect(isGarbledSnippetText('矩阵运算 a + ■ b 与 f(◇) = 0')).toBe(true)
    expect(isGarbledSnippetText('变量替换 □x_1 + 1')).toBe(true)
    expect(isGarbledSnippetText('正常数学表达式 $$P(Y=c_k) = \\frac{1}{2}$$ 与 **重点**')).toBe(false)
    expect(isGarbledSnippetText('$$\\sum_{i=1}^n \\xi_i + \\frac{1}{2}\\|w\\|^2$$')).toBe(false)
    expect(isGarbledSnippetText('| 概念 | 公式 |\n| --- | --- |\n| 间隔 | $y(w^Tx+b)/\\|w\\|$ |')).toBe(false)
    expect(isGarbledSnippetText('- ☐ 完成第一章复习\n- □ 整理错题\n- ■ 1. 线性可分\n- ◆ A. 基础概念')).toBe(false)
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
    expect(findAll(nodes, 'span').some((n) => n.attrs?.class?.includes('katex'))).toBe(true)
    const bodyRows = findAll(findAll(nodes, 'tbody'), 'tr')
    expect(cellTexts(bodyRows)[0]).toContain('快排')
    expect(cellTexts(bodyRows)[0]).toContain('log')
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
    expect(cellTexts(rows)[0]).toContain('≥0')
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

describe('richText LaTeX environments via KaTeX', () => {
  const collectClasses = (nodes: RichTextNode[]): string[] =>
    findAll(nodes, 'span')
      .flatMap((n) => (n.attrs?.class ? n.attrs.class.split(/\s+/) : []))
      .filter(Boolean)

  const assertNoLeak = (nodes: RichTextNode[]): void => {
    const text = flattenText(nodes)
    expect(text).not.toContain('\\begin')
    expect(text).not.toContain('\\end{')
    expect(text).not.toContain('&amp;')
  }

  it('renders pmatrix as a KaTeX mtable with paren delimiters', () => {
    const nodes = parseRichContent(String.raw`$$\begin{pmatrix} a & b \\ c & d \end{pmatrix}$$`)
    expect(nodes[0]).toMatchObject({ attrs: { class: 'rt-math-block' } })
    const classes = collectClasses(nodes)
    expect(classes).toContain('mtable')
    expect(classes).toContain('mopen')
    expect(classes).toContain('mclose')
    expect(flattenText(nodes)).toContain('a')
    expect(flattenText(nodes)).toContain('d')
    assertNoLeak(nodes)
  })

  it('distinguishes bmatrix / vmatrix / Vmatrix delimiters and plain matrix', () => {
    const delimText = (env: string): string => {
      const nodes = parseRichContent(String.raw`$$\begin{${env}} 1 & 0 \\ 0 & 1 \end{${env}}$$`)
      const delims = findAll(nodes, 'span').filter(
        (n) => n.attrs?.class?.includes('mopen') || n.attrs?.class?.includes('mclose'),
      )
      return flattenText(delims).replace(/\u200b/g, '')
    }
    expect(delimText('bmatrix')).toContain('[')
    expect(
      findAll(parseRichContent(String.raw`$$\begin{vmatrix} 1 & 0 \\ 0 & 1 \end{vmatrix}$$`), 'img').length,
    ).toBeGreaterThanOrEqual(2)
    expect(
      findAll(parseRichContent(String.raw`$$\begin{Vmatrix} 1 & 0 \\ 0 & 1 \end{Vmatrix}$$`), 'img').length,
    ).toBeGreaterThanOrEqual(2)
    expect(delimText('matrix')).toBe('')
  })

  it('renders cases with left brace and cells', () => {
    const nodes = parseRichContent(
      String.raw`$$f(x)=\begin{cases} x^2 & x>0 \\ 0 & \text{otherwise} \end{cases}$$`,
    )
    expect(collectClasses(nodes)).toContain('mtable')
    const text = flattenText(nodes)
    expect(text).toContain('f(x)=')
    expect(text).toContain('x&gt;0')
    expect(text).toContain('otherwise')
    assertNoLeak(nodes)
  })

  it('renders aligned environments cleanly without leaking commands', () => {
    const nodes = parseRichContent(
      String.raw`$$\begin{aligned} a &= b + c \\ &= d \end{aligned}$$`,
    )
    expect(collectClasses(nodes)).toContain('mtable')
    const text = flattenText(nodes).replace(/\u200b/g, '')
    expect(text).toContain('a=b+c')
    expect(text).toContain('=d')
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
    expect(collectClasses(nodes)).toContain('mtable')
    expect(flattenText(nodes)).toContain('1')
    expect(flattenText(nodes)).toContain('4')
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
    expect(collectClasses([nodes[1]])).toContain('mtable')
    assertNoLeak(nodes)
  })

  it('renders inline $...$ environments and nested environments', () => {
    const inline = parseRichContent(String.raw`矩阵 $A=\begin{pmatrix}1\\2\end{pmatrix}$ 的列向量`)
    expect(collectClasses(inline)).toContain('mtable')
    expect(flattenText(inline)).toContain('A=')
    expect(flattenText(inline)).toContain('的列向量')
    assertNoLeak(inline)

    const nested = parseMathToNodes(
      String.raw`\begin{pmatrix} \begin{pmatrix}1&2\\3&4\end{pmatrix} & 0 \\ 0 & 1 \end{pmatrix}`,
    )
    expect(collectClasses(nested).filter((c) => c === 'mtable').length).toBeGreaterThanOrEqual(2)
    assertNoLeak(nested)
  })

  it('reads array column alignment and tolerates unknown or unterminated environments', () => {
    const arr = parseMathToNodes(String.raw`\begin{array}{lr} 1 & 2 \\ 30 & 40 \end{array}`)
    expect(collectClasses(arr)).toContain('mtable')
    expect(flattenText(arr)).toContain('30')
    expect(flattenText(arr)).toContain('40')

    const unknown = parseMathToNodes(String.raw`\begin{foo} x + y \end{foo}`)
    expect(collectClasses(unknown)).toContain('katex-error')

    const truncated = parseMathToNodes(String.raw`\begin{pmatrix} 1 & 2 \\ 3 & 4`)
    expect(collectClasses(truncated)).toContain('katex-error')
  })

  it('supports \\\\ line breaks inside KaTeX display math', () => {
    const nodes = parseMathToNodes(String.raw`a = 1 \\ b = 2`, true)
    expect(collectClasses(nodes)).toContain('katex-display')
    expect(flattenText(nodes)).toContain('a=1')
    expect(flattenText(nodes)).toContain('b=2')
  })
})

const TABLE_FOR_STYLE = ['| a | b |', '| --- | --- |', '| 1 | 2 |'].join('\n')

describe('richText extended LaTeX commands via KaTeX', () => {
  const text = (expr: string): string => flattenText(parseMathToNodes(expr))
  const classes = (expr: string): string[] =>
    findAll(parseMathToNodes(expr), 'span')
      .flatMap((n) => (n.attrs?.class ? n.attrs.class.split(/\s+/) : []))
      .filter(Boolean)

  it('renders accents and overline with KaTeX accent/overline classes', () => {
    expect(classes(String.raw`\hat{x}`)).toContain('accent')
    expect(classes(String.raw`\hat{\theta}`)).toContain('accent')
    expect(classes(String.raw`\bar{x}`)).toContain('accent')
    expect(classes(String.raw`\vec{v}`)).toContain('accent')
    expect(classes(String.raw`\tilde y`)).toContain('accent')
    expect(classes(String.raw`\overline{AB}`)).toContain('overline')
    expect(text(String.raw`\overline{AB}`)).toContain('AB')
  })

  it('renders operator names upright with scripts attached', () => {
    expect(text(String.raw`\det(A)`)).toContain('det(A)')
    expect(text(String.raw`\sin\theta + \cos 2x`)).toContain('sinθ+cos2x')
    expect(text(String.raw`\log_2 n`)).toContain('log2​n')
    expect(text(String.raw`\ln x = \exp(y)`)).toContain('lnx=exp(y)')
    expect(classes(String.raw`\arg\max_{\theta} \min_x`)).toContain('mop')
    expect(classes(String.raw`\lim_{x \to 0} \frac{\sin x}{x}`)).toContain('mfrac')
  })

  it('renders binom via KaTeX mfrac', () => {
    const nodes = parseMathToNodes(String.raw`\binom{n}{k}`)
    expect(findAll(nodes, 'span').some((n) => n.attrs?.class?.includes('mfrac'))).toBe(true)
    expect(flattenText(nodes)).toContain('n')
    expect(flattenText(nodes)).toContain('k')
  })

  it('renders mathbb with KaTeX mathbb class', () => {
    expect(classes(String.raw`\mathbb{R}^n`)).toContain('mathbb')
    expect(text(String.raw`\mathbb{R}^n`)).toContain('Rn')
    expect(text(String.raw`\mathbb{N}, \mathbb Z, \mathbb{Q}`)).toContain('N,Z,Q')
  })

  it('supports sqrt with optional index and unbraced operands as SVG img', () => {
    const cube = parseMathToNodes(String.raw`\sqrt[3]{x}`)
    expect(findAll(cube, 'img').some((img) => img.attrs?.class === 'katex-svg')).toBe(true)
    expect(flattenText(cube)).toContain('3')
    expect(flattenText(cube)).toContain('x')
    expect(findAll(parseMathToNodes(String.raw`\sqrt2`), 'img').length).toBeGreaterThan(0)
  })

  it('recognises extended commands inline in prose and handles \\left./\\right.', () => {
    const nodes = parseRichContent(String.raw`令 $\hat{y}=\arg\max_k p_k$，且 $\mathbb{R}$`)
    const out = flattenText(nodes)
    expect(out).toContain('令 ')
    expect(out).toContain('argmax')
    expect(out).toContain('R')
    expect(text(String.raw`\left. x \right|_{0}`)).toContain('x∣0')
  })

  it('renders symbols, fractions, and plain pipes safely', () => {
    expect(text(String.raw`\alpha + \beta \le \gamma`)).toBe('α+β≤γ')
    expect(classes(String.raw`\frac{a}{b}`)).toContain('mfrac')
    expect(text(String.raw`\text{if } x \in A`).replace(/\u00a0/g, ' ')).toContain('if x∈A')
    expect(
      findAll(parseMathToNodes(String.raw`\unknowncmd`), 'span').some((n) =>
        n.attrs?.style?.includes('color:rgb(185,28,28)'),
      ),
    ).toBe(true)
    expect(flattenText(parseRichContent('普通段落 a | b | c'))).toBe('普通段落 a | b | c')
  })

  it('never emits bare hex colors or emoji in generated styles', () => {
    const nodes = parseRichContent(
      [
        TABLE_FOR_STYLE,
        String.raw`$$\begin{cases} 1 & x>0 \\ 0 & \text{else} \end{cases}$$`,
        String.raw`$$\unknowncmd$$`,
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
