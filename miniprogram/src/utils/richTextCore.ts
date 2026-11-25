/**
 * `richText` 家族共享的节点类型、转义与文本节点工具。
 * Markdown 解析（`richText.ts`）与 LaTeX 解析（`richTextMath.ts`）均依赖本文件，避免循环引用。
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

/**
 * 小程序 `<rich-text>` 节点内联 style 无法可靠解析 `var(--color-*)` 自定义属性，
 * 且工程规范禁止在 `App.vue` 之外使用裸 Hex 字面量，因此颜色全部采用 `rgb(...)` / `rgba(...)`。
 */
export const STYLES = {
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
  mathBlock: 'margin:10rpx 0;padding:12rpx 16rpx;background:rgb(239,246,255);border:1px solid rgb(191,219,254);border-radius:10rpx;color:rgb(28,25,23);line-height:1.6;word-break:break-word;overflow-x:auto;',
  mathInline: 'color:rgb(30,58,138);font-weight:500;',
  strong: 'font-weight:700;color:rgb(28,25,23);',
  em: 'font-style:italic;',
  del: 'text-decoration:line-through;color:rgb(120,113,108);',
  link: 'color:rgb(30,58,138);font-weight:600;',
  hr: 'height:1px;background:rgb(214,211,209);margin:14rpx 0;',
  sub: 'font-size:0.74em;vertical-align:sub;line-height:1;',
  sup: 'font-size:0.74em;vertical-align:super;line-height:1;',
  tableWrap: 'margin:8rpx 0;max-width:100%;overflow-x:auto;',
  table: 'border-collapse:collapse;min-width:100%;font-size:0.92em;line-height:1.5;border:1px solid rgb(214,211,209);',
  tableHeadCell: 'padding:8rpx 14rpx;border:1px solid rgb(214,211,209);background:rgb(239,246,255);color:rgb(28,25,23);font-weight:700;word-break:break-word;',
  tableCell: 'padding:8rpx 14rpx;border:1px solid rgb(231,229,228);color:rgb(41,37,36);word-break:break-word;',
  tableStripe: 'background:rgb(250,250,249);',
  mathMatrixWrap: 'display:inline-block;vertical-align:middle;margin:0 6rpx;padding:0 10rpx;',
  mathMatrixTable: 'border-collapse:collapse;',
  mathMatrixCell: 'padding:2rpx 10rpx;text-align:center;',
  mathAlignCell: 'padding:2rpx 4rpx;',
  mathOverline: 'text-decoration:overline;',
  mathUnderline: 'text-decoration:underline;',
} as const

export function escapeHtml(text: string): string {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

export function makeText(raw: string): RichTextTextNode {
  return { type: 'text', text: escapeHtml(raw) }
}

export function isTextNode(node: RichTextNode | undefined): node is RichTextTextNode {
  return !!node && 'type' in node && node.type === 'text'
}

/** 向 `nodes` 末尾追加文本；与上一个文本节点相邻时直接合并。 */
export function pushText(nodes: RichTextNode[], raw: string): void {
  if (!raw) return
  const escaped = escapeHtml(raw)
  const last = nodes[nodes.length - 1]
  if (isTextNode(last)) {
    last.text += escaped
    return
  }
  nodes.push({ type: 'text', text: escaped })
}

export function mergeAdjacentText(nodes: RichTextNode[]): RichTextNode[] {
  const merged: RichTextNode[] = []
  for (const node of nodes) {
    const prev = merged[merged.length - 1]
    if (isTextNode(node) && isTextNode(prev)) {
      prev.text += node.text
    } else {
      merged.push(node)
    }
  }
  return merged
}
