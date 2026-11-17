import { request, uploadFile } from '@/utils/request'
import type {
  MaterialItem,
  MaterialListQuery,
  MaterialListResult,
  MaterialStatistics,
} from '@/types'
import { adaptMaterial } from '../adapters'

export function apiGetMaterialStatistics(): Promise<MaterialStatistics> {
  return request<MaterialStatistics>({
    url: '/materials/statistics',
    method: 'GET',
  })
}

export function apiUploadMaterial(
  filePath: string,
  title?: string,
  folderId?: string,
): Promise<MaterialItem> {
  const formData: Record<string, string> = {}
  if (title) formData.title = title
  if (folderId) formData.folder_id = folderId
  return uploadFile<MaterialItem>(filePath, 'file', formData).then(adaptMaterial)
}

export function apiGetMaterialDetail(id: string): Promise<MaterialItem> {
  return request<MaterialItem>({
    url: `/materials/${id}`,
    method: 'GET',
  }).then(adaptMaterial)
}

/**
 * 软删除资料（后端置 is_deleted=True，**保留历史作答记录**）。
 *
 * 刻意不透出后端响应里的 `message`：它写的是「资料已移至回收站」，而**根本没有恢复接口**，
 * 照显示就是骗用户。要显示文案请用调用方自己的措辞。
 */
export function apiDeleteMaterial(id: string): Promise<{ material_id: string; is_deleted: boolean }> {
  return request<{ material_id: string; is_deleted: boolean; permanent: boolean; message: string }>({
    url: `/materials/${id}`,
    method: 'DELETE',
  }).then((res) => ({ material_id: res.material_id, is_deleted: res.is_deleted }))
}

export function apiGetMaterialList(params?: MaterialListQuery): Promise<MaterialItem[]> {
  let url = '/materials'
  const queryParts: string[] = []
  if (params?.folder_id) queryParts.push(`folder_id=${encodeURIComponent(params.folder_id)}`)
  if (params?.status) queryParts.push(`status=${encodeURIComponent(params.status)}`)
  if (queryParts.length > 0) url += `?${queryParts.join('&')}`

  return request<MaterialListResult | MaterialItem[]>({
    url,
    method: 'GET',
  }).then((res) => {
    if (res && 'items' in res) {
      return res.items.map(adaptMaterial)
    }
    return ((res as MaterialItem[]) || []).map(adaptMaterial)
  })
}

export function apiTriggerMaterialParse(materialId: string): Promise<{ message: string }> {
  return request({
    url: `/materials/${materialId}/parse`,
    method: 'POST',
  })
}
