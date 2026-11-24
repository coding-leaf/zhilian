import { useBackgroundTaskStore } from '@/stores/backgroundTask'
import { MAX_PRACTICE_QUESTIONS, type QuestionGenerationJob } from '@/types'
import { validateWrongRegenerateInput } from './practiceHelpers'

export interface WrongRegenerateScope {
  folderId?: string
  materialId?: string
}

export interface StartWrongRegenerateOptions {
  knowledgePointIds: string[]
  scope: WrongRegenerateScope
  sourcePracticeId?: string
  practiceTitle?: string
}

/**
 * 基于单一课程或资料范围内的错题知识点发起后台异步再生练习任务。
 * 后端 Worker 出题完成后原子建卷并写入 `result_practice_id`，前端仅在顶部任务条提醒，不强制跳转。
 */
export async function startWrongRegenerateJob(
  options: StartWrongRegenerateOptions,
): Promise<QuestionGenerationJob> {
  validateWrongRegenerateInput(options.knowledgePointIds, options.scope)
  const uniqueKpIds = Array.from(new Set(options.knowledgePointIds.filter(Boolean))).slice(
    0,
    MAX_PRACTICE_QUESTIONS,
  )
  if (uniqueKpIds.length === 0) {
    throw new Error('未提供错题知识点')
  }
  const taskStore = useBackgroundTaskStore()
  return taskStore.startQuestionJob({
    folder_id: options.scope.folderId,
    material_id: options.scope.folderId ? undefined : options.scope.materialId,
    knowledge_point_ids: uniqueKpIds,
    count: Math.min(MAX_PRACTICE_QUESTIONS, Math.max(3, uniqueKpIds.length)),
    difficulty: 3,
    auto_create_practice: true,
    practice_title: options.practiceTitle || '错题巩固练习',
    source_type: 'wrong_record',
    ...(options.sourcePracticeId ? { source_practice_id: options.sourcePracticeId } : {}),
  })
}
