import { describe, it, expect, vi, beforeEach } from 'vitest';
import * as requestModule from '@/utils/request';
import * as uploadModule from '@/utils/upload';
import {
  fetchMaterialList,
  fetchMaterialDetail,
  fetchMaterialStatus,
  deleteMaterial,
  retryMaterial,
  fetchKnowledgeTree,
  uploadMaterial,
  retakeMaterialPage,
  uploadMaterialFile,
  reshootMaterialPage,
  fetchMaterialOCRPages,
} from '@/api/material';

describe('Material API Module', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('should call fetchMaterialList with GET /api/v1/materials and query params', async () => {
    const mockResponse = {
      code: 0,
      message: 'success',
      data: {
        items: [
          {
            id: 'mat_001',
            title: 'Computer Network',
            file_format: 'pdf',
            file_size: 1024,
            source_type: 'local',
            status: 'ready',
            created_at: '2026-01-01T00:00:00Z',
          },
        ],
        total: 1,
        limit: 20,
        offset: 0,
      },
    };
    const requestSpy = vi.spyOn(requestModule, 'request').mockResolvedValue(mockResponse);

    const params = { page: 1, page_size: 20, keyword: 'Network', status: 'ready' };
    const res = await fetchMaterialList(params);

    expect(requestSpy).toHaveBeenCalledTimes(1);
    expect(requestSpy).toHaveBeenCalledWith({
      url: '/api/v1/materials',
      method: 'GET',
      data: params,
    });
    expect(res).toEqual(mockResponse);
  });

  it('should call fetchMaterialDetail with GET /api/v1/materials/:id', async () => {
    const mockResponse = {
      code: 0,
      message: 'success',
      data: {
        id: 'mat_001',
        title: 'Computer Network',
        file_format: 'pdf',
        file_size: 1024,
        source_type: 'local',
        status: 'ready',
        created_at: '2026-01-01T00:00:00Z',
      },
    };
    const requestSpy = vi.spyOn(requestModule, 'request').mockResolvedValue(mockResponse);

    const res = await fetchMaterialDetail('mat_001');

    expect(requestSpy).toHaveBeenCalledTimes(1);
    expect(requestSpy).toHaveBeenCalledWith({
      url: '/api/v1/materials/mat_001',
      method: 'GET',
    });
    expect(res).toEqual(mockResponse);
  });

  it('should call fetchMaterialStatus with GET /api/v1/materials/:id', async () => {
    const mockResponse = {
      code: 0,
      message: 'success',
      data: {
        id: 'mat_001',
        title: 'Computer Network',
        file_format: 'pdf',
        file_size: 1024,
        source_type: 'local',
        status: 'parsing',
        created_at: '2026-01-01T00:00:00Z',
      },
    };
    const requestSpy = vi.spyOn(requestModule, 'request').mockResolvedValue(mockResponse);

    const res = await fetchMaterialStatus('mat_001');

    expect(requestSpy).toHaveBeenCalledTimes(1);
    expect(requestSpy).toHaveBeenCalledWith({
      url: '/api/v1/materials/mat_001',
      method: 'GET',
    });
    expect(res).toEqual(mockResponse);
  });

  it('should call deleteMaterial with soft delete by default', async () => {
    const mockResponse = {
      code: 0,
      message: 'success',
      data: { material_id: 'mat_001', is_deleted: true, permanent: false },
    };
    const requestSpy = vi.spyOn(requestModule, 'request').mockResolvedValue(mockResponse);

    const res = await deleteMaterial('mat_001');

    expect(requestSpy).toHaveBeenCalledTimes(1);
    expect(requestSpy).toHaveBeenCalledWith({
      url: '/api/v1/materials/mat_001',
      method: 'DELETE',
    });
    expect(res).toEqual(mockResponse);
  });

  it('should call retryMaterial with POST /api/v1/materials/:id/retry', async () => {
    const mockResponse = {
      code: 0,
      message: 'success',
      data: {
        id: 'mat_001',
        title: 'Computer Network',
        file_format: 'pdf',
        file_size: 1024,
        source_type: 'local',
        status: 'pending',
        created_at: '2026-01-01T00:00:00Z',
      },
    };
    const requestSpy = vi.spyOn(requestModule, 'request').mockResolvedValue(mockResponse);

    const res = await retryMaterial('mat_001');

    expect(requestSpy).toHaveBeenCalledTimes(1);
    expect(requestSpy).toHaveBeenCalledWith({
      url: '/api/v1/materials/mat_001/retry',
      method: 'POST',
    });
    expect(res).toEqual(mockResponse);
  });

  it('should call deleteMaterial with hard delete endpoint when hard is true', async () => {
    const mockResponse = {
      code: 0,
      message: 'success',
      data: { material_id: 'mat_001', is_deleted: true, permanent: true },
    };
    const requestSpy = vi.spyOn(requestModule, 'request').mockResolvedValue(mockResponse);

    const res = await deleteMaterial('mat_001', true);

    expect(requestSpy).toHaveBeenCalledTimes(1);
    expect(requestSpy).toHaveBeenCalledWith({
      url: '/api/v1/materials/mat_001/hard',
      method: 'DELETE',
    });
    expect(res).toEqual(mockResponse);
  });

  it('should call fetchKnowledgeTree with GET /api/v1/materials/:id/knowledge-tree', async () => {
    const mockResponse = {
      code: 0,
      message: 'success',
      data: {
        material_id: 'mat_001',
        version_id: 'ver_001',
        nodes: [
          {
            id: 'node_001',
            title: 'TCP/IP Model',
            level: 1,
            children: [],
          },
        ],
      },
    };
    const requestSpy = vi.spyOn(requestModule, 'request').mockResolvedValue(mockResponse);

    const res = await fetchKnowledgeTree('mat_001', 'ver_001');

    expect(requestSpy).toHaveBeenCalledTimes(1);
    expect(requestSpy).toHaveBeenCalledWith({
      url: '/api/v1/materials/mat_001/knowledge-tree',
      method: 'GET',
      data: { version_id: 'ver_001' },
    });
    expect(res).toEqual(mockResponse);
  });

  it('should call uploadMaterial with POST /api/v1/materials/upload and idempotency key', async () => {
    const mockResponse = {
      code: 0,
      message: 'success',
      data: {
        id: 'mat_002',
        version_id: 'ver_002',
        title: 'Operating Systems',
        file_format: 'pdf',
        file_size: 2048,
        source_type: 'local',
        status: 'pending',
        created_at: '2026-01-01T00:00:00Z',
      },
    };
    const requestSpy = vi.spyOn(requestModule, 'request').mockResolvedValue(mockResponse);

    const res = await uploadMaterial('file-data', 'Operating Systems', 'test-uuid-key');

    expect(requestSpy).toHaveBeenCalledTimes(1);
    expect(requestSpy).toHaveBeenCalledWith({
      url: '/api/v1/materials/upload',
      method: 'POST',
      data: { file: 'file-data', title: 'Operating Systems', source_type: 'local' },
      headers: { 'Idempotency-Key': 'test-uuid-key' },
    });
    expect(res).toEqual(mockResponse);
  });

  it('keeps the caller-provided source_type on non-mini-program upload (MAT-014)', async () => {
    const mockResponse = {
      code: 0,
      message: 'success',
      data: {
        id: 'mat_003',
        version_id: 'ver_003',
        title: 'Wechat Doc',
        file_format: 'pdf',
        file_size: 1024,
        source_type: 'wechat',
        status: 'pending',
        created_at: '2026-01-01T00:00:00Z',
      },
    };
    const requestSpy = vi.spyOn(requestModule, 'request').mockResolvedValue(mockResponse);

    await uploadMaterial('file-data', 'Wechat Doc', 'idem-2', 'wechat');

    expect(requestSpy).toHaveBeenCalledWith({
      url: '/api/v1/materials/upload',
      method: 'POST',
      data: { file: 'file-data', title: 'Wechat Doc', source_type: 'wechat' },
      headers: { 'Idempotency-Key': 'idem-2' },
    });
  });

  it('should call retakeMaterialPage with POST /api/v1/materials/:id/reshoot', async () => {
    const mockResponse = {
      code: 0,
      message: 'success',
      data: {
        material_id: 'mat_002',
        version_id: 'ver_002',
        page_index: 4,
        is_qualified: true,
        reshoot_count: 1,
        parse_status: 'ready',
        unqualified_reason: null,
      },
    };
    const requestSpy = vi.spyOn(requestModule, 'request').mockResolvedValue(mockResponse);

    const res = await retakeMaterialPage('mat_002', 4, 'retake-file-path', 'idemp-key-1');

    expect(requestSpy).toHaveBeenCalledTimes(1);
    expect(requestSpy).toHaveBeenCalledWith({
      url: '/api/v1/materials/mat_002/reshoot',
      method: 'POST',
      data: { page_index: 4, file: 'retake-file-path' },
      headers: { 'Idempotency-Key': 'idemp-key-1' },
    });
    // Contract must match backend MaterialReshootResponse (MAT-007).
    expect(res.data.page_index).toBe(4);
    expect(res.data.is_qualified).toBe(true);
    expect(res.data.reshoot_count).toBe(1);
    expect(res.data.parse_status).toBe('ready');
  });

  it('should use multipart uni.uploadFile for retakeMaterialPage on real device', async () => {
    const uploadSpy = vi.spyOn(uploadModule, 'uploadFile').mockResolvedValue({
      code: 0,
      message: 'success',
      data: {
        material_id: 'mat_002',
        page_index: 4,
        is_qualified: true,
        reshoot_count: 1,
        parse_status: 'ready',
      },
    } as never);

    const originalEnv = process.env.NODE_ENV;
    process.env.NODE_ENV = 'production';
    (globalThis as unknown as { uni: Record<string, unknown> }).uni.uploadFile = vi.fn();
    try {
      await retakeMaterialPage('mat_002', 4, 'wxfile://tmp_page_4.jpg', 'idemp-key-1');
    } finally {
      process.env.NODE_ENV = originalEnv;
    }

    expect(uploadSpy).toHaveBeenCalledTimes(1);
    expect(uploadSpy).toHaveBeenCalledWith({
      url: '/api/v1/materials/mat_002/reshoot',
      filePath: 'wxfile://tmp_page_4.jpg',
      name: 'file',
      formData: { page_index: 4 },
      headers: { 'Idempotency-Key': 'idemp-key-1' },
    });
  });

  it('should call fetchMaterialOCRPages with only_unqualified filter', async () => {
    const mockResponse = {
      code: 0,
      message: 'success',
      data: {
        material_id: 'mat_002',
        version_id: 'ver_002',
        items: [
          {
            page_number: 3,
            is_qualified: false,
            reshoot_count: 1,
            unqualified_reason: '乱码率过高',
          },
        ],
      },
    };
    const requestSpy = vi.spyOn(requestModule, 'request').mockResolvedValue(mockResponse);

    const res = await fetchMaterialOCRPages('mat_002', true);

    expect(requestSpy).toHaveBeenCalledTimes(1);
    expect(requestSpy).toHaveBeenCalledWith({
      url: '/api/v1/materials/mat_002/ocr-pages',
      method: 'GET',
      data: { only_unqualified: true },
    });
    expect(res).toEqual(mockResponse);
  });

  it('should support uploadMaterialFile and reshootMaterialPage alias wrappers', async () => {
    const uploadRes = {
      code: 0,
      message: 'success',
      data: { id: 'm1', version_id: 'v1', status: 'pending' },
    };
    const reshootRes = {
      code: 0,
      message: 'success',
      data: { material_id: 'm1', page_index: 2, is_qualified: true, reshoot_count: 1 },
    };
    const requestSpy = vi
      .spyOn(requestModule, 'request')
      .mockResolvedValueOnce(uploadRes)
      .mockResolvedValueOnce(reshootRes);

    await uploadMaterialFile({
      filePath: 'test.pdf',
      title: 'Doc',
      idempotencyKey: 'idemp-1',
    });
    await reshootMaterialPage({
      materialId: 'm1',
      pageIndex: 2,
      filePath: 'reshoot.jpg',
      versionId: 'v1',
      idempotencyKey: 'idemp-2',
    });

    expect(requestSpy).toHaveBeenCalledTimes(2);
  });
});
