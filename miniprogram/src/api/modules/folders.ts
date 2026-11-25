import { request } from '@/utils/request'
import type {
  FolderItem,
  FolderKnowledgePointsResult,
  FolderListResult,
} from '@/types'

export function apiListFolders(includeArchived = false): Promise<FolderListResult> {
  return request<FolderListResult>({
    url: `/folders?include_archived=${includeArchived}`,
    method: 'GET',
  })
}

export function apiCreateFolder(name: string): Promise<FolderItem> {
  return request<FolderItem>({
    url: '/folders',
    method: 'POST',
    data: { name },
  })
}

export function apiRenameFolder(folderId: string, name: string): Promise<FolderItem> {
  return request<FolderItem>({
    url: `/folders/${folderId}`,
    method: 'PUT',
    data: { name },
  })
}

export function apiArchiveFolder(folderId: string): Promise<{ id: string; is_deleted: boolean }> {
  return request({
    url: `/folders/${folderId}`,
    method: 'DELETE',
  })
}

export function apiGetFolderKnowledgePoints(folderId: string): Promise<FolderKnowledgePointsResult> {
  return request<FolderKnowledgePointsResult>({
    url: `/folders/${folderId}/knowledge-points`,
    method: 'GET',
  })
}
