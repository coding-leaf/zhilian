/**
 * Markdown + KaTeX AST 编译器，面向微信小程序原生 `<rich-text :nodes>`。
 *
 * 模块划分：
 * - `richTextCore.ts`：节点类型、内联样式表（`rgb(...)` 颜色，禁止裸 Hex）、转义与文本工具。
 * - `katexRichText.ts`：`katex.__renderToDomTree` -> `<rich-text>` AST 适配器。
 * - `richTextTable.ts`：GFM 管道表格解析。
 * - 本文件：公式定界符优先扫描、Markdown 块级/行内解析与乱码片段检测。
 */
import { renderKatexToNodes } from './katexRichText'
import {
  STYLES,
  makeText,
  mergeAdjacentText,
  pushText,
  type RichTextNode,
} from './richTextCore'
import { isTableStart, tryParseTable } from './richTextTable'

export { escapeHtml } from './richTextCore'
export type { RichTextElementNode, RichTextNode, RichTextTextNode } from './richTextCore'
export { renderKatexToNodes as parseMathToNodes } from './katexRichText'

const HEADING_SIZES: Record<number, string> = {
  1: 'font-size:1.10em;',
  2: 'font-size:1.06em;',
  3: 'font-size:1.03em;',
  4: 'font-size:1.0em;',
}

const KNOWN_MATH_ENVS = new Set([
  'aligned',
  'align',
  'align*',
  'gather',
  'gather*',
  'equation',
  'equation*',
  'split',
  'cases',
  'dcases',
  'rcases',
  'pmatrix',
  'bmatrix',
  'Bmatrix',
  'vmatrix',
  'Vmatrix',
  'matrix',
  'smallmatrix',
  'array',
  'eqnarray',
  'eqnarray*',
  'multline',
  'multline*',
  'subarray',
  'CD',
])

const LATEX_FENCE_LANGS = new Set(['latex', 'tex', 'math'])
const TRAILING_PUNCT_RE = /^[，。；：、,.!?;:）)]+$/

function hasEvenBackslashesBefore(text: string, idx: number): boolean {
  let count = 0
  for (let i = idx - 1; i >= 0 && text[i] === '\\'; i -= 1) {
    count += 1
  }
  return count % 2 === 0
}

function findUnescapedMarker(text: string, marker: string, startIdx = 0): number {
  let pos = startIdx
  while (pos <= text.length - marker.length) {
    const idx = text.indexOf(marker, pos)
    if (idx === -1) return -1
    if (hasEvenBackslashesBefore(text, idx)) {
      return idx
    }
    pos = idx + 1
  }
  return -1
}

function startsWithKnownEnvironment(text: string): string | null {
  const match = /^\\begin\{([A-Za-z*]+)\}/.exec(text.trim())
  if (!match) return null
  return KNOWN_MATH_ENVS.has(match[1]) ? match[1] : null
}

function isLikelyInlineDollarMath(inner: string): boolean {
  const trimmed = inner.trim()
  if (!trimmed) return false
  // 排除 "$5 and $10"、"$5 和 $10"、"$5，公式..." 等货币/自然语言误判
  if (
    /^\d+(?:,\d{3})*(?:\.\d+)?(?:\s*[\u4e00-\u9fff，。；：、]|\s+(?:and|or|to|vs|of|for|in|per|each)\b)/i.test(
      trimmed,
    )
  ) {
    return false
  }
  return true
}

function findClosingInlineDollar(text: string, openIdx: number): number {
  let pos = openIdx + 1
  while (pos < text.length) {
    const ch = text[pos]
    if (ch === '$' && hasEvenBackslashesBefore(text, pos)) {
      // 跳过形如 $10 的货币数字起点，避免将 "$5 and $10" 误判为数学公式
      const nextChar = text[pos + 1]
      if (nextChar === '$') {
        pos += 2
        continue
      }
      if (nextChar && /\d/.test(nextChar)) {
        pos += 1
        continue
      }
      const inner = text.slice(openIdx + 1, pos)
      if (isLikelyInlineDollarMath(inner)) {
        return pos
      }
      return -1
    }
    pos += 1
  }
  return -1
}

