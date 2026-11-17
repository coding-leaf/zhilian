/**
 * 零依赖 Markdown + LaTeX/数学公式 AST 编译器，面向微信小程序原生 `<rich-text :nodes>`。
 *
 * 注意：小程序 `<rich-text>` 节点内联 style 无法可靠解析 `var(--color-*)` 自定义属性，
 * 且工程规范禁止在 `App.vue` 之外使用裸 Hex 字面量，因此颜色全部采用语义一致的 `rgb(...)` / `rgba(...)`。
 */

export interface RichTextTextNode {
  type: 'text'
  text: string
}

export interface RichTextElementNode {
  name: string
  attrs?: Record<string, string>
  children?: RichTextNode[]
}

export type RichTextNode = RichTextElementNode | RichTextTextNode

const STYLES = {
  headingBase: 'font-weight:700;color:rgb(28,25,23);line-height:1.4;margin:10rpx 0 6rpx;',
  paragraph: 'margin:0 0 8rpx 0;line-height:1.55;word-break:break-word;',
  list: 'margin:4rpx 0 8rpx 0;',
  listItem: 'display:flex;align-items:flex-start;margin:3rpx 0;line-height:1.55;word-break:break-word;',
  listMarker: 'color:rgb(30,58,138);font-weight:700;margin-right:10rpx;flex-shrink:0;',
  listContent: 'flex:1;min-width:0;word-break:break-word;',
  quote: 'margin:8rpx 0;padding:10rpx 14rpx;background:rgb(248,250,252);border-left:5rpx solid rgb(30,58,138);color:rgb(71,85,105);border-radius:0 8rpx 8rpx 0;line-height:1.55;',
  codeBlock: 'margin:8rpx 0;padding:12rpx 14rpx;background:rgb(245,245,244);border:1px solid rgb(231,229,228);border-radius:10rpx;overflow-x:auto;',
  codeBlockInner: 'font-family:monospace;font-size:22rpx;line-height:1.5;color:rgb(51,65,85);white-space:pre-wrap;word-break:break-all;',
  inlineCode: 'font-family:monospace;font-size:0.9em;padding:2rpx 8rpx;margin:0 4rpx;background:rgb(245,245,244);color:rgb(30,58,138);border-radius:6rpx;',
  mathBlock: 'margin:10rpx 0;padding:12rpx 16rpx;background:rgb(239,246,255);border:1px solid rgb(191,219,254);border-radius:10rpx;color:rgb(28,25,23);line-height:1.6;word-break:break-word;',
  mathInline: 'color:rgb(30,58,138);font-weight:500;',
  strong: 'font-weight:700;color:rgb(28,25,23);',
  em: 'font-style:italic;',
  sub: 'font-size:0.74em;vertical-align:sub;line-height:1;',
  sup: 'font-size:0.74em;vertical-align:super;line-height:1;',
} as const

const HEADING_SIZES: Record<number, string> = {
  1: 'font-size:1.10em;',
  2: 'font-size:1.06em;',
  3: 'font-size:1.03em;',
  4: 'font-size:1.0em;',
}

const LATEX_SYMBOL_MAP: Record<string, string> = {
  alpha: 'α',
  beta: 'β',
  gamma: 'γ',
  delta: 'δ',
  epsilon: 'ε',
  varepsilon: 'ε',
  zeta: 'ζ',
  eta: 'η',
  theta: 'θ',
  vartheta: 'ϑ',
  iota: 'ι',
  kappa: 'κ',
  lambda: 'λ',
  mu: 'μ',
  nu: 'ν',
  xi: 'ξ',
  pi: 'π',
  varpi: 'ϖ',
  rho: 'ρ',
  varrho: 'ϱ',
  sigma: 'σ',
  varsigma: 'ς',
  tau: 'τ',
  upsilon: 'υ',
  phi: 'φ',
  varphi: 'φ',
  chi: 'χ',
  psi: 'ψ',
  omega: 'ω',
  Gamma: 'Γ',
  Delta: 'Δ',
  Theta: 'Θ',
  Lambda: 'Λ',
  Xi: 'Ξ',
  Pi: 'Π',
  Sigma: 'Σ',
  Phi: 'Φ',
  Psi: 'Ψ',
  Omega: 'Ω',
  sum: '∑',
  prod: '∏',
  int: '∫',
  partial: '∂',
  nabla: '∇',
  infty: '∞',
  propto: '∝',
  le: '≤',
  leq: '≤',
  ge: '≥',
  geq: '≥',
  ne: '≠',
  neq: '≠',
  approx: '≈',
  equiv: '≡',
  sim: '~',
  simeq: '≃',
  cong: '≅',
  in: '∈',
  notin: '∉',
  subset: '⊂',
  subseteq: '⊆',
  supset: '⊃',
  supseteq: '⊇',
  cup: '∪',
  cap: '∩',
  emptyset: '∅',
  times: '×',
  cdot: '·',
  div: '÷',
  pm: '±',
  mp: '∓',
  circ: '∘',
  to: '→',
  rightarrow: '→',
  leftarrow: '←',
  leftrightarrow: '↔',
  Rightarrow: '⇒',
  Leftrightarrow: '⇔',
  forall: '∀',
  exists: '∃',
  neg: '¬',
  land: '∧',
  lor: '∨',
  therefore: '∴',
  because: '∵',
  ldots: '…',
  cdots: '…',
  dots: '…',
}

