/**
 * LaTeX 数学表达式 -> `<rich-text>` 节点：命令、上下标、修饰记号与 `\begin{...}` 环境。
 *
 * 渲染策略：小程序没有 MathML/KaTeX，故分式/根式降级为带括号的线性文本，
 * 矩阵 / 分段函数 / 对齐环境渲染为内联样式的 `<table>`，定界符用左右边框模拟。
 */
import {
  ACCENT_MARKS,
  IGNORED_COMMANDS,
  LATEX_ENVIRONMENTS,
  LATEX_SYMBOL_MAP,
  OPERATOR_NAMES,
  STRIP_WRAPPER_COMMANDS,
  toBlackboardBold,
  type MatrixDelimiter,
} from './latexSymbols'
import {
  STYLES,
  isTextNode,
  mergeAdjacentText,
  pushText,
  type RichTextElementNode,
  type RichTextNode,
} from './richTextCore'

interface ParsedGroup {
  content: string
  nextIdx: number
}

const FRAC_COMMANDS = new Set(['frac', 'dfrac', 'tfrac'])
const BINOM_COMMANDS = new Set(['binom', 'dbinom', 'tbinom'])
const ENTITY_SPLITTER = /(&[#a-zA-Z0-9]+;)/

const INK = 'rgb(28,25,23)'

const DELIMITER_STYLES: Record<MatrixDelimiter, string> = {
  none: '',
  paren: `border-left:2px solid ${INK};border-right:2px solid ${INK};border-radius:40% / 50%;`,
  bracket: `border-left:2px solid ${INK};border-right:2px solid ${INK};`,
  brace: `border-left:3px double ${INK};border-right:3px double ${INK};border-radius:12rpx;`,
  leftbrace: `border-left:2px solid ${INK};border-radius:14rpx 0 0 14rpx;`,
  bar: `border-left:1px solid ${INK};border-right:1px solid ${INK};`,
  doublebar: `border-left:4px double ${INK};border-right:4px double ${INK};`,
}

export function skipSpaces(src: string, idx: number): number {
  let cursor = idx
  while (cursor < src.length && src[cursor] === ' ') cursor += 1
  return cursor
}

export function readBraceGroup(src: string, openIdx: number): ParsedGroup | null {
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

/** 读取 `[...]` 可选参数（如 `\sqrt[3]{x}` 的根指数）。 */
function readBracketGroup(src: string, openIdx: number): ParsedGroup | null {
  if (src[openIdx] !== '[') return null
  const closeIdx = src.indexOf(']', openIdx + 1)
  if (closeIdx === -1) return null
  return { content: src.slice(openIdx + 1, closeIdx), nextIdx: closeIdx + 1 }
}

export function readScriptOperand(src: string, startIdx: number): ParsedGroup | null {
  const idx = skipSpaces(src, startIdx)
  if (idx >= src.length) return null
  if (src[idx] === '{') return readBraceGroup(src, idx)
  if (src[idx] === '\\') {
    const cmdMatch = /^\\[a-zA-Z]+/.exec(src.slice(idx))
    if (cmdMatch) return { content: cmdMatch[0], nextIdx: idx + cmdMatch[0].length }
  }
  return { content: src[idx], nextIdx: idx + 1 }
}

export function makeScriptNode(tag: 'sub' | 'sup', children: RichTextNode[]): RichTextElementNode {
  return {
    name: tag,
    attrs: { class: `rt-${tag}`, style: tag === 'sub' ? STYLES.sub : STYLES.sup },
    children,
  }
}

/** 仅对文本节点中非 HTML 实体的片段做字符映射（文本节点已转义，不能破坏 `&amp;` 等实体）。 */
function mapTextNodes(nodes: RichTextNode[], mapper: (text: string) => string): RichTextNode[] {
  return nodes.map((node) => {
    if (!isTextNode(node)) return node
    const text = node.text
      .split(ENTITY_SPLITTER)
      .map((part) => (ENTITY_SPLITTER.test(part) ? part : mapper(part)))
      .join('')
    return { type: 'text', text }
  })
}

function visibleLength(nodes: RichTextNode[]): number {
  return nodes.reduce((sum, node) => {
    if (isTextNode(node)) return sum + Array.from(node.text).length
    return sum + 2
  }, 0)
}

function wrapStyled(
  className: string,
  style: string,
  children: RichTextNode[],
): RichTextElementNode {
  return { name: 'span', attrs: { class: className, style }, children }
}

function applyAccent(cmd: string, inner: RichTextNode[]): RichTextNode[] {
  if (cmd === 'underline') return [wrapStyled('rt-math-underline', STYLES.mathUnderline, inner)]
  const isBar = cmd === 'bar' || cmd === 'overline'
  if (isBar && visibleLength(inner) > 1) {
    return [wrapStyled('rt-math-overline', STYLES.mathOverline, inner)]
  }
  const mark = ACCENT_MARKS[cmd]
  return mapTextNodes(inner, (text) => text.replace(/[^\s\p{M}]/gu, (ch) => `${ch}${mark}`))
}

/** 按顶层 `\\`（行）或 `&`（列）切分环境主体；忽略花括号与嵌套环境内部的分隔符。 */
function splitTopLevel(body: string, mode: 'row' | 'col'): string[] {
  const parts: string[] = []
  let current = ''
  let braceDepth = 0
  let envDepth = 0
  let i = 0
  while (i < body.length) {
    const ch = body[i]
    if (ch === '\\') {
      if (body.startsWith('\\begin{', i)) {
        envDepth += 1
        current += '\\begin{'
        i += 7
        continue
      }
      if (body.startsWith('\\end{', i)) {
        envDepth = Math.max(0, envDepth - 1)
        current += '\\end{'
        i += 5
        continue
      }
      if (body[i + 1] === '\\' && mode === 'row' && braceDepth === 0 && envDepth === 0) {
        parts.push(current)
        current = ''
        i += 2
        const spacing = /^\[\s*-?[\d.]+\s*(?:pt|em|ex|mm|cm|in)\s*\]/.exec(body.slice(i))
        if (spacing) i += spacing[0].length
        continue
      }
      current += body.slice(i, i + 2)
      i += 2
      continue
    }
    if (ch === '{') braceDepth += 1
    else if (ch === '}') braceDepth = Math.max(0, braceDepth - 1)
    else if (ch === '&' && mode === 'col' && braceDepth === 0 && envDepth === 0) {
      parts.push(current)
      current = ''
      i += 1
      continue
    }
    current += ch
    i += 1
  }
  parts.push(current)
  return parts
}

function parseEnvironmentRows(body: string): string[][] {
  const rows = splitTopLevel(body, 'row').map((row) =>
    splitTopLevel(row, 'col').map((cell) => cell.trim()),
  )
  const last = rows[rows.length - 1]
  if (last && last.length === 1 && last[0] === '') rows.pop()
  return rows
}

function buildGridTable(
  rows: string[][],
  cellStyle: (col: number) => string,
): RichTextElementNode {
  return {
    name: 'table',
    attrs: { class: 'rt-math-grid', style: STYLES.mathMatrixTable },
    children: [
      {
        name: 'tbody',
        children: rows.map((row) => ({
          name: 'tr',
          children: row.map((cell, col) => ({
            name: 'td',
            attrs: { style: cellStyle(col) },
            children: parseMathToNodes(cell),
          })),
        })),
      },
    ],
  }
}

function buildEnvironmentNode(
  envName: string,
  body: string,
  columnSpec: string,
): RichTextNode[] {
  const def = LATEX_ENVIRONMENTS[envName]
  const rows = parseEnvironmentRows(body)
  if (!def || rows.length === 0) return []

  const aligns = columnSpec.match(/[lcr]/g) ?? []
  const alignName: Record<string, string> = { l: 'left', c: 'center', r: 'right' }
  const cellStyle = (col: number): string => {
    if (def.kind === 'aligned') {
      return `${STYLES.mathAlignCell}text-align:${col % 2 === 0 ? 'right' : 'left'};`
    }
    if (def.kind === 'cases') return `${STYLES.mathMatrixCell}text-align:left;`
    if (def.kind === 'array') {
      return `${STYLES.mathMatrixCell}text-align:${alignName[aligns[col] ?? 'c']};`
    }
    return STYLES.mathMatrixCell
  }

  return [
    {
      name: 'span',
      attrs: {
        class: `rt-math-env rt-math-${def.kind}`,
        style: `${STYLES.mathMatrixWrap}${DELIMITER_STYLES[def.delimiter]}`,
      },
      children: [buildGridTable(rows, cellStyle)],
    },
  ]
}

/** 在 `src[bodyStart:]` 内找到与 `name` 配对的 `\end{name}`；缺失时（流式截断）容错为吃到末尾。 */
function findEnvironmentEnd(
  src: string,
  bodyStart: number,
  name: string,
): { bodyEnd: number; nextIdx: number } {
  const marker = /\\(begin|end)\{([^}]*)\}/g
  marker.lastIndex = bodyStart
  let depth = 1
  for (let m = marker.exec(src); m; m = marker.exec(src)) {
    if (m[2] !== name) continue
    depth += m[1] === 'begin' ? 1 : -1
    if (depth === 0) return { bodyEnd: m.index, nextIdx: m.index + m[0].length }
  }
  return { bodyEnd: src.length, nextIdx: src.length }
}

/** `idx` 指向 `\begin`；渲染整个环境并返回其后的游标位置。 */
function consumeEnvironment(
  src: string,
  idx: number,
  cursor: number,
  out: RichTextNode[],
): number {
  const nameGroup = readBraceGroup(src, skipSpaces(src, cursor))
  if (!nameGroup) {
    pushText(out, 'begin')
    return cursor
  }
  const envName = nameGroup.content.trim()
  const { bodyEnd, nextIdx } = findEnvironmentEnd(src, nameGroup.nextIdx, envName)
  let body = src.slice(nameGroup.nextIdx, bodyEnd)
  let columnSpec = ''
  if (envName === 'array' || envName === 'alignedat') {
    const spec = readBraceGroup(body, skipSpaces(body, 0))
    if (spec) {
      columnSpec = spec.content
      body = body.slice(spec.nextIdx)
    }
  }
  if (LATEX_ENVIRONMENTS[envName]) {
    out.push(...buildEnvironmentNode(envName, body, columnSpec))
  } else {
    // 未知环境：丢弃 begin/end 标记，只渲染主体，避免原始 `\begin{...}` 泄漏。
    out.push(...parseMathToNodes(body))
  }
  return Math.max(nextIdx, idx + 1)
}

function consumeFraction(src: string, cursor: number, out: RichTextNode[]): number | null {
  const numGroup = readBraceGroup(src, skipSpaces(src, cursor))
  if (!numGroup) return null
  const denGroup = readBraceGroup(src, skipSpaces(src, numGroup.nextIdx))
  if (!denGroup) return null
  pushText(out, '(')
  out.push(...parseMathToNodes(numGroup.content))
  pushText(out, ')/(')
  out.push(...parseMathToNodes(denGroup.content))
  pushText(out, ')')
  return denGroup.nextIdx
}

function consumeBinomial(src: string, cursor: number, out: RichTextNode[]): number | null {
  const topGroup = readBraceGroup(src, skipSpaces(src, cursor))
  if (!topGroup) return null
  const bottomGroup = readBraceGroup(src, skipSpaces(src, topGroup.nextIdx))
  if (!bottomGroup) return null
  const rows = [[topGroup.content.trim()], [bottomGroup.content.trim()]]
  out.push({
    name: 'span',
    attrs: {
      class: 'rt-math-env rt-math-binom',
      style: `${STYLES.mathMatrixWrap}${DELIMITER_STYLES.paren}`,
    },
    children: [buildGridTable(rows, () => STYLES.mathMatrixCell)],
  })
  return bottomGroup.nextIdx
}

function consumeSqrt(src: string, cursor: number, out: RichTextNode[]): number {
  let pos = skipSpaces(src, cursor)
  const indexGroup = readBracketGroup(src, pos)
  if (indexGroup) {
    out.push(makeScriptNode('sup', parseMathToNodes(indexGroup.content)))
    pos = skipSpaces(src, indexGroup.nextIdx)
  }
  const braced = readBraceGroup(src, pos)
  if (braced) {
    pushText(out, '√(')
    out.push(...parseMathToNodes(braced.content))
    pushText(out, ')')
    return braced.nextIdx
  }
  const single = readScriptOperand(src, pos)
  pushText(out, '√')
  if (!single) return pos
  out.push(...parseMathToNodes(single.content))
  return single.nextIdx
}

function consumeAccent(
  cmd: string,
  src: string,
  cursor: number,
  out: RichTextNode[],
): number | null {
  const operand = readScriptOperand(src, cursor)
  if (!operand) return null
  out.push(...applyAccent(cmd, parseMathToNodes(operand.content)))
  return operand.nextIdx
}

function consumeBlackboard(src: string, cursor: number, out: RichTextNode[]): number | null {
  const operand = readScriptOperand(src, cursor)
  if (!operand) return null
  out.push(...mapTextNodes(parseMathToNodes(operand.content), toBlackboardBold))
  return operand.nextIdx
}

function consumeWrapper(src: string, cursor: number, out: RichTextNode[]): number | null {
  const inner = readBraceGroup(src, skipSpaces(src, cursor))
  if (!inner) return null
  out.push(...parseMathToNodes(inner.content))
  return inner.nextIdx
}

/** `src[idx]` 为反斜杠；消费一个 LaTeX 命令并返回其后的游标位置。 */
export function consumeLatexCommand(src: string, idx: number, out: RichTextNode[]): number {
  const rest = src.slice(idx)
  if (rest.startsWith('\\\\')) {
    out.push({ name: 'br' })
    return idx + 2
  }
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
  const cursor = idx + cmdMatch[0].length

  if (cmd === 'begin') return consumeEnvironment(src, idx, cursor, out)
  if (cmd === 'end') {
    const stray = readBraceGroup(src, skipSpaces(src, cursor))
    return stray ? stray.nextIdx : cursor
  }

  let consumed: number | null = null
  if (FRAC_COMMANDS.has(cmd)) consumed = consumeFraction(src, cursor, out)
  else if (BINOM_COMMANDS.has(cmd)) consumed = consumeBinomial(src, cursor, out)
  else if (cmd === 'sqrt') consumed = consumeSqrt(src, cursor, out)
  else if (cmd === 'mathbb') consumed = consumeBlackboard(src, cursor, out)
  else if (cmd in ACCENT_MARKS || cmd === 'underline') consumed = consumeAccent(cmd, src, cursor, out)
  else if (STRIP_WRAPPER_COMMANDS.has(cmd)) consumed = consumeWrapper(src, cursor, out)
  if (consumed !== null) return consumed

  if (IGNORED_COMMANDS.has(cmd)) {
    // `\left.` / `\right.` 表示不可见定界符
    return (cmd === 'left' || cmd === 'right') && src[cursor] === '.' ? cursor + 1 : cursor
  }

  if (OPERATOR_NAMES.has(cmd)) {
    pushText(out, cmd)
    if (/[A-Za-z0-9\\]/.test(src[cursor] ?? '')) pushText(out, ' ')
    return cursor
  }

  if (LATEX_SYMBOL_MAP[cmd]) {
    pushText(out, LATEX_SYMBOL_MAP[cmd])
    return cursor
  }

  pushText(out, cmd)
  return cursor
}

/** 是否为 `parseInline` 应当按 LaTeX 命令处理的已知命令（避免把普通反斜杠词误转换）。 */
export function isKnownLatexCommand(cmd: string): boolean {
  return (
    cmd in LATEX_SYMBOL_MAP
    || cmd in ACCENT_MARKS
    || STRIP_WRAPPER_COMMANDS.has(cmd)
    || IGNORED_COMMANDS.has(cmd)
    || OPERATOR_NAMES.has(cmd)
    || FRAC_COMMANDS.has(cmd)
    || BINOM_COMMANDS.has(cmd)
    || cmd === 'sqrt'
    || cmd === 'mathbb'
    || cmd === 'underline'
  )
}

/** `rest` 是否以受支持的 `\begin{env}` 开头（用于行内与整行裸环境识别）。 */
export function startsWithKnownEnvironment(rest: string): string | null {
  const match = /^\\begin\{([A-Za-z*]+)\}/.exec(rest)
  return match && LATEX_ENVIRONMENTS[match[1]] ? match[1] : null
}

/**
 * 从 `lines[startIdx]`（以 `\begin{env}` 开头）收集到配对的 `\end{env}`（或文末），
 * 返回合并后的表达式与下一行下标。
 */
export function collectEnvironmentBlock(
  lines: string[],
  startIdx: number,
): { expr: string; nextIdx: number } {
  const collected: string[] = []
  let i = startIdx
  let depth = 0
  while (i < lines.length) {
    const line = lines[i]
    depth += (line.match(/\\begin\{[^}]*\}/g) ?? []).length
    depth -= (line.match(/\\end\{[^}]*\}/g) ?? []).length
    collected.push(line.trim())
    i += 1
    if (depth <= 0) break
  }
  return { expr: collected.join(' '), nextIdx: i }
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
        out.push(makeScriptNode(ch === '_' ? 'sub' : 'sup', parseMathToNodes(operand.content)))
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
