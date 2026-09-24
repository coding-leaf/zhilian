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

  function selectAllKnowledge(allIds: string[]): void {
    selectedKnowledgeIds.value = [...allIds];
  }

  function clearKnowledgeSelection(): void {
    selectedKnowledgeIds.value = [];
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
    setMaterials,
    setMaterialsList,
    addMaterial,
    appendMaterialsList,
    updateMaterialStatus,
    setActiveMaterial,
    setCurrentMaterialId,
    setKnowledgeTree,
    clearKnowledgeTree,
    toggleKnowledgeSelection,
    selectAllKnowledge,
    clearKnowledgeSelection,
    toggleNodeCollapse,
    reset,
    resetMaterialState,
  };
});

export default useMaterialStore;