const STRIP_WRAPPER_COMMANDS = new Set([
  'text',
  'mathrm',
  'mathbf',
  'mathit',
  'mathcal',
  'operatorname',
  'boldsymbol',
])

const IGNORED_COMMANDS = new Set(['left', 'right', 'limits', 'nolimits', 'quad', 'qquad'])

export function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function makeText(raw: string): RichTextTextNode {
  return { type: 'text', text: escapeHtml(raw) }
}

function pushText(nodes: RichTextNode[], raw: string): void {
  if (!raw) return
  const escaped = escapeHtml(raw)
  const last = nodes[nodes.length - 1]
  if (last && 'type' in last && last.type === 'text') {
    last.text += escaped
    return
  }
  nodes.push({ type: 'text', text: escaped })
}

function readBraceGroup(src: string, openIdx: number): { content: string; nextIdx: number } | null {
  if (src[openIdx] !== '{') return null
  let depth = 0
  for (let i = openIdx; i < src.length; i += 1) {
    const ch = src[i]
    if (ch === '\\' && i + 1 < src.length) {
      i += 1
      continue
    }
    if (ch === '{') depth += 1
    else if (ch === '}') {
      depth -= 1
      if (depth === 0) {
        return { content: src.slice(openIdx + 1, i), nextIdx: i + 1 }
      }
    }
  }
  return null
}

function readScriptOperand(src: string, startIdx: number): { content: string; nextIdx: number } | null {
  let idx = startIdx
  while (idx < src.length && src[idx] === ' ') idx += 1
  if (idx >= src.length) return null
  if (src[idx] === '{') return readBraceGroup(src, idx)
  if (src[idx] === '\\') {
    const cmdMatch = /^\\[a-zA-Z]+/.exec(src.slice(idx))
    if (cmdMatch) return { content: cmdMatch[0], nextIdx: idx + cmdMatch[0].length }
  }
  return { content: src[idx], nextIdx: idx + 1 }
}

