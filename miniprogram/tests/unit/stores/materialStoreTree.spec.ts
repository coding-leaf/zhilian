import { describe, it, expect, beforeEach } from 'vitest';
import { setActivePinia, createPinia } from 'pinia';
import { useMaterialStore } from '@/stores/materialStore';
import type { KnowledgeTreeNode } from '@/types/material';

describe('MaterialStore Knowledge Tree & Selection Extensions', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  const mockTree: KnowledgeTreeNode[] = [
    {
      id: 'node-1',
      name: 'Chapter 1: Principles',
      level: 1,
      is_low_confidence: false,
      children: [
        {
          id: 'node-1-1',
          name: 'Section 1.1: Core Concepts',
          level: 2,
          is_low_confidence: true,
          parent_id: 'node-1',
        },
      ],
    },
    {
      id: 'node-2',
      name: 'Chapter 2: Practices',
      level: 1,
      is_low_confidence: false,
      children: [],
    },
  ];

  it('should initialize with empty tree and selection states', () => {
    const store = useMaterialStore();
    expect(store.currentKnowledgeTree).toEqual([]);
    expect(store.knowledgeTree).toEqual([]);
    expect(store.selectedKnowledgeIds).toEqual([]);
    expect(store.selectedCount).toBe(0);
    expect(store.isAnyKnowledgeSelected).toBe(false);
    expect(store.hasLowConfidenceNode).toBe(false);
    expect(store.knowledgeTreeCollapsedMap).toEqual({});
  });

  it('should set and clear knowledge tree correctly', () => {
    const store = useMaterialStore();
    store.setKnowledgeTree(mockTree);
    expect(store.currentKnowledgeTree).toHaveLength(2);
    expect(store.knowledgeTree).toHaveLength(2);
    expect(store.hasLowConfidenceNode).toBe(true);

    store.clearKnowledgeTree();
    expect(store.currentKnowledgeTree).toEqual([]);
    expect(store.knowledgeTree).toEqual([]);
    expect(store.hasLowConfidenceNode).toBe(false);
  });

  it('should toggle knowledge point selection properly', () => {
    const store = useMaterialStore();
    store.toggleKnowledgeSelection('node-1');
    expect(store.selectedKnowledgeIds).toEqual(['node-1']);
    expect(store.selectedCount).toBe(1);
    expect(store.isAnyKnowledgeSelected).toBe(true);

    store.toggleKnowledgeSelection('node-2');
    expect(store.selectedKnowledgeIds).toEqual(['node-1', 'node-2']);
    expect(store.selectedCount).toBe(2);

    // Toggle off
    store.toggleKnowledgeSelection('node-1');
    expect(store.selectedKnowledgeIds).toEqual(['node-2']);
    expect(store.selectedCount).toBe(1);
  });

  it('should select all knowledge points and clear selection', () => {
    const store = useMaterialStore();
    store.selectAllKnowledge(['node-1', 'node-1-1', 'node-2']);
    expect(store.selectedKnowledgeIds).toHaveLength(3);
    expect(store.selectedCount).toBe(3);
    expect(store.isAnyKnowledgeSelected).toBe(true);

    store.clearKnowledgeSelection();
    expect(store.selectedKnowledgeIds).toEqual([]);
    expect(store.selectedCount).toBe(0);
    expect(store.isAnyKnowledgeSelected).toBe(false);
  });

  it('should toggle node collapse map correctly', () => {
    const store = useMaterialStore();
    expect(store.knowledgeTreeCollapsedMap['node-1']).toBeUndefined();

    store.toggleNodeCollapse('node-1');
    expect(store.knowledgeTreeCollapsedMap['node-1']).toBe(true);

    store.toggleNodeCollapse('node-1');
    expect(store.knowledgeTreeCollapsedMap['node-1']).toBe(false);
  });

  it('should reset all tree and selection state on store reset', () => {
    const store = useMaterialStore();
    store.setKnowledgeTree(mockTree);
    store.selectAllKnowledge(['node-1', 'node-2']);
    store.toggleNodeCollapse('node-1');

    store.reset();

    expect(store.currentKnowledgeTree).toEqual([]);
    expect(store.selectedKnowledgeIds).toEqual([]);
    expect(store.knowledgeTreeCollapsedMap).toEqual({});
    expect(store.selectedCount).toBe(0);
    expect(store.hasLowConfidenceNode).toBe(false);
  });
});
