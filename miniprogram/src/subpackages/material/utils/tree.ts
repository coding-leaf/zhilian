/**
 * 知识点层级树与出题配置相关的纯函数工具模块。
 *
 * 遵循系统单向分层与无外部依赖原则：输入输出均为纯数据结构，无副作用。
 */

import type { KnowledgeTreeNode } from '../../../types/material';

/**
 * 递归平铺知识点树，返回扁平化的节点列表。
 *
 * @param nodes 嵌套的知识点树节点数组。
 * @returns 平铺后的一维节点数组。
 */
export function flattenKnowledgeTree(nodes: KnowledgeTreeNode[]): KnowledgeTreeNode[] {
  const result: KnowledgeTreeNode[] = [];

  function traverse(list: KnowledgeTreeNode[]): void {
    for (const node of list) {
      result.push(node);
      if (node.children && node.children.length > 0) {
        traverse(node.children);
      }
    }
  }

  if (Array.isArray(nodes)) {
    traverse(nodes);
  }

  return result;
}

/**
 * 扁平化可见行数据结构：节点及其渲染深度 (根节点深度为 1)。
 */
export interface KnowledgeTreeRow {
  node: KnowledgeTreeNode;
  depth: number;
}

/**
 * 前序遍历知识点树，输出折叠感知的可见行列表。
 *
 * 被折叠节点的子孙不进入结果，但折叠节点自身始终保留；用于微信小程序端
 * 以单层列表 + 缩进替代递归组件渲染，规避递归组件 props 透传失效问题。
 *
 * @param nodes 嵌套的知识点树根节点数组。
 * @param collapsedMap 折叠状态映射 (key 为节点 ID，true 表示已折叠)。
 * @returns 可见行列表，按前序遍历顺序排列。
 */
export function flattenVisibleTree(
  nodes: KnowledgeTreeNode[],
  collapsedMap: Record<string, boolean> = {},
): KnowledgeTreeRow[] {
  const rows: KnowledgeTreeRow[] = [];

  function traverse(list: KnowledgeTreeNode[], depth: number): void {
    if (!Array.isArray(list)) return;
    for (const node of list) {
      if (!node || !node.id) continue;
      rows.push({ node, depth });
      const isCollapsed = Boolean(collapsedMap[node.id]);
      if (!isCollapsed && Array.isArray(node.children) && node.children.length > 0) {
        traverse(node.children, depth + 1);
      }
    }
  }

  traverse(nodes, 1);
  return rows;
}

/**
 * 递归收集指定节点及其所有子孙节点的 ID 列表。
 *
 * @param node 目标知识点节点。
 * @returns 包含当前节点及其所有子孙节点 ID 的数组。
 */
export function collectNodeAndDescendantIds(node: KnowledgeTreeNode): string[] {
  const ids: string[] = [];

  function traverse(n: KnowledgeTreeNode): void {
    if (!n || !n.id) return;
    ids.push(n.id);
    if (Array.isArray(n.children) && n.children.length > 0) {
      for (const child of n.children) {
        traverse(child);
      }
    }
  }

  traverse(node);
  return ids;
}

/**
 * 节点勾选状态：全选 / 半选 / 未选。
 */
export type KnowledgeNodeCheckStatus = 'checked' | 'indeterminate' | 'unchecked';

/**
 * 依据当前选中集合推导节点自身及其子树的勾选状态。
 *
 * 与「仅判断自身 ID」不同，本函数自下而上聚合整个子树：子树全选中返回
 * `checked`，全未选返回 `unchecked`，部分选中返回 `indeterminate`（半选），
 * 从而支持父节点复选框的正确回显。
 *
 * @param node 目标知识点节点。
 * @param selectedIdSet 已选中的知识点主键集合。
 * @returns 节点的勾选状态。
 */
export function getNodeCheckStatus(
  node: KnowledgeTreeNode | null | undefined,
  selectedIdSet: ReadonlySet<string> = new Set<string>(),
): KnowledgeNodeCheckStatus {
  if (!node || !node.id) {
    return 'unchecked';
  }
  const subtreeIds = collectNodeAndDescendantIds(node);
  if (subtreeIds.length === 0) {
    return 'unchecked';
  }
  let selectedCount = 0;
  for (const id of subtreeIds) {
    if (selectedIdSet.has(id)) {
      selectedCount += 1;
    }
  }
  if (selectedCount === 0) {
    return 'unchecked';
  }
  if (selectedCount === subtreeIds.length) {
    return 'checked';
  }
  return 'indeterminate';
}

/**
 * 根据知识点主键列表筛选匹配的节点。
 *
 * @param nodes 知识点树或平铺节点列表。
 * @param ids 目标知识点主键 ID 集合。
 * @returns 匹配的知识点节点列表。
 */
export function filterNodesByIds(nodes: KnowledgeTreeNode[], ids: string[]): KnowledgeTreeNode[] {
  const flat = flattenKnowledgeTree(nodes);
  const idSet = new Set(ids);
  return flat.filter((node) => idSet.has(node.id));
}

/**
 * 计算当前选中知识点在总知识点树中的覆盖率百分比 (0~100)。
 *
 * @param totalNodes 完整知识点树或平铺列表。
 * @param selectedIds 已选中的知识点主键 ID 列表。
 * @returns 覆盖率整数百分比 (0~100)，空输入返回 0。
 */
export function calculateKnowledgeCoverage(
  totalNodes: KnowledgeTreeNode[],
  selectedIds: string[],
): number {
  const flat = flattenKnowledgeTree(totalNodes);
  if (flat.length === 0) {
    return 0;
  }
  const idSet = new Set(selectedIds);
  const matchedCount = flat.filter((node) => idSet.has(node.id)).length;
  return Math.min(100, Math.round((matchedCount / flat.length) * 100));
}

/**
 * 出题生成参数纯函数校验。
 * 校验题数必须在 1~20 之间（与后端契约一致），题型列表不可为空。
 *
 * @param config 出题配置对象。
 * @returns 校验结果及失败提示文案。
 */
export function validateQuestionConfig(config: { count?: number; question_types?: string[] }): {
  valid: boolean;
  message?: string;
} {
  const count = config.count;
  if (count === undefined || count === null || isNaN(count)) {
    return { valid: false, message: '请输入出题数量' };
  }
  if (count < 1 || count > 20) {
    return { valid: false, message: '出题数量必须在 1 到 20 题之间' };
  }
  if (!config.question_types || config.question_types.length === 0) {
    return { valid: false, message: '请至少选择一种题型' };
  }
  return { valid: true };
}

/**
 * 计算前后两次对象快照中发生变更的字段列表。
 *
 * @param before 修改前快照。
 * @param after 修改后快照。
 * @returns 变更字段属性名数组。
 */
export function computeFieldDiffs(
  before: Record<string, unknown>,
  after: Record<string, unknown>,
): string[] {
  const changedFields: string[] = [];
  const allKeys = new Set([...Object.keys(before), ...Object.keys(after)]);

  for (const key of allKeys) {
    const valBefore = before[key];
    const valAfter = after[key];

    if (typeof valBefore === 'object' && typeof valAfter === 'object') {
      if (JSON.stringify(valBefore) !== JSON.stringify(valAfter)) {
        changedFields.push(key);
      }
    } else if (valBefore !== valAfter) {
      changedFields.push(key);
    }
  }

  return changedFields;
}
