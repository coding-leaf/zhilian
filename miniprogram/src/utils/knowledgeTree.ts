/**
 * 前序扁平化知识树节点（纯函数，不修改原树）。
 *
 * mp-weixin 下禁止组件模板递归自渲染，深层树统一由本函数展开后再单层 v-for 渲染。
 */
export function flattenKnowledgeTree<T extends { children?: readonly T[] | null }>(
  nodes: readonly T[] | null | undefined,
): T[] {
  if (!nodes?.length) return []
  const result: T[] = []
  const traverse = (list: readonly T[]) => {
    for (const node of list) {
      result.push(node)
      if (node.children?.length) {
        traverse(node.children)
      }
    }
  }
  traverse(nodes)
  return result
}