function makeMathBlockNode(expr: string): RichTextNode {
  return {
    name: 'div',
    attrs: { class: 'rt-math-block', style: STYLES.mathBlock },
    children: renderKatexToNodes(expr, true),
  }
}

function makeInlineDisplayMathNode(expr: string): RichTextNode {
  return {
    name: 'span',
    attrs: {
      class: 'rt-math-block',
      style: `${STYLES.mathBlock}display:block;`,
    },
    children: renderKatexToNodes(expr, true),
  }
}

function makeInlineMathNode(expr: string): RichTextNode {
  return {
    name: 'span',
    attrs: { class: 'rt-math-inline', style: STYLES.mathInline },
    children: renderKatexToNodes(expr, false),
  }
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
  return { content: src[idx], nextIdx: idx + 1 }
}

function makeScriptNode(tag: 'sub' | 'sup', content: string): RichTextNode {
  return {
    name: tag,
    attrs: { class: `rt-${tag}`, style: tag === 'sub' ? STYLES.sub : STYLES.sup },
    children: [makeText(content)],
  }
}

function consumeAttachedScripts(line: string, startIdx: number, out: RichTextNode[]): number {
  let cursor = startIdx
  while (cursor < line.length && (line[cursor] === '_' || line[cursor] === '^')) {
    const operand = readScriptOperand(line, cursor + 1)
    if (!operand) break
    out.push(makeScriptNode(line[cursor] === '_' ? 'sub' : 'sup', operand.content))
    cursor = operand.nextIdx
  }
  return cursor
}

function tryConsumeUnfencedScript(line: string, idx: number, out: RichTextNode[]): number {
  const slice = line.slice(idx)
  const bracedSub = /^([A-Za-z0-9)\]])_\{([^}]+)\}/.exec(slice)
  if (bracedSub) {
    pushText(out, bracedSub[1])
    out.push(makeScriptNode('sub', bracedSub[2]))
    return consumeAttachedScripts(line, idx + bracedSub[0].length, out)
  }

  const bracedSup = /^([A-Za-z0-9)\]])\^\{([^}]+)\}/.exec(slice)
  if (bracedSup) {
    pushText(out, bracedSup[1])
    out.push(makeScriptNode('sup', bracedSup[2]))
    return consumeAttachedScripts(line, idx + bracedSup[0].length, out)
  }

  const prevChar = idx > 0 ? line[idx - 1] : ''
  const isWordPrefix = /[A-Za-z0-9_]/.test(prevChar)
  if (!isWordPrefix) {
    const shortSub = /^([A-Za-z])_([A-Za-z0-9]{1,2})(?![A-Za-z0-9_])/.exec(slice)
    if (shortSub) {
      pushText(out, shortSub[1])
      out.push(makeScriptNode('sub', shortSub[2]))
      return consumeAttachedScripts(line, idx + shortSub[0].length, out)
    }
  }

  const shortSup = /^([A-Za-z0-9)\]])\^([A-Za-z0-9+-]{1,3})(?![A-Za-z0-9_])/.exec(slice)
  if (shortSup) {
    pushText(out, shortSup[1])
    out.push(makeScriptNode('sup', shortSup[2]))
    return consumeAttachedScripts(line, idx + shortSup[0].length, out)
  }

  return -1
}

