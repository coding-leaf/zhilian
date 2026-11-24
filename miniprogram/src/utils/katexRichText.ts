/**
 * KaTeX virtual DOM (`katex.__renderToDomTree`) -> 微信小程序 `<rich-text>` AST 适配器。
 *
 * 借鉴 `katex-mini` 轻量 AST 映射方案，零 `window`/`document` 依赖，
 * 将 `Span` / `Anchor` / `SymbolNode` / `SvgNode` / `PathNode` / `LineNode`
 * 同步转换为微信原生 `<rich-text :nodes>` 支持的 `span` / `img` / `text` 节点数组。
 */
import katex from 'katex'
import { makeText, mergeAdjacentText, type RichTextNode } from './richTextCore'

interface KatexDomNodeBase {
  classes?: string[]
  style?: Record<string, string>
  attributes?: Record<string, string>
  children?: KatexDomNodeBase[]
  text?: string
  italic?: number
  src?: string
  alt?: string
  pathName?: string
  alternate?: string
  toMarkup?: () => string
}

interface KatexDomTreeConstructors {
  Span?: new (...args: never[]) => KatexDomNodeBase
  Anchor?: new (...args: never[]) => KatexDomNodeBase
  SymbolNode?: new (...args: never[]) => KatexDomNodeBase
  SvgNode?: new (...args: never[]) => KatexDomNodeBase
  PathNode?: new (...args: never[]) => KatexDomNodeBase
  LineNode?: new (...args: never[]) => KatexDomNodeBase
}

interface KatexRenderOptions {
  displayMode?: boolean
  output?: 'html' | 'mathml' | 'htmlAndMathml'
  throwOnError?: boolean
  strict?: boolean | string
  trust?: boolean
  errorColor?: string
}

interface KatexInternalApi {
  __renderToDomTree: (expr: string, options?: KatexRenderOptions) => KatexDomNodeBase
  __domTree?: KatexDomTreeConstructors
}

const katexApi = katex as unknown as KatexInternalApi

const ERROR_COLOR_RGB = 'rgb(185,28,28)'
const SVG_IMG_STYLE = 'display:block;position:absolute;width:100%;height:inherit;'

function hyphenateCssProp(prop: string): string {
  return prop.replace(/([A-Z])/g, '-$1').toLowerCase()
}

function escapeXmlAttr(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

/** 将内联样式中可能存在的 `#rgb`/`#rrggbb` 转为 `rgb(...)`，避免触发无裸 Hex 门禁。 */
function normalizeHexColors(styleText: string): string {
  return styleText.replace(/#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b/g, (_match, hex: string) => {
    const full =
      hex.length === 3
        ? `${hex[0]}${hex[0]}${hex[1]}${hex[1]}${hex[2]}${hex[2]}`
        : hex
    const r = parseInt(full.slice(0, 2), 16)
    const g = parseInt(full.slice(2, 4), 16)
    const b = parseInt(full.slice(4, 6), 16)
    return `rgb(${r},${g},${b})`
  })
}

function serializeStyle(
  styleMap: Record<string, string> | undefined,
  attrStyle: string | undefined,
  extraItalic = 0,
): string {
  const parts: string[] = []
  if (attrStyle && attrStyle.trim()) {
    const trimmed = attrStyle.trim()
    parts.push(trimmed.endsWith(';') ? trimmed : `${trimmed};`)
  }
  if (extraItalic > 0) {
    parts.push(`margin-right:${extraItalic}em;`)
  }
  if (styleMap) {
    for (const key of Object.keys(styleMap)) {
      const value = styleMap[key]
      if (value !== undefined && value !== '') {
        parts.push(`${hyphenateCssProp(key)}:${value};`)
      }
    }
  }
  return parts.length > 0 ? normalizeHexColors(parts.join('')) : ''
}

