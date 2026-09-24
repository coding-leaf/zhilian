import { describe, it, expect, beforeEach } from 'vitest';
import { setActivePinia, createPinia } from 'pinia';
import { useMaterialStore } from '@/stores/materialStore';
import type { MaterialItem, KnowledgeTreeNode } from '@/types/material';

describe('MaterialStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  const mockMaterial1: MaterialItem = {
    id: 'mat-001',
    title: 'Operating Systems Chapter 1',
    file_format: 'pdf',
    file_size: 102400,
    source_type: 'upload',
    status: 'ready',
    current_version_id: 'ver-001',
    versions_count: 1,
    created_at: '2026-09-01T10:00:00Z',
  };

  const mockMaterial2: MaterialItem = {
    id: 'mat-002',
    title: 'Computer Networks Chapter 2',
    file_format: 'docx',
    file_size: 204800,
    source_type: 'upload',
    status: 'pending',
    current_version_id: null,
    versions_count: 0,
    created_at: '2026-09-02T10:00:00Z',
  };

  const mockKnowledgeTree: KnowledgeTreeNode[] = [
    {
      id: 'kn-001',
      title: 'Process Management',
      level: 1,
      children: [
        {
          id: 'kn-002',
          title: 'Process vs Thread',
          level: 2,
          parent_id: 'kn-001',
        },
      ],
    },
  ];

  it('should initialize with default empty state', () => {
    const store = useMaterialStore();
    expect(store.materials).toEqual([]);
    expect(store.activeMaterialId).toBeNull();
    expect(store.activeVersionId).toBeNull();
    expect(store.currentKnowledgeTree).toEqual([]);
    expect(store.currentMaterial).toBeNull();
  });

  it('should set materials list and derive currentMaterial getter', () => {
    const store = useMaterialStore();
    store.setMaterials([mockMaterial1, mockMaterial2]);

    expect(store.materials).toHaveLength(2);
    expect(store.materials[0].id).toBe('mat-001');

    store.setActiveMaterial('mat-001', 'ver-001');
    expect(store.activeMaterialId).toBe('mat-001');
    expect(store.activeVersionId).toBe('ver-001');
    expect(store.currentMaterial?.id).toBe('mat-001');
    expect(store.currentMaterial?.title).toBe('Operating Systems Chapter 1');
  });

  it('should add a new material to the list or update existing one', () => {
    const store = useMaterialStore();
    store.addMaterial(mockMaterial1);
    expect(store.materials).toHaveLength(1);

    // Adding same material updates it
    const updated1: MaterialItem = { ...mockMaterial1, title: 'Updated Title' };
    store.addMaterial(updated1);
    expect(store.materials).toHaveLength(1);
    expect(store.materials[0].title).toBe('Updated Title');

    // Adding different material appends
    store.addMaterial(mockMaterial2);
    expect(store.materials).toHaveLength(2);
  });

  it('should update material status', () => {
    const store = useMaterialStore();
    store.setMaterials([mockMaterial1, mockMaterial2]);

    store.updateMaterialStatus('mat-002', 'ready');
    const updated = store.materials.find((m) => m.id === 'mat-002');
    expect(updated?.status).toBe('ready');
  });

  it('should set current knowledge tree', () => {
    const store = useMaterialStore();
    store.setKnowledgeTree(mockKnowledgeTree);

    expect(store.currentKnowledgeTree).toHaveLength(1);
    expect(store.currentKnowledgeTree[0].title).toBe('Process Management');
    expect(store.currentKnowledgeTree[0].children?.[0].title).toBe('Process vs Thread');
  });

  it('should reset all material state cleanly', () => {
    const store = useMaterialStore();
    store.setMaterials([mockMaterial1]);
    store.setActiveMaterial('mat-001', 'ver-001');
    store.setKnowledgeTree(mockKnowledgeTree);

    store.reset();

    expect(store.materials).toEqual([]);
    expect(store.activeMaterialId).toBeNull();
    expect(store.activeVersionId).toBeNull();
    expect(store.currentKnowledgeTree).toEqual([]);
    expect(store.currentMaterial).toBeNull();
  });
});