function consumeLatexCommand(src: string, idx: number, out: RichTextNode[]): number {
  const rest = src.slice(idx)
  const spaceCmd = /^\\[,;:!\s]/.exec(rest)
  if (spaceCmd) {
    pushText(out, spaceCmd[0] === '\\!' ? '' : ' ')
    return idx + spaceCmd[0].length
  }
  const escapedChar = /^\\([{}|%$&_#])/.exec(rest)
  if (escapedChar) {
    pushText(out, escapedChar[1] === '|' ? '||' : escapedChar[1])
    return idx + escapedChar[0].length
  }
  const cmdMatch = /^\\([a-zA-Z]+)/.exec(rest)
  if (!cmdMatch) {
    pushText(out, src[idx])
    return idx + 1
  }
  const cmd = cmdMatch[1]
  let cursor = idx + cmdMatch[0].length

  if (cmd === 'frac' || cmd === 'dfrac' || cmd === 'tfrac') {
    while (cursor < src.length && src[cursor] === ' ') cursor += 1
    const numGroup = readBraceGroup(src, cursor)
    if (numGroup) {
      let denCursor = numGroup.nextIdx
      while (denCursor < src.length && src[denCursor] === ' ') denCursor += 1
      const denGroup = readBraceGroup(src, denCursor)
      if (denGroup) {
        pushText(out, '(')
        out.push(...parseMathToNodes(numGroup.content))
        pushText(out, ')/(')
        out.push(...parseMathToNodes(denGroup.content))
        pushText(out, ')')
        return denGroup.nextIdx
      }
    }
  }

  if (cmd === 'sqrt') {
    while (cursor < src.length && src[cursor] === ' ') cursor += 1
    const inner = readBraceGroup(src, cursor)
    if (inner) {
      pushText(out, '√(')
      out.push(...parseMathToNodes(inner.content))
      pushText(out, ')')
      return inner.nextIdx
    }
  }

  if (STRIP_WRAPPER_COMMANDS.has(cmd)) {
    while (cursor < src.length && src[cursor] === ' ') cursor += 1
    const inner = readBraceGroup(src, cursor)
    if (inner) {
      out.push(...parseMathToNodes(inner.content))
      return inner.nextIdx
    }
  }

  if (IGNORED_COMMANDS.has(cmd)) {
    return cursor
  }

  if (LATEX_SYMBOL_MAP[cmd]) {
    pushText(out, LATEX_SYMBOL_MAP[cmd])
    return cursor
  }

  pushText(out, cmd)
  return cursor
}

export function parseMathToNodes(expr: string): RichTextNode[] {
  const out: RichTextNode[] = []
  let i = 0
  while (i < expr.length) {
    const ch = expr[i]
    if (ch === '\\') {
      i = consumeLatexCommand(expr, i, out)
      continue
    }
    if ((ch === '_' || ch === '^') && i + 1 < expr.length) {
      const operand = readScriptOperand(expr, i + 1)
      if (operand) {
        const tagName = ch === '_' ? 'sub' : 'sup'
        const style = ch === '_' ? STYLES.sub : STYLES.sup
        out.push({
          name: tagName,
          attrs: { class: `rt-${tagName}`, style },
          children: parseMathToNodes(operand.content),
        })
        i = operand.nextIdx
        continue
      }
    }
    if (ch === '{' || ch === '}') {
      i += 1
      continue
    }
    pushText(out, ch)
    i += 1
  }
  return mergeAdjacentText(out)
}

function mergeAdjacentText(nodes: RichTextNode[]): RichTextNode[] {
  const merged: RichTextNode[] = []
  for (const node of nodes) {
    const prev = merged[merged.length - 1]
    if (
      'type' in node
      && node.type === 'text'
      && prev
      && 'type' in prev
      && prev.type === 'text'
    ) {
      prev.text += node.text
    } else {
      merged.push(node)
    }
  }
  return merged
}

function isLikelyInlineDollarMath(inner: string): boolean {
  const trimmed = inner.trim()
  if (!trimmed) return false
  // 排除类似 "$5 和 $10" 的中文货币句误判
  if (/^\d+(?:\.\d+)?\s+[\u4e00-\u9fff]/.test(trimmed)) return false
  return true
}

function consumeAttachedScripts(line: string, startIdx: number, out: RichTextNode[]): number {
  let cursor = startIdx
  while (cursor < line.length && (line[cursor] === '_' || line[cursor] === '^')) {
    const ch = line[cursor]
    const operand = readScriptOperand(line, cursor + 1)
    if (!operand) break
    const tagName = ch === '_' ? 'sub' : 'sup'
    const style = ch === '_' ? STYLES.sub : STYLES.sup
    out.push({
      name: tagName,
      attrs: { class: `rt-${tagName}`, style },
      children: parseMathToNodes(operand.content),
    })
    cursor = operand.nextIdx
  }
  return cursor
}

function tryConsumeUnfencedScript(line: string, idx: number, out: RichTextNode[]): number {
  const slice = line.slice(idx)
  const bracedSub = /^([A-Za-z0-9)\]])_\{([^}]+)\}/.exec(slice)
  if (bracedSub) {
    pushText(out, bracedSub[1])
    out.push({
      name: 'sub',
      attrs: { class: 'rt-sub', style: STYLES.sub },
      children: parseMathToNodes(bracedSub[2]),
    })
    return consumeAttachedScripts(line, idx + bracedSub[0].length, out)
  }

  const bracedSup = /^([A-Za-z0-9)\]])\^\{([^}]+)\}/.exec(slice)
  if (bracedSup) {
    pushText(out, bracedSup[1])
    out.push({
      name: 'sup',
      attrs: { class: 'rt-sup', style: STYLES.sup },
      children: parseMathToNodes(bracedSup[2]),
    })
    return consumeAttachedScripts(line, idx + bracedSup[0].length, out)
  }

  const prevChar = idx > 0 ? line[idx - 1] : ''
  const isWordPrefix = /[A-Za-z0-9_]/.test(prevChar)
  if (!isWordPrefix) {
    const shortSub = /^([A-Za-z])_([A-Za-z0-9]{1,2})(?![A-Za-z0-9_])/.exec(slice)
    if (shortSub) {
      pushText(out, shortSub[1])
      out.push({
        name: 'sub',
        attrs: { class: 'rt-sub', style: STYLES.sub },
        children: [makeText(shortSub[2])],
      })
      return consumeAttachedScripts(line, idx + shortSub[0].length, out)
    }
  }

  const shortSup = /^([A-Za-z0-9)\]])\^([A-Za-z0-9+-]{1,3})(?![A-Za-z0-9_])/.exec(slice)
  if (shortSup) {
    pushText(out, shortSup[1])
    out.push({
      name: 'sup',
      attrs: { class: 'rt-sup', style: STYLES.sup },
      children: [makeText(shortSup[2])],
    })
    return consumeAttachedScripts(line, idx + shortSup[0].length, out)
  }

  return -1
}

