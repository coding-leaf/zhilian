import type {
  AttemptResult,
  DiagnosisReport,
  PracticeSession,
  QuestionOption,
  QuestionType,
} from '@/types'
import { optionDisplayText, optionKey, questionTypeLabel } from '@/api'
import { weakPointId, weakPointName } from '@/api/adapters/diagnosis'
import { isGarbledSnippetText } from '@/utils/richText'

const TF_TRUE = new Set(['正确', '对', '是', 'TRUE', 'T', 'YES', 'Y', '1', 'V', '√', 'A'])
const TF_FALSE = new Set(['错误', '错', '否', 'FALSE', 'F', 'NO', 'N', '0', 'X', '×', 'B'])

export function normalizeReportTrueFalse(raw: unknown): '正确' | '错误' | '' {
  if (typeof raw === 'boolean') return raw ? '正确' : '错误'
  if (raw === undefined || raw === null) return ''
  const cleaned = String(raw)
    .trim()
    .replace(/^[()[\]{}<>、.:：\s]+|[()[\]{}<>、.:：\s]+$/g, '')
    .toUpperCase()
  if (!cleaned) return ''
  if (TF_TRUE.has(cleaned)) return '正确'
  if (TF_FALSE.has(cleaned)) return '错误'
  return ''
}

export function formatAnswer(value: unknown): string {
  if (value === undefined || value === null || value === '') return '未作答'
  if (Array.isArray(value)) return value.length ? value.join('、') : '未作答'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

/** 按题型格式化展示作答或标准答案（判断题归一化为「正确/错误」、多选展开 JSON、填空美化等价分隔）。 */
export function formatAttemptAnswer(value: unknown, questionType?: QuestionType | string): string {
  if (value === undefined || value === null || value === '') return '未作答'
  if (questionType === 'true_false') {
    const tf = normalizeReportTrueFalse(value)
    return tf || formatAnswer(value)
  }
  if (questionType === 'multiple_choice') {
    if (Array.isArray(value)) return value.length ? value.join('、') : '未作答'
    if (typeof value === 'string') {
      const trimmed = value.trim()
      if (trimmed.startsWith('[') && trimmed.endsWith(']')) {
        try {
          const parsed = JSON.parse(trimmed)
          if (Array.isArray(parsed)) return parsed.length ? parsed.join('、') : '未作答'
        } catch {
          // fallback
        }
      }
      if (/^[A-Za-z](?:[,，、\s]+[A-Za-z])+$/.test(trimmed)) {
        return trimmed
          .split(/[,，、\s]+/)
          .map((s) => s.trim().toUpperCase())
          .filter(Boolean)
          .join('、')
      }
    }
  }
  if (questionType === 'fill_in_blank' && typeof value === 'string') {
    return value
      .split(/\s*(?:[;；\n]|&&)\s*/)
      .filter((part) => part.trim())
      .map((part) =>
        part
          .split(/\s*(?:\|\|\||\|\||\/\/\/|\|)\s*/)
          .filter((alt) => alt.trim())
          .join(' 或 '),
      )
      .join(' ； ')
  }
  return formatAnswer(value)
}

export type OptionVisualTone = 'correct' | 'wrong' | 'missed' | 'neutral'

function extractSelectionKeys(value: unknown, questionType?: QuestionType | string): string[] {
  if (value === undefined || value === null || value === '') return []
  if (questionType === 'true_false') {
    const tf = normalizeReportTrueFalse(value)
    return tf ? [tf] : []
  }
  if (Array.isArray(value)) return value.map((v) => String(v).trim().toUpperCase()).filter(Boolean)
  if (typeof value === 'string') {
    const trimmed = value.trim()
    if (trimmed.startsWith('[') && trimmed.endsWith(']')) {
      try {
        const parsed = JSON.parse(trimmed)
        if (Array.isArray(parsed)) {
          return parsed.map((v) => String(v).trim().toUpperCase()).filter(Boolean)
        }
      } catch {
        // fallback
      }
    }
    if (questionType === 'multiple_choice') {
      if (/^[A-Za-z]+$/.test(trimmed) && trimmed.length > 1) {
        return trimmed.toUpperCase().split('')
      }
      return trimmed
        .split(/[,，、\s]+/)
        .map((v) => v.trim().toUpperCase())
        .filter(Boolean)
    }
    return [trimmed.toUpperCase()]
  }
  return []
}

/** 判定逐题选项卡的视觉状态（选对 / 选错 / 漏选 / 未选）。 */
export function resolveOptionTone(
  option: QuestionOption,
  index: number,
  result: AttemptResult,
): OptionVisualTone {
  if (result.gradingStatus !== 'graded') return 'neutral'
  const keyToken =
    result.type === 'true_false'
      ? normalizeReportTrueFalse(option.content) || normalizeReportTrueFalse(option.key)
      : optionKey(option, index).toUpperCase()
  if (!keyToken) return 'neutral'

  const userKeys = extractSelectionKeys(result.userAnswer, result.type)
  const correctKeys = extractSelectionKeys(result.correctAnswer, result.type)
  const inUser = userKeys.includes(keyToken)
  const inCorrect = correctKeys.includes(keyToken)

  if (inUser && inCorrect) return 'correct'
  if (inUser && !inCorrect) return 'wrong'
  if (!inUser && inCorrect) return 'missed'
  return 'neutral'
}

export function formatOptionText(option: QuestionOption, index: number): string {
  return option.content?.trim() ? option.content : optionDisplayText(option, index)
}

export interface SourceQuoteView {
  visible: boolean
  isGarbled: boolean
  content: string
}

/** 统一校验原文切片是否包含历史 PDF 符号乱码，防止直出 `AB&A&` 等噪声。 */
export function resolveSourceQuoteView(sourceQuote?: string | null): SourceQuoteView {
  const raw = typeof sourceQuote === 'string' ? sourceQuote.trim() : ''
  if (!raw) return { visible: false, isGarbled: false, content: '' }
  if (isGarbledSnippetText(raw)) {
    return { visible: true, isGarbled: true, content: '' }
  }
  return { visible: true, isGarbled: false, content: raw }
}

export function formatScore(score: number | null, maxScore: number): string {
  if (score === null) return `—/${maxScore}`
  return `${score}/${maxScore}`
}

export function formatPercent(rate: number): string {
  return `${Math.round(rate * 100)}%`
}

export interface ResultBadge {
  text: string
  tone: 'correct' | 'wrong' | 'pending' | 'unanswered'
}

/** 待判 / 待重判 / 未作答的题目不得显示为零分或答错。 */
export function resolveResultBadge(result: AttemptResult): ResultBadge {
  if (!result.isAnswered) return { text: '未作答', tone: 'unanswered' }
  if (result.gradingStatus === 'grading') return { text: '判题中', tone: 'pending' }
  if (result.gradingStatus === 'pending_regrade') return { text: '待重判', tone: 'pending' }
  if (result.isCorrect === null) return { text: '判题中', tone: 'pending' }
  return result.isCorrect
    ? { text: `正确 ${formatScore(result.score, result.maxScore)}`, tone: 'correct' }
    : { text: `错误 ${formatScore(result.score, result.maxScore)}`, tone: 'wrong' }
}

export function typeLabel(type: QuestionType | string): string {
  return questionTypeLabel(type)
}

/** 错题再生用的考点 ID：优先诊断报告薄弱点，其次逐题结果。 */
export function collectWrongKnowledgePointIds(
  report: DiagnosisReport | null,
  results: AttemptResult[],
): string[] {
  const ids = new Set<string>()
  for (const point of report?.weak_knowledge_points || []) {
    const id = weakPointId(point)
    if (id) ids.add(id)
  }
  if (ids.size === 0) {
    for (const result of results) {
      if (result.isCorrect === false && result.knowledgePointId) ids.add(result.knowledgePointId)
    }
  }
  return Array.from(ids)
}

export interface WeakPointView {
  id?: string
  name: string
  masteryRate: number
  reason: string
  suggestion: string
}

export function buildWeakPointViews(report: DiagnosisReport | null): WeakPointView[] {
  return (report?.weak_knowledge_points || []).map((point) => ({
    id: weakPointId(point),
    name: weakPointName(point),
    masteryRate: point.current_score,
    reason: point.cause_explanation || point.cause_type || '暂无归因说明',
    suggestion: point.actionable_advice || '建议针对性复习后再次练习',
  }))
}

/** 再生题范围来自练习详情本身，不再让页面猜测归属。 */
export function resolveSessionScope(session: PracticeSession | null) {
  return {
    folderId: session?.folder_id || undefined,
    materialId: session?.folder_id ? undefined : session?.material_id || undefined,
  }
}

export type GradingMode = 'regrade' | 'self-evaluate'