/**
 * 行内解析：优先识别行内代码、转义 `\$` 与数学定界符（`$$...$$` / `\[...\]` / `$...$` / `\(...\)`），
 * 保护公式内部的 `_` / `*` 不被 Markdown 强调语法拆碎。
 */
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

    if (rest.startsWith('\\$')) {
      pushText(out, '$')
      i += 2
      continue
    }

    if (rest.startsWith('$$') && hasEvenBackslashesBefore(line, i)) {
      const closeIdx = findUnescapedMarker(rest, '$$', 2)
      if (closeIdx !== -1) {
        const expr = rest.slice(2, closeIdx)
        out.push(makeInlineDisplayMathNode(expr))
        i += closeIdx + 2
        continue
      }
    }

    if (rest.startsWith('\\[') && hasEvenBackslashesBefore(line, i)) {
      const closeIdx = findUnescapedMarker(rest, '\\]', 2)
      if (closeIdx !== -1) {
        const expr = rest.slice(2, closeIdx)
        out.push(makeInlineDisplayMathNode(expr))
        i += closeIdx + 2
        continue
      }
    }

    if (rest.startsWith('\\(') && hasEvenBackslashesBefore(line, i)) {
      const closeIdx = findUnescapedMarker(rest, '\\)', 2)
      if (closeIdx !== -1) {
        const expr = rest.slice(2, closeIdx)
        out.push(makeInlineMathNode(expr))
        i += closeIdx + 2
        continue
      }
    }

    if (rest.startsWith('$') && !rest.startsWith('$$') && hasEvenBackslashesBefore(line, i)) {
      const closeIdx = findClosingInlineDollar(rest, 0)
      if (closeIdx !== -1) {
        const expr = rest.slice(1, closeIdx)
        out.push(makeInlineMathNode(expr))
        i += closeIdx + 1
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

function unwrapCjkParaLines(paraLines: string[]): string[] {
  if (paraLines.length <= 1) return paraLines
  const merged: string[] = []
  for (const rawLine of paraLines) {
    if (merged.length === 0) {
      merged.push(rawLine)
      continue
    }
    const prev = merged[merged.length - 1].trimEnd()
    const currTrimmed = rawLine.trimStart()
    const startsWithCjk = /^[\u4e00-\u9fff]/.test(currTrimmed)
    const shouldUnwrap =
      startsWithCjk
      && ((prev.length >= 10 && /[\u4e00-\u9fff]$/.test(prev)) || /[，、]$/.test(prev))
    if (shouldUnwrap) {
      merged[merged.length - 1] = `${prev}${currTrimmed}`
    } else {
      merged.push(rawLine)
    }
  }
  return merged
}

/**
 * 扫描当前行是否存在未闭合的行内/行中数学定界符（`$`, `$$`, `\[`, `\(`），
 * 仅在需要跨软换行配对时返回待闭合的标记类型。
 */
function findUnclosedMathDelimiter(line: string): '$$' | '\\[' | '\\(' | '$' | null {
  let i = 0
  while (i < line.length) {
    const rest = line.slice(i)
    if (rest.startsWith('`')) {
      const codeMatch = /^`([^`\n]+)`/.exec(rest)
      if (codeMatch) {
        i += codeMatch[0].length
        continue
      }
    }
    if (rest.startsWith('\\$')) {
      i += 2
      continue
    }
    if (rest.startsWith('$$') && hasEvenBackslashesBefore(line, i)) {
      const closeIdx = findUnescapedMarker(rest, '$$', 2)
      if (closeIdx === -1) return '$$'
      i += closeIdx + 2
      continue
    }
    if (rest.startsWith('\\[') && hasEvenBackslashesBefore(line, i)) {
      const closeIdx = findUnescapedMarker(rest, '\\]', 2)
      if (closeIdx === -1) return '\\['
      i += closeIdx + 2
      continue
    }
    if (rest.startsWith('\\(') && hasEvenBackslashesBefore(line, i)) {
      const closeIdx = findUnescapedMarker(rest, '\\)', 2)
      if (closeIdx === -1) return '\\('
      i += closeIdx + 2
      continue
    }
    if (rest.startsWith('$') && !rest.startsWith('$$') && hasEvenBackslashesBefore(line, i)) {
      const closeIdx = findClosingInlineDollar(rest, 0)
      if (closeIdx !== -1) {
        i += closeIdx + 1
        continue
      }
      const nextChar = rest[1]
      if (nextChar && /\d/.test(nextChar)) {
        i += 1
        continue
      }
      return '$'
    }
    i += 1
  }
  return null
}

/**
 * 将被 PDF/排版软换行拆断的跨行公式（如 `平面 $w^T x +\nb = 0$`）合并回单行，
 * 仅在后续行确实存在闭合定界符时才合并，防止孤立 `$` 吞噬无关文本。
 */
function mergeUnclosedMathLines(lines: string[]): string[] {
  if (lines.length <= 1) return lines
  const result: string[] = []
  let idx = 0

  while (idx < lines.length) {
    let combined = lines[idx]
    let unclosed = findUnclosedMathDelimiter(combined)

    if (unclosed) {
      let probe = idx + 1
      let candidate = combined
      let closed = false

      while (probe < lines.length && probe - idx <= 8) {
        const joiner = unclosed === '$$' || unclosed === '\\[' ? '\n' : ' '
        candidate = `${candidate}${joiner}${lines[probe]}`
        const nextState = findUnclosedMathDelimiter(candidate)
        if (!nextState) {
          closed = true
          combined = candidate
          idx = probe
          break
        }
        unclosed = nextState
        probe += 1
      }

      if (!closed) {
        result.push(lines[idx])
        idx += 1
        continue
      }
    }

    result.push(combined)
    idx += 1
  }

  return result
}

function buildMultilineChildren(lines: string[]): RichTextNode[] {
  const normalized = mergeUnclosedMathLines(lines)
  const children: RichTextNode[] = []
  normalized.forEach((line, idx) => {
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
  if (startsWithKnownEnvironment(trimmed)) return true
  if (/^#{1,4}\s+/.test(trimmed)) return true
  if (/^>\s?/.test(trimmed)) return true
  if (/^\s*[-*•]\s+/.test(line)) return true
  if (/^\s*\d+[.)]\s+/.test(line)) return true
  return false
}

function unwrapLatexFenceBody(body: string): string {
  const trimmed = body.trim()
  if (trimmed.startsWith('$$') && trimmed.endsWith('$$') && trimmed.length >= 4) {
    const inner = trimmed.slice(2, -2)
    if (findUnescapedMarker(inner, '$$', 0) === -1) return inner.trim()
  }
  if (trimmed.startsWith('\\[') && trimmed.endsWith('\\]') && trimmed.length >= 4) {
    const inner = trimmed.slice(2, -2)
    if (findUnescapedMarker(inner, '\\]', 0) === -1) return inner.trim()
  }
  return trimmed
}

function pushTrailingAfterMathBlock(nodes: RichTextNode[], afterClose: string): void {
  const trimmed = afterClose.trim()
  if (!trimmed) return
  nodes.push({
    name: 'p',
    attrs: { class: 'rt-p', style: STYLES.paragraph },
    children: TRAILING_PUNCT_RE.test(trimmed) ? [makeText(trimmed)] : parseInline(trimmed),
  })
}

function tryConsumeBareEnvironmentBlock(
  lines: string[],
  startIdx: number,
  nodes: RichTextNode[],
): number {
  const trimmed = lines[startIdx].trim()
  const envName = startsWithKnownEnvironment(trimmed)
  if (!envName) return -1

  const endTag = `\\end{${envName}}`
  const firstEndIdx = trimmed.indexOf(endTag)
  if (firstEndIdx !== -1) {
    const envExpr = trimmed.slice(0, firstEndIdx + endTag.length)
    const afterClose = trimmed.slice(firstEndIdx + endTag.length)
    nodes.push(makeMathBlockNode(envExpr))
    pushTrailingAfterMathBlock(nodes, afterClose)
    return startIdx + 1
  }

  const collected: string[] = [lines[startIdx]]
  let cursor = startIdx + 1
  let afterClose = ''
  while (cursor < lines.length) {
    const line = lines[cursor]
    const endIdx = line.indexOf(endTag)
    if (endIdx !== -1) {
      collected.push(line.slice(0, endIdx + endTag.length))
      afterClose = line.slice(endIdx + endTag.length)
      cursor += 1
      break
    }
    collected.push(line)
    cursor += 1
  }

  nodes.push(makeMathBlockNode(collected.join('\n').trim()))
  pushTrailingAfterMathBlock(nodes, afterClose)
  return cursor
}

function tryConsumeBlockMath(
  lines: string[],
  startIdx: number,
  nodes: RichTextNode[],
): number {
  const trimmed = lines[startIdx].trim()
  const isBracket = trimmed.startsWith('\\[')
  const isDollar = trimmed.startsWith('$$')
  if (!isBracket && !isDollar) return -1

  const openMarker = isBracket ? '\\[' : '$$'
  const closeMarker = isBracket ? '\\]' : '$$'
  const afterOpen = trimmed.slice(openMarker.length)
  const sameLineCloseIdx = findUnescapedMarker(afterOpen, closeMarker, 0)

  if (sameLineCloseIdx !== -1) {
    const afterClose = afterOpen.slice(sameLineCloseIdx + closeMarker.length).trim()
    // 若同一行闭合后仍有正文或第二段公式（非纯句末标点），交由段落/行内解析器完整切分
    if (afterClose && !TRAILING_PUNCT_RE.test(afterClose)) {
      return -1
    }
    const expr = afterOpen.slice(0, sameLineCloseIdx).trim()
    nodes.push(makeMathBlockNode(expr))
    pushTrailingAfterMathBlock(nodes, afterClose)
    return startIdx + 1
  }

  const mathLines: string[] = afterOpen ? [afterOpen] : []
  let cursor = startIdx + 1
  let closed = false
  let afterClose = ''

  while (cursor < lines.length) {
    const currentLine = lines[cursor]
    const closeIdx = findUnescapedMarker(currentLine, closeMarker, 0)
    if (closeIdx !== -1) {
      const prefix = currentLine.slice(0, closeIdx).trim()
      if (prefix) mathLines.push(prefix)
      afterClose = currentLine.slice(closeIdx + closeMarker.length).trim()
      cursor += 1
      closed = true
      break
    }
    mathLines.push(currentLine)
    cursor += 1
  }

  if (!closed) {
    // 遇到未闭合定界符时仅消费到空行前为止，防止吞掉后续正文与标题
    const fallbackLines: string[] = afterOpen ? [afterOpen] : []
    let scan = startIdx + 1
    while (scan < lines.length && lines[scan].trim() && !isBlockStarter(lines[scan])) {
      fallbackLines.push(lines[scan])
      scan += 1
    }
    nodes.push(makeMathBlockNode(fallbackLines.join('\n').trim()))
    return scan
  }

  nodes.push(makeMathBlockNode(mathLines.join('\n').trim()))
  pushTrailingAfterMathBlock(nodes, afterClose)
  return cursor
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
      const lang = trimmed.slice(3).trim().toLowerCase()
      const codeLines: string[] = []
      i += 1
      while (i < lines.length && !/^```\s*$/.test(lines[i].trim())) {
        codeLines.push(lines[i])
        i += 1
      }
      if (i < lines.length) i += 1

      if (LATEX_FENCE_LANGS.has(lang)) {
        const expr = unwrapLatexFenceBody(codeLines.join('\n'))
        if (expr) {
          nodes.push(makeMathBlockNode(expr))
        }
        continue
      }

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

    const envNext = tryConsumeBareEnvironmentBlock(lines, i, nodes)
    if (envNext !== -1) {
      i = envNext
      continue
    }

    const table = tryParseTable(lines, i, parseInline)
    if (table) {
      nodes.push(table.node)
      i = table.nextIdx
      continue
    }

    const mathBlockNext = tryConsumeBlockMath(lines, i, nodes)
    if (mathBlockNext !== -1) {
      i = mathBlockNext
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
    while (
      i < lines.length
      && !isBlockStarter(lines[i])
      && !(paraLines.length > 0 && isTableStart(lines, i))
    ) {
      paraLines.push(lines[i])
      i += 1
    }
    if (paraLines.length > 0) {
      nodes.push({
        name: 'p',
        attrs: { class: 'rt-p', style: STYLES.paragraph },
        children: buildMultilineChildren(unwrapCjkParaLines(paraLines)),
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
const EXTENDED_LATIN_MATH_GARBLE = /(?:[\u0127\u0111\u00f8\u0142\u00fe\u0126\u0110\u00d8\u0141\u00de][A-Za-z0-9_=+\-^/*]|[A-Za-z0-9_=+\-^/*][\u0127\u0111\u00f8\u0142\u00fe\u0126\u0110\u00d8\u0141\u00de]|[\u0100-\u024f](?=[A-Za-z0-9_]*\d)|\d(?=[A-Za-z0-9_]*[\u0100-\u024f]))/
const CORRUPT_GLYPH_RE = /[\ue000-\uf8ff\ufffd\u2612\u25af]/
const BOX_PLACEHOLDER = '[\\u2610\\u25a1\\u25a0\\u25aa\\u25ab\\u25c7\\u25c6]'
const MATH_ADJACENT_BOX_RE = new RegExp(
  `(?:(?:[A-Za-z0-9_=+<>≤≥(\\u0370-\\u03ff]|[^\\s][ \\t]*-)[ \\t]*${BOX_PLACEHOLDER}`
  + `|${BOX_PLACEHOLDER}[ \\t]*[=+\\-<>≤≥_^*\\/{}\\u0370-\\u03ff]`
  + `|${BOX_PLACEHOLDER}[A-Za-z0-9](?![A-Za-z.])`
  + `|${BOX_PLACEHOLDER}[ \\t]+[A-Za-z0-9\\u0370-\\u03ff]+[ \\t]*[_^=+\\-<>≤≥*/])`,
)
const DANGLING_INDEX_LINE_RE = /^\d+\s*,\s*(?:\.{2,3}\s*,\s*)?[A-Za-z\u0370-\u03ff][A-Za-z0-9]{0,3}$/

function hasDenseSingleLetterFragments(text: string): boolean {
  const nonCodeLines: string[] = []
  let inFence = false
  for (const rawLine of text.replace(/\r\n/g, '\n').replace(/\r/g, '\n').split('\n')) {
    const trimmed = rawLine.trim()
    if (!trimmed) continue
    if (trimmed.startsWith('```')) {
      inFence = !inFence
      continue
    }
    if (!inFence) nonCodeLines.push(trimmed)
  }

  let singleLetterLines = 0
  let shortFormulaLines = 0
  let danglingLines = 0
  let consecutiveSingle = 0
  let maxConsecutiveSingle = 0

  for (const ln of nonCodeLines) {
    if (ln.length === 1 && /^[A-Za-z]$/.test(ln)) {
      singleLetterLines += 1
      consecutiveSingle += 1
      if (consecutiveSingle > maxConsecutiveSingle) maxConsecutiveSingle = consecutiveSingle
    } else {
      consecutiveSingle = 0
    }
    if (
      ln.length <= 8
      && !/[\u4e00-\u9fff]/.test(ln)
      && /[\d=+\-\u2212\u00d7\u00f7\u2211\u221a^_/\u0370-\u03ff]/.test(ln)
    ) {
      shortFormulaLines += 1
    }
    if (
      ln.length <= 24
      && !/[\u4e00-\u9fff]/.test(ln)
      && (DANGLING_INDEX_LINE_RE.test(ln) || (/[=([]$/.test(ln) && /[A-Za-z0-9\u0370-\u03ff]/.test(ln)))
    ) {
      danglingLines += 1
    }
  }

  if (danglingLines >= 1 && maxConsecutiveSingle >= 3) return true
  if (nonCodeLines.length >= 6 && singleLetterLines >= 3) {
    return (singleLetterLines + shortFormulaLines + danglingLines) / nonCodeLines.length >= 0.35
  }
  return false
}

/**
 * 检测历史未重解析 PDF 切片是否残留 `SymbolMT` ASCII 符号乱码簇、扩展拉丁数学乱码（如 `ħx1`）、
 * 替代符/缺字形豆腐块（`\ufffd`、`☒`、`▯` 或数学邻接方框）或密集单字母碎行。
 */
export function isGarbledSnippetText(text: string | null | undefined): boolean {
  if (!text || !text.trim()) return false
  const cleaned = text.replace(/\$\$/g, ' ').replace(/\*{3,}/g, ' ')
  if (
    EXTENDED_LATIN_MATH_GARBLE.test(cleaned)
    || CORRUPT_GLYPH_RE.test(cleaned)
    || MATH_ADJACENT_BOX_RE.test(cleaned)
  ) {
    return true
  }

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

  return hasDenseSingleLetterFragments(text)
}