export function parseInline(line: string): RichTextNode[] {
  const out: RichTextNode[] = []
  let i = 0

  while (i < line.length) {
    const rest = line.slice(i)

    if (rest.startsWith('`')) {
      const codeMatch = /^`([^`\n]+)`/.exec(rest)
      if (codeMatch) {
        out.push({
          name: 'code',
          attrs: { class: 'rt-inline-code', style: STYLES.inlineCode },
          children: [makeText(codeMatch[1])],
        })
        i += codeMatch[0].length
        continue
      }
    }

    if (rest.startsWith('$$')) {
      const displayInline = /^\$\$([^\n]+?)\$\$/.exec(rest)
      if (displayInline) {
        out.push({
          name: 'span',
          attrs: { class: 'rt-math-inline', style: STYLES.mathInline },
          children: parseMathToNodes(displayInline[1]),
        })
        i += displayInline[0].length
        continue
      }
    }

    if (rest.startsWith('$') && !rest.startsWith('$$')) {
      const mathMatch = /^\$([^$\n]+?)\$/.exec(rest)
      if (mathMatch && isLikelyInlineDollarMath(mathMatch[1])) {
        out.push({
          name: 'span',
          attrs: { class: 'rt-math-inline', style: STYLES.mathInline },
          children: parseMathToNodes(mathMatch[1]),
        })
        i += mathMatch[0].length
        continue
      }
    }

    if (rest.startsWith('\\(')) {
      const parenMath = /^\\\(([^\n]+?)\\\)/.exec(rest)
      if (parenMath) {
        out.push({
          name: 'span',
          attrs: { class: 'rt-math-inline', style: STYLES.mathInline },
          children: parseMathToNodes(parenMath[1]),
        })
        i += parenMath[0].length
        continue
      }
    }

    if (rest.startsWith('**')) {
      const boldMatch = /^\*\*([^*\n]+?)\*\*/.exec(rest)
      if (boldMatch) {
        out.push({
          name: 'strong',
          attrs: { style: STYLES.strong },
          children: parseInline(boldMatch[1]),
        })
        i += boldMatch[0].length
        continue
      }
    }

    if (rest.startsWith('__') && (i === 0 || !/[A-Za-z0-9_]/.test(line[i - 1]))) {
      const boldUnder = /^__([^_\n]+?)__(?![A-Za-z0-9_])/.exec(rest)
      if (boldUnder) {
        out.push({
          name: 'strong',
          attrs: { style: STYLES.strong },
          children: parseInline(boldUnder[1]),
        })
        i += boldUnder[0].length
        continue
      }
    }

    if (rest.startsWith('*') && !rest.startsWith('**')) {
      const italicMatch = /^\*([^\s*\n](?:[^*\n]*?[^\s*\n])?)\*/.exec(rest)
      if (italicMatch) {
        out.push({
          name: 'em',
          attrs: { style: STYLES.em },
          children: parseInline(italicMatch[1]),
        })
        i += italicMatch[0].length
        continue
      }
    }

    if (rest.startsWith('\\')) {
      const latexCmd = /^\\(frac|dfrac|tfrac|sqrt|text|mathrm|mathbf|mathit|mathcal|operatorname|[a-zA-Z]+)/.exec(rest)
      if (
        latexCmd
        && (
          latexCmd[1] in LATEX_SYMBOL_MAP
          || STRIP_WRAPPER_COMMANDS.has(latexCmd[1])
          || IGNORED_COMMANDS.has(latexCmd[1])
          || ['frac', 'dfrac', 'tfrac', 'sqrt'].includes(latexCmd[1])
        )
      ) {
        const nextIdx = consumeLatexCommand(line, i, out)
        i = consumeAttachedScripts(line, nextIdx, out)
        continue
      }
    }

    const scriptNext = tryConsumeUnfencedScript(line, i, out)
    if (scriptNext !== -1) {
      i = scriptNext
      continue
    }

    pushText(out, line[i])
    i += 1
  }

  return mergeAdjacentText(out)
}

function buildMultilineChildren(lines: string[]): RichTextNode[] {
  const children: RichTextNode[] = []
  lines.forEach((line, idx) => {
    if (idx > 0) children.push({ name: 'br' })
    children.push(...parseInline(line))
  })
  return children
}

function isBlockStarter(line: string): boolean {
  const trimmed = line.trim()
  if (!trimmed) return true
  if (/^```/.test(trimmed)) return true
  if (/^\$\$/.test(trimmed) || /^\\\[/.test(trimmed)) return true
  if (/^#{1,4}\s+/.test(trimmed)) return true
  if (/^>\s?/.test(trimmed)) return true
  if (/^\s*[-*•]\s+/.test(line)) return true
  if (/^\s*\d+[.)]\s+/.test(line)) return true
  return false
}

