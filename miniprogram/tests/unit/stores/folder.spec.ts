import { describe, it, expect, beforeEach } from 'vitest';
import { setActivePinia, createPinia } from 'pinia';
import { useFolderStore } from '@/stores/folderStore';
import type { FolderItem } from '@/types/folder';

function makeFolder(id: string, overrides: Partial<FolderItem> = {}): FolderItem {
  return {
    id,
    name: `课程-${id}`,
    is_archived: false,
    material_count: 0,
    ready_material_count: 0,
    knowledge_point_count: 0,
    question_count: 0,
    created_at: '2026-09-20T00:00:00Z',
    ...overrides,
  };
}

describe('folderStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it('setFolderList splits active and archived courses in one pass', () => {
    const store = useFolderStore();
    store.setFolderList([
      makeFolder('a'),
      makeFolder('b', { is_archived: true, archived_at: '2026-09-27T00:00:00Z' }),
    ]);

    expect(store.folders.map((f) => f.id)).toEqual(['a']);
    expect(store.archivedFolders.map((f) => f.id)).toEqual(['b']);
    expect(store.archivedCount).toBe(1);
  });

  it('upsertFolder inserts new folders and replaces existing ones', () => {
    const store = useFolderStore();
    store.setFolders([makeFolder('a', { name: '旧名' })]);

    store.upsertFolder(makeFolder('a', { name: '新名' }));
    expect(store.folders).toHaveLength(1);
    expect(store.folders[0].name).toBe('新名');

    store.upsertFolder(makeFolder('b'));
    expect(store.folders.map((f) => f.id)).toEqual(['b', 'a']);
  });

  it('removeFolder clears the folder from both lists and the current selection', () => {
    const store = useFolderStore();
    store.setFolders([makeFolder('a')]);
    store.setArchivedFolders([makeFolder('z', { is_archived: true })]);
    store.setCurrentFolder(makeFolder('a'));

    store.removeFolder('a');
    store.removeFolder('z');

    expect(store.folders).toHaveLength(0);
    expect(store.archivedFolders).toHaveLength(0);
    expect(store.currentFolder).toBeNull();
  });

  it('setUnclassifiedCount clamps negatives and drives hasUnclassified', () => {
    const store = useFolderStore();
    store.setUnclassifiedCount(-3);
    expect(store.unclassifiedCount).toBe(0);
    expect(store.hasUnclassified).toBe(false);

    store.setUnclassifiedCount(2);
    expect(store.unclassifiedCount).toBe(2);
    expect(store.hasUnclassified).toBe(true);
  });

  it('reset clears all course state', () => {
    const store = useFolderStore();
    store.setFolders([makeFolder('a')]);
    store.setArchivedFolders([makeFolder('z', { is_archived: true })]);
    store.setUnclassifiedCount(5);
    store.setCurrentFolder(makeFolder('a'));

    store.reset();

    expect(store.folders).toHaveLength(0);
    expect(store.archivedFolders).toHaveLength(0);
    expect(store.unclassifiedCount).toBe(0);
    expect(store.currentFolder).toBeNull();
  });
});
