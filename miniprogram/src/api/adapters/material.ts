import type { MaterialItem, MaterialStatus } from '@/types'

const MATERIAL_STATUSES: MaterialStatus[] = [
  'pending',
  'parsing',
  'ready',
  'failed',
  'retake_required',
]

/** 资料状态归一化：后端可能返回大写枚举，统一为小写状态机取值。 */
export function adaptMaterial<T extends MaterialItem>(item: T): T {
  const raw = String(item?.status ?? '').toLowerCase()
  const status = (MATERIAL_STATUSES as string[]).includes(raw)
    ? (raw as MaterialStatus)
    : 'pending'
  return { ...item, status }
}
