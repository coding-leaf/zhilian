import { describe, it, expect, vi, beforeEach } from 'vitest';
import * as requestModule from '@/utils/request';
import {
  fetchFolderList,
  fetchFolderDetail,
  createFolder,
  renameFolder,
  archiveFolder,
  restoreFolder,
} from '@/api/folder';

describe('Folder API Module', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('fetchFolderList calls GET /api/v1/folders with include_archived', async () => {
    const requestSpy = vi
      .spyOn(requestModule, 'request')
      .mockResolvedValue({ code: 0, message: 'success', data: { items: [], total: 0 } });

    await fetchFolderList({ include_archived: true });

    expect(requestSpy).toHaveBeenCalledWith({
      url: '/api/v1/folders',
      method: 'GET',
      data: { include_archived: true },
    });
  });

  it('fetchFolderList omits data when no params are provided', async () => {
    const requestSpy = vi
      .spyOn(requestModule, 'request')
      .mockResolvedValue({ code: 0, message: 'success', data: { items: [], total: 0 } });

    await fetchFolderList();

    expect(requestSpy).toHaveBeenCalledWith({
      url: '/api/v1/folders',
      method: 'GET',
      data: undefined,
    });
  });

  it('fetchFolderDetail calls GET /api/v1/folders/:id', async () => {
    const requestSpy = vi
      .spyOn(requestModule, 'request')
      .mockResolvedValue({ code: 0, message: 'success', data: {} });

    await fetchFolderDetail('f1');

    expect(requestSpy).toHaveBeenCalledWith({
      url: '/api/v1/folders/f1',
      method: 'GET',
    });
  });

  it('createFolder posts the name payload', async () => {
    const requestSpy = vi
      .spyOn(requestModule, 'request')
      .mockResolvedValue({ code: 0, message: 'success', data: {} });

    await createFolder({ name: '高等数学' });

    expect(requestSpy).toHaveBeenCalledWith({
      url: '/api/v1/folders',
      method: 'POST',
      data: { name: '高等数学' },
    });
  });

  it('renameFolder patches the name payload', async () => {
    const requestSpy = vi
      .spyOn(requestModule, 'request')
      .mockResolvedValue({ code: 0, message: 'success', data: {} });

    await renameFolder('f1', { name: '线性代数' });

    expect(requestSpy).toHaveBeenCalledWith({
      url: '/api/v1/folders/f1',
      method: 'PATCH',
      data: { name: '线性代数' },
    });
  });

  it('archiveFolder deletes the folder and returns the purge window', async () => {
    const requestSpy = vi.spyOn(requestModule, 'request').mockResolvedValue({
      code: 0,
      message: 'success',
      data: { id: 'f1', is_deleted: true, purge_after: '2026-10-04T00:00:00Z', message: 'ok' },
    });

    const res = await archiveFolder('f1');

    expect(requestSpy).toHaveBeenCalledWith({
      url: '/api/v1/folders/f1',
      method: 'DELETE',
    });
    expect(res.data.purge_after).toBe('2026-10-04T00:00:00Z');
  });

  it('restoreFolder posts to the restore endpoint', async () => {
    const requestSpy = vi
      .spyOn(requestModule, 'request')
      .mockResolvedValue({ code: 0, message: 'success', data: {} });

    await restoreFolder('f1');

    expect(requestSpy).toHaveBeenCalledWith({
      url: '/api/v1/folders/f1/restore',
      method: 'POST',
    });
  });
});