export function parseRichContent(raw: string | null | undefined): RichTextNode[] {
  if (!raw || !raw.trim()) return []
  const lines = raw.replace(/\r\n/g, '\n').replace(/\r/g, '\n').split('\n')
  const nodes: RichTextNode[] = []
  let i = 0

  while (i < lines.length) {
    const line = lines[i]
    const trimmed = line.trim()

    if (!trimmed) {
      i += 1
      continue
    }

    if (/^```/.test(trimmed)) {
      const codeLines: string[] = []
      i += 1
      while (i < lines.length && !/^```\s*$/.test(lines[i].trim())) {
        codeLines.push(lines[i])
        i += 1
      }
      if (i < lines.length) i += 1
      const codeChildren: RichTextNode[] = []
      codeLines.forEach((codeLine, idx) => {
        if (idx > 0) codeChildren.push({ name: 'br' })
        codeChildren.push(makeText(codeLine))
      })
      nodes.push({
        name: 'div',
        attrs: { class: 'rt-code-block', style: STYLES.codeBlock },
        children: [{ name: 'code', attrs: { style: STYLES.codeBlockInner }, children: codeChildren }],
      })
      continue
    }

    if (trimmed.startsWith('$$') || trimmed.startsWith('\\[')) {
      const isBracket = trimmed.startsWith('\\[')
      const openMarker = isBracket ? '\\[' : '$$'
      const closeMarker = isBracket ? '\\]' : '$$'
      const afterOpen = trimmed.slice(openMarker.length)
      let mathExpr = ''
      if (afterOpen.endsWith(closeMarker) && afterOpen.length >= closeMarker.length) {
        mathExpr = afterOpen.slice(0, -closeMarker.length).trim()
        i += 1
      } else {
        const mathLines = afterOpen ? [afterOpen] : []
        i += 1
        while (i < lines.length) {
          const currentTrimmed = lines[i].trim()
          if (currentTrimmed.endsWith(closeMarker)) {
            const prefix = currentTrimmed.slice(0, -closeMarker.length).trim()
            if (prefix) mathLines.push(prefix)
            i += 1
            break
          }
          mathLines.push(lines[i])
          i += 1
        }
        mathExpr = mathLines.join(' ').trim()
      }
      nodes.push({
        name: 'div',
        attrs: { class: 'rt-math-block', style: STYLES.mathBlock },
        children: parseMathToNodes(mathExpr),
      })
      continue
    }

    const headingMatch = /^(#{1,4})\s+(.+)$/.exec(trimmed)
    if (headingMatch) {
      const level = headingMatch[1].length
      nodes.push({
        name: 'div',
        attrs: {
          class: `rt-h rt-h${level}`,
          style: `${STYLES.headingBase}${HEADING_SIZES[level] || HEADING_SIZES[4]}`,
        },
        children: parseInline(headingMatch[2].trim()),
      })
      i += 1
      continue
    }

    if (/^>\s?/.test(trimmed)) {
      const quoteLines: string[] = []
      while (i < lines.length && /^>\s?/.test(lines[i].trim())) {
        quoteLines.push(lines[i].trim().replace(/^>\s?/, ''))
        i += 1
      }
      nodes.push({
        name: 'blockquote',
        attrs: { class: 'rt-quote', style: STYLES.quote },
        children: buildMultilineChildren(quoteLines),
      })
      continue
    }

    if (/^\s*[-*•]\s+/.test(line) || /^\s*\d+[.)]\s+/.test(line)) {
      const listItems: RichTextNode[] = []
      while (i < lines.length) {
        const ulMatch = /^\s*[-*•]\s+(.+)$/.exec(lines[i])
        const olMatch = /^\s*(\d+)[.)]\s+(.+)$/.exec(lines[i])
        if (!ulMatch && !olMatch) break
        const marker = olMatch ? `${olMatch[1]}.` : '•'
        const itemText = olMatch ? olMatch[2] : ulMatch![1]
        listItems.push({
          name: 'div',
          attrs: { class: 'rt-li', style: STYLES.listItem },
          children: [
            { name: 'span', attrs: { style: STYLES.listMarker }, children: [makeText(marker)] },
            { name: 'span', attrs: { style: STYLES.listContent }, children: parseInline(itemText) },
          ],
        })
        i += 1
      }
      nodes.push({
        name: 'div',
        attrs: { class: 'rt-list', style: STYLES.list },
        children: listItems,
      })
      continue
    }

    const paraLines: string[] = []
    while (i < lines.length && !isBlockStarter(lines[i])) {
      paraLines.push(lines[i])
      i += 1
    }
    if (paraLines.length > 0) {
      nodes.push({
        name: 'p',
        attrs: { class: 'rt-p', style: STYLES.paragraph },
        children: buildMultilineChildren(paraLines),
      })
    } else {
      i += 1
    }
  }

  return nodes
}

