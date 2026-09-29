import { ref, type Ref } from 'vue'
import { describeFailure } from '@/utils/requestError'

/**
 * 资料删除的交互编排（工作台资料卡）。
 *
 * 抽成页面本地 composable 而非内联在页面里，原因有两条：
 * 1. `pages/index/index.vue` 已 865 行（超 `docs/DESIGN.md` §6 的 300 行约定，属既有偏离），
 *    不该再往里堆逻辑；
 * 2. 内联在页面里的分支（取消 / 失败 / 连点）在当前测试策略下不可测——本仓库不做组件挂载测试。
 *    抽出来就能像 `useWrongMarking` 一样直接被用例驱动。
 */

/** 删除确认文案。**刻意不提「回收站」**：后端没有恢复接口，说了就是空头承诺。 */
export function buildMaterialDeleteConfirmContent(title?: string | null): string {
  return `删除「${title || '无标题资料'}」？删除后不再显示。历史作答记录会保留，但当前无法在应用内恢复。`
}

export interface MaterialDeleteApi {
  /** 软删除资料；失败必须抛出，不得吞掉。 */
  deleteMaterial: (id: string) => Promise<void>
}

export interface MaterialDeleteController {
  /** 正在删除的资料 id；为空表示空闲。兼作连点守卫。 */
  deletingId: Ref<string>
  requestDelete: (item: { id: string; title?: string | null }) => void
}

export function useMaterialDelete(api: MaterialDeleteApi): MaterialDeleteController {
  const deletingId = ref('')

  const requestDelete = (item: { id: string; title?: string | null }): void => {
    // 连点守卫：在途时直接忽略，不弹第二个确认框
    if (deletingId.value) return
    uni.showModal({
      title: '删除资料',
      content: buildMaterialDeleteConfirmContent(item.title),
      confirmText: '删除',
      confirmColor: '#b91c1c',
      success: async ({ confirm }) => {
        if (!confirm) return
        deletingId.value = item.id
        try {
          await api.deleteMaterial(item.id)
          uni.showToast({ title: '资料已删除', icon: 'success' })
        } catch (error) {
          // 失败必须可见：吞掉会让「删除失败」与「已删除」在界面上长得一样
          console.error('Failed to delete material', error)
          uni.showToast({ title: describeFailure(error, '删除失败，请重试'), icon: 'none' })
        } finally {
          deletingId.value = ''
        }
      },
    })
  }

  return { deletingId, requestDelete }
}
