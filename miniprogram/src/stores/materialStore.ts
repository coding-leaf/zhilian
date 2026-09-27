/**
 * Material Store
 * Manages learning materials, active selection, and knowledge tree state.
 * Enforces pure state mutation without direct network API calls.
 */

import { defineStore } from 'pinia';
import { ref, computed } from 'vue';
import type { MaterialItem, MaterialStatus, KnowledgeTreeNode } from '../types/material';

export type KnowledgeNode = KnowledgeTreeNode;

export const useMaterialStore = defineStore('material', () => {
  // State
  const materials = ref<MaterialItem[]>([]);
  const activeMaterialId = ref<string | null>(null);
  const activeVersionId = ref<string | null>(null);
  const currentKnowledgeTree = ref<KnowledgeTreeNode[]>([]);
  const selectedKnowledgeIds = ref<string[]>([]);
  const knowledgeTreeCollapsedMap = ref<Record<string, boolean>>({});

  // Getters
  const materialsList = computed(() => materials.value);
  const currentMaterialId = computed(() => activeMaterialId.value);
  const activeVersion = computed(() => activeVersionId.value);
  const knowledgeTree = computed(() => currentKnowledgeTree.value);
  const currentMaterial = computed<MaterialItem | null>(() => {
    if (!activeMaterialId.value) {
      return null;
    }
    return materials.value.find((item) => item.id === activeMaterialId.value) ?? null;
  });

  const selectedCount = computed(() => selectedKnowledgeIds.value.length);
  const isAnyKnowledgeSelected = computed(() => selectedKnowledgeIds.value.length > 0);

  /** 未分类资料（folder_id 为空）视图，供控制台「未分类」入口使用。 */
  const unclassifiedMaterials = computed(() => materials.value.filter((item) => !item.folder_id));

  const hasLowConfidenceNode = computed(() => {
    function checkNode(node: KnowledgeTreeNode): boolean {
      if (node.is_low_confidence) {
        return true;
      }
      if (node.children && node.children.length > 0) {
        return node.children.some(checkNode);
      }
      return false;
    }
    return currentKnowledgeTree.value.some(checkNode);
  });

  // Actions
  function setMaterials(list: MaterialItem[]): void {
    materials.value = [...list];
  }

  function setMaterialsList(list: MaterialItem[]): void {
    setMaterials(list);
  }

  function addMaterial(item: MaterialItem): void {
    const index = materials.value.findIndex((m) => m.id === item.id);
    if (index >= 0) {
      materials.value[index] = item;
    } else {
      materials.value.unshift(item);
    }
  }

  function appendMaterialsList(list: MaterialItem[]): void {
    materials.value = [...materials.value, ...list];
  }

  /** 本地剔除资料（移动课程 / 删除后同步全局切片，不发请求）。 */
  function removeMaterial(id: string): void {
    materials.value = materials.value.filter((item) => item.id !== id);
    if (activeMaterialId.value === id) {
      activeMaterialId.value = null;
      activeVersionId.value = null;
    }
  }

  /** 本地更新资料归属课程（移动成功后即时刷新，不发请求）。 */
  function updateMaterialFolder(id: string, folderId: string | null): void {
    const item = materials.value.find((m) => m.id === id);
    if (item) {
      item.folder_id = folderId;
    }
  }

  function updateMaterialStatus(id: string, status: MaterialStatus): void {
    const item = materials.value.find((m) => m.id === id);
    if (item) {
      item.status = status;
    }
  }

  function setActiveMaterial(materialId: string | null, versionId: string | null = null): void {
    activeMaterialId.value = materialId;
    activeVersionId.value = versionId;
  }

  function setCurrentMaterialId(id: string | null): void {
    setActiveMaterial(id);
  }

  function setKnowledgeTree(nodes: KnowledgeTreeNode[]): void {
    currentKnowledgeTree.value = [...nodes];
  }

  function clearKnowledgeTree(): void {
    currentKnowledgeTree.value = [];
  }

  function toggleKnowledgeSelection(id: string): void {
    const index = selectedKnowledgeIds.value.indexOf(id);
    if (index > -1) {
      selectedKnowledgeIds.value.splice(index, 1);
    } else {
      selectedKnowledgeIds.value.push(id);
    }
  }

  function toggleKnowledgeSubtree(ids: string[], select: boolean): void {
    const currentSet = new Set(selectedKnowledgeIds.value);
    if (select) {
      for (const id of ids) {
        currentSet.add(id);
      }
    } else {
      for (const id of ids) {
        currentSet.delete(id);
      }
    }
    selectedKnowledgeIds.value = Array.from(currentSet);
  }

  function selectAllKnowledge(allIds: string[]): void {
    selectedKnowledgeIds.value = [...allIds];
  }

  function clearKnowledgeSelection(): void {
    selectedKnowledgeIds.value = [];
  }

  /**
   * Clear all knowledge-related state (tree, selection, collapse map) without
   * touching material identity. Used when entering a different material so
   * stale考点 selection / collapse state cannot leak across materials.
   */
  function clearKnowledgeState(): void {
    currentKnowledgeTree.value = [];
    selectedKnowledgeIds.value = [];
    knowledgeTreeCollapsedMap.value = {};
  }

  function toggleNodeCollapse(id: string): void {
    knowledgeTreeCollapsedMap.value = {
      ...knowledgeTreeCollapsedMap.value,
      [id]: !knowledgeTreeCollapsedMap.value[id],
    };
  }

  function reset(): void {
    materials.value = [];
    activeMaterialId.value = null;
    activeVersionId.value = null;
    currentKnowledgeTree.value = [];
    selectedKnowledgeIds.value = [];
    knowledgeTreeCollapsedMap.value = {};
  }

  function resetMaterialState(): void {
    reset();
  }

  return {
    materials,
    activeMaterialId,
    activeVersionId,
    currentKnowledgeTree,
    knowledgeTree,
    selectedKnowledgeIds,
    knowledgeTreeCollapsedMap,
    materialsList,
    currentMaterialId,
    activeVersion,
    currentMaterial,
    selectedCount,
    isAnyKnowledgeSelected,
    hasLowConfidenceNode,
    unclassifiedMaterials,
    setMaterials,
    setMaterialsList,
    addMaterial,
    appendMaterialsList,
    removeMaterial,
    updateMaterialFolder,
    updateMaterialStatus,
    setActiveMaterial,
    setCurrentMaterialId,
    setKnowledgeTree,
    clearKnowledgeTree,
    toggleKnowledgeSelection,
    toggleKnowledgeSubtree,
    selectAllKnowledge,
    clearKnowledgeSelection,
    clearKnowledgeState,
    toggleNodeCollapse,
    reset,
    resetMaterialState,
  };
});

export default useMaterialStore;