const SYMBOL_SOUP_CLUSTER = /[!"#$%&'*=?@^~]{3,}/g
const SYMBOL_PAIR_CLUSTER = /[!"#$%&'*=?@^~]{2,}/g
const REPEATED_SAFE_TOKEN = /^(?:\*{3,}|={3,}|"{3,}|'{3,}|!={2,}|~{3,})$/
const SYMBOL_AMP_LINE = /(?:[A-Z]{1,2}&){2,}/

/**
 * 检测历史未重解析 PDF 切片是否残留 `SymbolMT` ASCII 符号乱码簇（如 `AB&A&`、`"#$"$`、`!"#!#`）。
 */
export function isGarbledSnippetText(text: string | null | undefined): boolean {
  if (!text || !text.trim()) return false
  const cleaned = text.replace(/\$\$/g, ' ').replace(/\*{3,}/g, ' ')
  const clusters = cleaned.match(SYMBOL_SOUP_CLUSTER) ?? []
  const suspicious = clusters.filter((token) => !REPEATED_SAFE_TOKEN.test(token))
  if (suspicious.length >= 1) return true

  if (SYMBOL_AMP_LINE.test(cleaned)) return true

  const pairs = (cleaned.match(SYMBOL_PAIR_CLUSTER) ?? []).filter(
    (token) => !REPEATED_SAFE_TOKEN.test(token),
  )
  if (pairs.length >= 3) {
    const nonSpace = cleaned.replace(/\s+/g, '')
    const symbolChars = (nonSpace.match(/[!"#$%&'*=?@^~]/g) ?? []).length
    if (nonSpace.length > 0 && symbolChars / nonSpace.length > 0.25) return true
  }
  return false
}
