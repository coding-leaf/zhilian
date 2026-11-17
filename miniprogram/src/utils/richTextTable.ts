/**
 * GFM 管道表格（`| h1 | h2 |` + `| --- | --- |` + 数据行）-> `<rich-text>` 节点。
 *
 * 渲染成带内联样式的 `<table><thead>…</thead><tbody>…</tbody></table>`，
 * 外层 `overflow-x:auto` 容器保证宽表可横向滚动。单元格内容经 `renderInline` 回调解析，
 * 因此行内公式、粗体、行内代码在表格中同样生效（本文件不依赖 `richText.ts`，避免循环引用）。
 */
import { STYLES, type RichTextElementNode, type RichTextNode } from './richTextCore'

type CellAlign = 'left' | 'center' | 'right'
type InlineRenderer = (text: string) => RichTextNode[]

export interface TableBlock {
  node: RichTextElementNode
  /** 表格之后的下一行下标 */
  nextIdx: number
}

const SEPARATOR_CELL = /^:?-+:?$/

/**
 * 按未转义的 `|` 切分一行；反引号代码与 `$...$` 公式内部的 `|`（如 `$|x|$`）不视为分隔符。
 */
function splitTableRow(line: string): string[] {
  const text = line.trim()
  const cells: string[] = []
  let current = ''
  let inCode = false
  let inMath = false
  let i = 0
  while (i < text.length) {
    const ch = text[i]
    if (ch === '\\' && text[i + 1] === '|') {
      current += inMath ? '\\|' : '|'
      i += 2
      continue
    }
    if (ch === '`') {
      inCode = !inCode
    } else if (ch === '$' && !inCode) {
      const marker = text[i + 1] === '$' ? '$$' : '$'
      if (inMath || text.indexOf(marker, i + marker.length) !== -1) inMath = !inMath
      current += marker
      i += marker.length
      continue
    }
    if (ch === '|' && !inCode && !inMath) {
      cells.push(current)
      current = ''
      i += 1
      continue
    }
    current += ch
    i += 1
  }
  cells.push(current)
  if (text.startsWith('|')) cells.shift()
  if (text.endsWith('|') && !text.endsWith('\\|')) cells.pop()
  return cells.map((cell) => cell.trim())
}

function readSeparatorAligns(line: string): CellAlign[] | null {
  if (!line.includes('|')) return null
  const cells = splitTableRow(line)
  if (cells.length === 0 || !cells.every((cell) => SEPARATOR_CELL.test(cell))) return null
  return cells.map((cell) => {
    const left = cell.startsWith(':')
    const right = cell.endsWith(':')
    if (left && right) return 'center'
    return right ? 'right' : 'left'
  })
}

export function isTableStart(lines: string[], idx: number): boolean {
  const header = lines[idx]
  const separator = lines[idx + 1]
  if (header === undefined || separator === undefined) return false
  if (!header.trim() || !header.includes('|')) return false
  const aligns = readSeparatorAligns(separator)
  return aligns !== null && splitTableRow(header).length === aligns.length
}

function renderCellContent(text: string, renderInline: InlineRenderer): RichTextNode[] {
  const children: RichTextNode[] = []
  text.split(/<br\s*\/?>/i).forEach((part, idx) => {
    if (idx > 0) children.push({ name: 'br' })
    children.push(...renderInline(part.trim()))
  })
  return children
}

/** 若 `lines[startIdx]` 起始于表格则解析整张表，否则返回 `null`。 */
export function tryParseTable(
  lines: string[],
  startIdx: number,
  renderInline: InlineRenderer,
): TableBlock | null {
  if (!isTableStart(lines, startIdx)) return null
  const aligns = readSeparatorAligns(lines[startIdx + 1]) ?? []
  const columnCount = aligns.length
  const headers = splitTableRow(lines[startIdx])

  const bodyRows: string[][] = []
  let i = startIdx + 2
  while (i < lines.length && lines[i].trim() && lines[i].includes('|')) {
    const cells = splitTableRow(lines[i]).slice(0, columnCount)
    while (cells.length < columnCount) cells.push('')
    bodyRows.push(cells)
    i += 1
  }

  const alignStyle = (col: number): string => `text-align:${aligns[col]};`

  const headRow: RichTextElementNode = {
    name: 'tr',
    children: headers.map((cell, col) => ({
      name: 'th',
      attrs: { style: `${STYLES.tableHeadCell}${alignStyle(col)}` },
      children: renderCellContent(cell, renderInline),
    })),
  }

  const bodyNodes: RichTextElementNode[] = bodyRows.map((row, rowIdx) => ({
    name: 'tr',
    children: row.map((cell, col) => ({
      name: 'td',
      attrs: {
        style: `${STYLES.tableCell}${rowIdx % 2 === 1 ? STYLES.tableStripe : ''}${alignStyle(col)}`,
      },
      children: renderCellContent(cell, renderInline),
    })),
  }))

  const table: RichTextElementNode = {
    name: 'table',
    attrs: { class: 'rt-table', style: STYLES.table },
    children: [
      { name: 'thead', children: [headRow] },
      { name: 'tbody', children: bodyNodes },
    ],
  }

  return {
    node: {
      name: 'div',
      attrs: { class: 'rt-table-wrap', style: STYLES.tableWrap },
      children: [table],
    },
    nextIdx: i,
  }
}
