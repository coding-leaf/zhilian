import type { QuestionItem, QuestionOption, QuestionType } from '@/types'

export type CanonicalTrueFalseValue = '正确' | '错误'

const TRUE_VALUES = new Set(['正确', '对', '是', 'TRUE', 'T', 'YES', 'Y', '1', 'V', '√', 'A'])
const FALSE_VALUES = new Set(['错误', '错', '否', 'FALSE', 'F', 'NO', 'N', '0', 'X', '×', 'B'])

export const TRUE_FALSE_CANONICAL_OPTIONS: QuestionOption[] = [
  { key: '正确', content: '正确' },
  { key: '错误', content: '错误' },
]

/**
 * 将各种历史/异构判断题作答或选项值归一化为后端 grading.py 认可的规范真假值 `'正确'` / `'错误'`。
 * 无法识别时返回空字符串。
 */
export function normalizeTrueFalseValue(raw: unknown): CanonicalTrueFalseValue | '' {
  if (typeof raw === 'boolean') return raw ? '正确' : '错误'
  if (raw === null || raw === undefined) return ''
  const cleaned = String(raw)
    .trim()
    .replace(/^[()[\]{}<>、.:：\s]+|[()[\]{}<>、.:：\s]+$/g, '')
    .toUpperCase()
  if (!cleaned) return ''
  if (TRUE_VALUES.has(cleaned)) return '正确'
  if (FALSE_VALUES.has(cleaned)) return '错误'
  return ''
}

/**
 * 将判断题选项规范化：无论后端下发 `A/B` 还是空数组，统一产出以 `'正确'` / `'错误'` 为提交键的选项。
 */
export function resolveTrueFalseOptions(options?: QuestionOption[]): QuestionOption[] {
  if (!options?.length) return TRUE_FALSE_CANONICAL_OPTIONS
  const normalized = options.map((opt, idx) => {
    const fromContent = normalizeTrueFalseValue(opt.content)
    const fromKey = normalizeTrueFalseValue(opt.key)
    const canonical: CanonicalTrueFalseValue =
      fromContent || fromKey || (idx === 0 ? '正确' : '错误')
    const displayContent = opt.content?.trim() || canonical
    return {
      key: canonical,
      content: displayContent,
    }
  })
  return normalized
}

/** 判断题展示角标：显示简明单字「对 / 错」，不重复渲染「正确. 正确」。 */
export function trueFalseBadgeText(option: QuestionOption, index: number): string {
  const canonical = normalizeTrueFalseValue(option.key) || normalizeTrueFalseValue(option.content)
  if (canonical === '正确') return '对'
  if (canonical === '错误') return '错'
  return index === 0 ? '对' : '错'
}

/** 单选与判断题高亮判定（兼容历史草稿 `'A'`/`'T'` 与 `'B'`/`'F'`）。 */
export function isSingleOrTrueFalseSelected(
  questionType: QuestionType | string,
  savedValue: unknown,
  optionKeyValue: string,
): boolean {
  if (questionType === 'true_false') {
    const normalizedSaved = normalizeTrueFalseValue(savedValue)
    const normalizedOpt = normalizeTrueFalseValue(optionKeyValue)
    return normalizedSaved !== '' && normalizedSaved === normalizedOpt
  }
  return savedValue === optionKeyValue
}

/** 多选题作答值归一化为字符串数组（兼容数组、JSON 数组串与逗号分隔）。 */
export function normalizeMultipleSelection(raw: unknown): string[] {
  if (Array.isArray(raw)) {
    return Array.from(new Set(raw.map((item) => String(item).trim()).filter(Boolean)))
  }
  if (typeof raw === 'string') {
    const trimmed = raw.trim()
    if (!trimmed) return []
    if (trimmed.startsWith('[') && trimmed.endsWith(']')) {
      try {
        const parsed = JSON.parse(trimmed)
        if (Array.isArray(parsed)) {
          return Array.from(new Set(parsed.map((item) => String(item).trim()).filter(Boolean)))
        }
      } catch {
        // fall through to delimiter split
      }
    }
    return Array.from(
      new Set(
        trimmed
          .split(/[,，、\s]+/)
          .map((item) => item.trim())
          .filter(Boolean),
      ),
    )
  }
  return []
}

/** 切换多选题某一项并按字母序稳定排序返回。 */
export function toggleMultipleSelection(raw: unknown, optionKeyValue: string): string[] {
  const current = normalizeMultipleSelection(raw)
  const idx = current.indexOf(optionKeyValue)
  if (idx !== -1) {
    current.splice(idx, 1)
  } else {
    current.push(optionKeyValue)
    current.sort()
  }
  return current
}

const STEM_BLANK_PATTERN = /(?:_{2,}|（\s*）|\(\s*\)|【\s*】)/g
const MAX_MULTI_BLANKS = 10

/** 检测填空题空格数量：优先识别题干占位符，缺失时参考答案分隔符数量兜底。 */
export function resolveFillBlankCount(stem: string, answer?: unknown): number {
  const matches = (stem || '').match(STEM_BLANK_PATTERN) ?? []
  if (matches.length >= 2) {
    return Math.min(matches.length, MAX_MULTI_BLANKS)
  }
  if (typeof answer === 'string' && /[;；\n]|&&/.test(answer)) {
    const parts = answer.split(/\s*(?:[;；\n]|&&)\s*/).filter((part) => part.trim())
    if (parts.length >= 2) {
      return Math.min(parts.length, MAX_MULTI_BLANKS)
    }
  }
  return matches.length === 1 ? 1 : 0
}

/** 把已保存的填空字符串拆分为 N 个独立格输入值，兼容后端 `;` / `；` / `\n` / `&&`。 */
export function splitFillBlankAnswers(raw: unknown, blankCount: number): string[] {
  const count = Math.max(1, blankCount)
  const text = typeof raw === 'string' ? raw : ''
  const parts = text ? text.split(/(?:\s*&&\s*|[;；]\s?|\n)/) : []
  const slots = Array.from({ length: count }, (_, idx) => parts[idx] ?? '')
  if (parts.length > count) {
    slots[count - 1] = parts.slice(count - 1).join('; ')
  }
  return slots
}

/** 把 N 个空格值合并为后端 `grading.py` 识别的 `; ` 分隔串；全空则返回空串。 */
export function joinFillBlankAnswers(parts: string[]): string {
  if (parts.every((part) => !part.trim())) return ''
  return parts.map((part) => part.replace(/[;；\n]+/g, ' ')).join('; ')
}

/** 提取续练中需要升级为规范 `'正确'`/`'错误'` 的历史判断题草稿。 */
export function collectLegacyTrueFalseUpgrades(
  questions: QuestionItem[],
  userAnswers: Record<string, unknown>,
): Array<{ questionId: string; answer: CanonicalTrueFalseValue }> {
  const updates: Array<{ questionId: string; answer: CanonicalTrueFalseValue }> = []
  for (const question of questions) {
    if (question.type !== 'true_false') continue
    const saved = userAnswers[question.id]
    if (saved === undefined || saved === null || saved === '') continue
    const canonical = normalizeTrueFalseValue(saved)
    if (canonical && saved !== canonical) {
      updates.push({ questionId: question.id, answer: canonical })
    }
  }
  return updates
}