function encodeSvgDataUri(svgMarkup: string): string {
  const compact = svgMarkup.replace(/\r?\n/g, ' ').replace(/\s+/g, ' ').trim()
  const encoded = compact
    .replace(/%/g, '%25')
    .replace(/#/g, '%23')
    .replace(/"/g, '%22')
    .replace(/</g, '%3C')
    .replace(/>/g, '%3E')
  return `data:image/svg+xml;charset=utf-8,${encoded}`
}

function isInstanceOf(node: KatexDomNodeBase, ctor?: new (...args: never[]) => KatexDomNodeBase): boolean {
  return typeof ctor === 'function' && node instanceof ctor
}

function isSvgChildLine(child: KatexDomNodeBase): boolean {
  const domTree = katexApi.__domTree
  if (isInstanceOf(child, domTree?.LineNode)) return true
  return Boolean(child.attributes && ('x1' in child.attributes || 'y1' in child.attributes))
}

function renderSvgChildMarkup(child: KatexDomNodeBase, needsExplicitNoStroke: boolean): string {
  const domTree = katexApi.__domTree
  if (isInstanceOf(child, domTree?.PathNode) || 'pathName' in child || 'alternate' in child) {
    if (typeof child.toMarkup === 'function') {
      const raw = child.toMarkup()
      if (needsExplicitNoStroke && !/\bstroke=/.test(raw)) {
        return raw.replace(/\/?>$/, ' stroke="none"/>')
      }
      return raw
    }
    if (child.alternate) {
      return `<path d="${escapeXmlAttr(child.alternate)}"${needsExplicitNoStroke ? ' stroke="none"' : ''}/>`
    }
    return ''
  }

  if (isSvgChildLine(child)) {
    if (typeof child.toMarkup === 'function') {
      const raw = child.toMarkup()
      if (!/\bstroke=/.test(raw)) {
        return raw.replace(/\/?>$/, ' stroke="currentColor"/>')
      }
      return raw
    }
    const attrs = child.attributes ?? {}
    const attrStr = Object.keys(attrs)
      .map((key) => ` ${key}="${escapeXmlAttr(attrs[key])}"`)
      .join('')
    const strokeAttr = 'stroke' in attrs ? '' : ' stroke="currentColor"'
    return `<line${attrStr}${strokeAttr}/>`
  }

  return typeof child.toMarkup === 'function' ? child.toMarkup() : ''
}

function buildSvgMarkup(node: KatexDomNodeBase): string {
  const attrs = node.attributes ?? {}
  const children = node.children ?? []
  const hasLine = children.some(isSvgChildLine)
  const attrParts: string[] = []
  if (!('xmlns' in attrs)) {
    attrParts.push('xmlns="http://www.w3.org/2000/svg"')
  }
  if (!('fill' in attrs)) {
    attrParts.push('fill="currentColor"')
  }
  for (const key of Object.keys(attrs)) {
    attrParts.push(`${key}="${escapeXmlAttr(attrs[key])}"`)
  }
  const inner = children.map((child) => renderSvgChildMarkup(child, hasLine)).join('')
  return `<svg ${attrParts.join(' ')}>${inner}</svg>`
}

function convertDomNode(node: KatexDomNodeBase): RichTextNode[] {
  const domTree = katexApi.__domTree

  if (isInstanceOf(node, domTree?.SvgNode) || (!('classes' in node) && !('text' in node) && Array.isArray(node.children))) {
    const svgMarkup = buildSvgMarkup(node)
    return [
      {
        name: 'img',
        attrs: {
          class: 'katex-svg',
          style: SVG_IMG_STYLE,
          src: encodeSvgDataUri(svgMarkup),
        },
      },
    ]
  }

  if (isInstanceOf(node, domTree?.SymbolNode) || typeof node.text === 'string') {
    const text = node.text ?? ''
    if (!text) return []
    const className = (node.classes ?? []).filter(Boolean).join(' ')
    const style = serializeStyle(node.style, node.attributes?.style, node.italic ?? 0)
    if (!className && !style) {
      return [makeText(text)]
    }
    const attrs: Record<string, string> = {
      class: className ? `kt-s ${className}` : 'kt-s',
    }
    if (style) attrs.style = style
    return [{ name: 'span', attrs, children: [makeText(text)] }]
  }

  if (typeof node.src === 'string' && !Array.isArray(node.children)) {
    const className = (node.classes ?? []).filter(Boolean).join(' ')
    const style = serializeStyle(node.style, node.attributes?.style)
    const attrs: Record<string, string> = { src: node.src }
    if (className) attrs.class = className
    if (style) attrs.style = style
    return [{ name: 'img', attrs }]
  }

  const childNodes: RichTextNode[] = []
  for (const child of node.children ?? []) {
    childNodes.push(...convertDomNode(child))
  }
  const mergedChildren = mergeAdjacentText(childNodes)

  const className = (node.classes ?? []).filter(Boolean).join(' ')
  const style = serializeStyle(node.style, node.attributes?.style)
  // 必须保留 KaTeX 无类包装 Span（如 .vlist > span > span、.mfrac > span > span），
  // 并统一附带 .kt-s 类名供 WXSS 命中，避免微信小程序剥离 span 标签选择器导致分式与上下标错位。
  const attrs: Record<string, string> = {
    class: className ? `kt-s ${className}` : 'kt-s',
  }
  if (style) attrs.style = style

  return [
    {
      name: 'span',
      attrs,
      children: mergedChildren,
    },
  ]
}

/**
 * 使用 `katex.__renderToDomTree` 将单个 LaTeX 公式编译为 `<rich-text>` 节点数组。
 * 遇到异常语法或意外错误时安全降级为可读纯文本节点，绝不抛异常导致白屏。
 */
export function renderKatexToNodes(expr: string, displayMode = false): RichTextNode[] {
  const trimmed = expr.trim()
  if (!trimmed) return []

  try {
    const domTree = katexApi.__renderToDomTree(trimmed, {
      displayMode,
      output: 'html',
      throwOnError: false,
      strict: false,
      trust: false,
      errorColor: ERROR_COLOR_RGB,
    })
    const converted = convertDomNode(domTree)
    return converted.length > 0 ? converted : [makeText(trimmed)]
  } catch {
    return [
      {
        name: 'span',
        attrs: { class: 'katex-fallback' },
        children: [makeText(trimmed)],
      },
    ]
  }
}
