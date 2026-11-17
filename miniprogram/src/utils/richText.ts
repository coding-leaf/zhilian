/**
 * 零依赖 Markdown + LaTeX/数学公式 AST 编译器，面向微信小程序原生 `<rich-text :nodes>`。
 *
 * 模块划分：
 * - `richTextCore.ts`：节点类型、内联样式表（`rgb(...)` 颜色，禁止裸 Hex）、转义与文本工具。
 * - `latexSymbols.ts`：LaTeX 符号 / 运算符 / 修饰记号 / 环境数据表。
 * - `richTextMath.ts`：LaTeX 命令与 `\begin{...}` 环境解析。
 * - 本文件：Markdown 块级（标题、列表、引用、代码块、GFM 表格、公式块）与行内解析。
 */
import {
  STYLES,
  makeText,
  mergeAdjacentText,
  pushText,
  type RichTextElementNode,
  type RichTextNode,
} from './richTextCore'
import {
  collectEnvironmentBlock,
  consumeLatexCommand,
  isKnownLatexCommand,
  makeScriptNode,
  parseMathToNodes,
  readScriptOperand,
  startsWithKnownEnvironment,
} from './richTextMath'
import { isTableStart, tryParseTable } from './richTextTable'

export { escapeHtml } from './richTextCore'
export type { RichTextElementNode, RichTextNode, RichTextTextNode } from './richTextCore'
export { parseMathToNodes } from './richTextMath'

const HEADING_SIZES: Record<number, string> = {
  1: 'font-size:1.10em;',
  2: 'font-size:1.06em;',
  3: 'font-size:1.03em;',
  4: 'font-size:1.0em;',
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
    const operand = readScriptOperand(line, cursor + 1)
    if (!operand) break
    out.push(makeScriptNode(line[cursor] === '_' ? 'sub' : 'sup', parseMathToNodes(operand.content)))
    cursor = operand.nextIdx
  }
  return cursor
}

function tryConsumeUnfencedScript(line: string, idx: number, out: RichTextNode[]): number {
  const slice = line.slice(idx)
  const bracedSub = /^([A-Za-z0-9)\]])_\{([^}]+)\}/.exec(slice)
  if (bracedSub) {
    pushText(out, bracedSub[1])
    out.push(makeScriptNode('sub', parseMathToNodes(bracedSub[2])))
    return consumeAttachedScripts(line, idx + bracedSub[0].length, out)
  }

  const bracedSup = /^([A-Za-z0-9)\]])\^\{([^}]+)\}/.exec(slice)
  if (bracedSup) {
    pushText(out, bracedSup[1])
    out.push(makeScriptNode('sup', parseMathToNodes(bracedSup[2])))
    return consumeAttachedScripts(line, idx + bracedSup[0].length, out)
  }

  const prevChar = idx > 0 ? line[idx - 1] : ''
  const isWordPrefix = /[A-Za-z0-9_]/.test(prevChar)
  if (!isWordPrefix) {
    const shortSub = /^([A-Za-z])_([A-Za-z0-9]{1,2})(?![A-Za-z0-9_])/.exec(slice)
    if (shortSub) {
      pushText(out, shortSub[1])
      out.push(makeScriptNode('sub', [makeText(shortSub[2])]))
      return consumeAttachedScripts(line, idx + shortSub[0].length, out)
    }
  }

  const shortSup = /^([A-Za-z0-9)\]])\^([A-Za-z0-9+-]{1,3})(?![A-Za-z0-9_])/.exec(slice)
  if (shortSup) {
    pushText(out, shortSup[1])
    out.push(makeScriptNode('sup', [makeText(shortSup[2])]))
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
      const latexCmd = /^\\([a-zA-Z]+)/.exec(rest)
      if (latexCmd && (startsWithKnownEnvironment(rest) || isKnownLatexCommand(latexCmd[1]))) {
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
  if (startsWithKnownEnvironment(trimmed)) return true
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

    if (startsWithKnownEnvironment(trimmed)) {
      const block = collectEnvironmentBlock(lines, i)
      nodes.push({
        name: 'div',
        attrs: { class: 'rt-math-block', style: STYLES.mathBlock },
        children: parseMathToNodes(block.expr),
      })
      i = block.nextIdx
      continue
    }

    const table = tryParseTable(lines, i, parseInline)
    if (table) {
      nodes.push(table.node)
      i = table.nextIdx
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