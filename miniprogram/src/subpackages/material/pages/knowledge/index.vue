<template>
  <view class="knowledge-page">
    <view class="paper-card kp-header">
      <view class="kp-header-top">
        <text v-if="chapterLabel" class="kp-chapter">{{ chapterLabel }}</text>
        <text :class="['mastery-pill', `mastery-${masteryBadge.tone}`]">{{ masteryBadge.text }}</text>
      </view>
      <view class="kp-title-row">
        <text class="kp-title">{{ pointTitle }}</text>
        <button
          :class="['regen-btn', { 'is-disabled': isGeneratingGuide }]"
          :loading="isGeneratingGuide"
          :disabled="isGeneratingGuide"
          @tap="handleGenerate(true)"
        >
          {{ isGeneratingGuide ? '精讲中' : '重新生成' }}
        </button>
      </view>
    </view>

    <view class="tab-bar">
      <view
        v-for="tab in TABS"
        :key="tab.key"
        :class="['tab-item', { active: activeTab === tab.key }]"
        @tap="activeTab = tab.key"
      >
        <text class="tab-text">{{ tab.label }}</text>
      </view>
    </view>

    <view v-if="activeTab === 'evidence'" class="tab-body">
      <KnowledgeEvidenceList
        :snippets="snippets"
        :loading="loadingSnippets"
        :load-failed="snippetLoadFailed"
        :reset-key="kpId"
      />
    </view>

    <view v-else class="tab-body">
      <template v-if="guideStatus === 'ready' && studyGuide">
        <StudyGuideNoteView v-if="activeTab === 'note'" :guide="studyGuide" />
        <StudyGuideExamplesView v-else-if="activeTab === 'examples'" :examples="studyGuide.worked_examples" />
        <StudyGuideCompareView v-else :comparisons="studyGuide.comparisons" :pitfalls="studyGuide.pitfalls" />
      </template>

      <template v-else>
        <view class="paper-card status-banner">
          <view class="status-banner-head">
            <view v-if="isGeneratingGuide || guideStatus === 'loading'" class="status-dot-pulse" />
            <text class="status-banner-title">{{ statusMeta.title }}</text>
          </view>
          <text class="status-banner-desc">{{ statusMeta.desc }}</text>
          <button
            v-if="guideStatus === 'empty' || guideStatus === 'error'"
            class="paper-btn-primary generate-now-btn"
            :loading="isGeneratingGuide"
            :disabled="isGeneratingGuide"
            @tap="handleGenerate(guideStatus === 'error')"
          >
            {{ guideStatus === 'error' ? '重新生成考前精讲' : '点击生成考前精讲' }}
          </button>
        </view>

        <view class="paper-card preview-card">
          <text class="preview-label">核心定义速览（Stage 1）</text>
          <RichContent :content="stage1Summary" />
          <view v-if="stage1Formulas.length" class="preview-formulas">
            <view v-for="(formula, idx) in stage1Formulas" :key="idx" class="preview-formula-item">
              <RichContent :content="formula" compact />
            </view>
          </view>
        </view>
      </template>
    </view>

    <view class="bottom-fixed-bar kp-bottom-bar">
      <button class="practice-btn" @tap="goToPractice">针对此考点出题</button>
      <button class="paper-btn-primary coach-btn" @tap="showCoach = true">向 AI 助教追问</button>
    </view>

    <AiCoachDrawer
      v-model:visible="showCoach"
      :title="`考点答疑: ${pointTitle}`"
      :context-text="`当前考点：${pointTitle}。核心定义：${studyGuide?.core_definition || stage1Summary}`"
      :knowledge-point-id="kpId"
    />
  </view>
</template>

<script setup lang="ts">
import { computed, onUnmounted, ref } from 'vue'
import { onLoad } from '@dcloudio/uni-app'
import {
  apiGenerateKnowledgeStudyGuide, apiGetKnowledgePointDetail,
  apiGetKnowledgePointSnippets, apiGetKnowledgeStudyGuide, apiGetMasteryOverview,
} from '@/api'
import AiCoachDrawer from '@/components/AiCoachDrawer.vue'
import RichContent from '@/components/RichContent.vue'
import type { KnowledgePointDetail, KnowledgeSnippet, StudyGuideContent } from '@/types'
import { extractUserErrorMessage } from '@/utils/loadingGuard'
import { safeNavigateTo } from '@/utils/navigation'
import KnowledgeEvidenceList from '../../components/KnowledgeEvidenceList.vue'
import StudyGuideCompareView from '../../components/StudyGuideCompareView.vue'
import StudyGuideExamplesView from '../../components/StudyGuideExamplesView.vue'
import StudyGuideNoteView from '../../components/StudyGuideNoteView.vue'
import { buildMasteryMap, resolveMasteryBadge, type MasteryEntry } from '../../utils/courseStudy'

type TabKey = 'note' | 'examples' | 'compare' | 'evidence'
const TABS: Array<{ key: TabKey; label: string }> = [
  { key: 'note', label: '精讲笔记' }, { key: 'examples', label: '典型例题' },
  { key: 'compare', label: '对比与避坑' }, { key: 'evidence', label: '教材原文' },
]
const kpId = ref('')
const materialId = ref('')
const chapterLabel = ref('')
const activeTab = ref<TabKey>('note')
const pointDetail = ref<KnowledgePointDetail | null>(null)
const snippets = ref<KnowledgeSnippet[]>([])
const loadingSnippets = ref(false)
const snippetLoadFailed = ref(false)
const masteryEntry = ref<MasteryEntry | null>(null)
const guideStatus = ref<'loading' | 'empty' | 'generating' | 'ready' | 'error'>('loading')
const studyGuide = ref<StudyGuideContent | null>(null)
const errorText = ref('')
const elapsedSec = ref(0)
const showCoach = ref(false)
let pollTimer: ReturnType<typeof setTimeout> | null = null
let elapsedTimer: ReturnType<typeof setInterval> | null = null
let pollAttempts = 0
let disposed = false

const clearPollTimer = () => { if (pollTimer !== null) { clearTimeout(pollTimer); pollTimer = null } }
const clearElapsedTimer = () => { if (elapsedTimer !== null) { clearInterval(elapsedTimer); elapsedTimer = null } }
const stopGeneratingTimers = () => { clearPollTimer(); clearElapsedTimer() }
const startElapsedTimer = () => {
  clearElapsedTimer()
  elapsedSec.value = 0
  elapsedTimer = setInterval(() => { if (!disposed && guideStatus.value === 'generating') elapsedSec.value += 1 }, 1000)
}
const isGeneratingGuide = computed(() => guideStatus.value === 'generating')
const pointTitle = computed(() => pointDetail.value?.name || '考点精讲')
const masteryBadge = computed(() => resolveMasteryBadge(masteryEntry.value))
const resolvedMaterialId = computed(() => materialId.value || pointDetail.value?.material_id || '')
const stage1Summary = computed(() =>
  pointDetail.value?.structured_content?.core_summary?.trim()
  || pointDetail.value?.description?.trim()
  || '正在加载本考点的核心定义预览，你也可以先切到「教材原文」查看溯源。',
)
const stage1Formulas = computed(() => pointDetail.value?.structured_content?.key_formulas ?? [])
const GENERATING_TAB_LABELS: Record<'note' | 'examples' | 'compare', string> = {
  note: '精讲笔记（考法定位、核心定义与推导链）',
  examples: '典型例题与分步标准解答',
  compare: '易混概念对比与常见避坑',
}
const statusMeta = computed(() => {
  const defaultDesc = '正在为你深度拆解推导链、典型例题与易错对比，首次生成约 15~25 秒，生成后永久秒开；可先切「教材原文」或离开页面，后台生成不会中断。'
  if (guideStatus.value === 'loading') return { title: '正在检查考前精讲缓存...', desc: defaultDesc }
  if (guideStatus.value === 'generating') {
    const tabLabel = GENERATING_TAB_LABELS[activeTab.value === 'evidence' ? 'note' : activeTab.value]
    return {
      title: `正在深度精讲生成中（已耗时 ${elapsedSec.value}s）`,
      desc: `正在后台生成${tabLabel}，通常约 15~25 秒。可随时切换「教材原文」或离开页面，后台生成不会取消。`,
    }
  }
  if (guideStatus.value === 'error') {
    return { title: '精讲生成未能完成', desc: errorText.value || '请检查网络后点击下方按钮重新生成，先切「教材原文」亦可阅读。' }
  }
  return { title: '尚未生成考前精讲', desc: defaultDesc }
})

const scheduleNextPoll = () => {
  clearPollTimer()
  if (disposed || !kpId.value || pollAttempts >= 45) {
    if (pollAttempts >= 45 && guideStatus.value === 'generating') {
      clearElapsedTimer()
      guideStatus.value = 'error'
      errorText.value = '后台精讲生成耗时较长，请点击下方按钮重试。'
    }
    return
  }
  pollTimer = setTimeout(async () => {
    pollTimer = null
    if (disposed) return
    pollAttempts += 1
    try {
      const res = await apiGetKnowledgeStudyGuide(kpId.value, { silentToast: true })
      if (disposed) return
      if (res.status === 'ready' && res.study_guide) { stopGeneratingTimers(); studyGuide.value = res.study_guide; guideStatus.value = 'ready'; return }
      if (res.status === 'failed') { stopGeneratingTimers(); guideStatus.value = 'error'; errorText.value = res.error_message || '后台精讲生成失败，请点击下方按钮重试。'; return }
      if (res.status === 'empty') { stopGeneratingTimers(); guideStatus.value = 'empty'; return }
      scheduleNextPoll()
    } catch { if (!disposed) scheduleNextPoll() }
  }, 2000)
}

const handleGenerate = async (force: boolean) => {
  if (!kpId.value || isGeneratingGuide.value) return
  stopGeneratingTimers(); pollAttempts = 0; errorText.value = ''; guideStatus.value = 'generating'; startElapsedTimer()
  try {
    const res = await apiGenerateKnowledgeStudyGuide(kpId.value, force)
    if (disposed) return
    if (res.status === 'ready' && res.study_guide) { stopGeneratingTimers(); studyGuide.value = res.study_guide; guideStatus.value = 'ready'; return }
    if (res.status === 'generating') { scheduleNextPoll(); return }
    if (res.status === 'failed') { stopGeneratingTimers(); guideStatus.value = 'error'; errorText.value = res.error_message || '考前精讲生成失败，请重试'; return }
    stopGeneratingTimers(); guideStatus.value = 'empty'
  } catch (err) {
    if (disposed) return
    stopGeneratingTimers()
    guideStatus.value = 'error'
    errorText.value = extractUserErrorMessage(err, '考前精讲生成失败，请重试')
  }
}

onLoad(async (options) => {
  kpId.value = options?.kp_id ? decodeURIComponent(options.kp_id) : ''
  materialId.value = options?.material_id ? decodeURIComponent(options.material_id) : ''
  chapterLabel.value = options?.chapter ? decodeURIComponent(options.chapter) : ''
  if (!kpId.value) return
  loadingSnippets.value = true
  const [detailRes, snippetRes, guideRes, masteryRes] = await Promise.allSettled([
    apiGetKnowledgePointDetail(kpId.value), apiGetKnowledgePointSnippets(kpId.value),
    apiGetKnowledgeStudyGuide(kpId.value, { silentToast: true }), apiGetMasteryOverview().catch(() => null),
  ])
  if (disposed) return
  if (detailRes.status === 'fulfilled') {
    pointDetail.value = detailRes.value
    if (!materialId.value) materialId.value = detailRes.value.material_id
  }
  if (snippetRes.status === 'fulfilled') snippets.value = snippetRes.value.snippets
  else snippetLoadFailed.value = true
  loadingSnippets.value = false
  if (masteryRes.status === 'fulfilled' && masteryRes.value) masteryEntry.value = buildMasteryMap(masteryRes.value)[kpId.value] ?? null
  if (guideRes.status === 'fulfilled' && guideRes.value.status === 'ready' && guideRes.value.study_guide) {
    studyGuide.value = guideRes.value.study_guide; guideStatus.value = 'ready'
  } else if (guideRes.status === 'fulfilled' && guideRes.value.status === 'generating') {
    guideStatus.value = 'generating'; startElapsedTimer(); scheduleNextPoll()
  } else if (guideRes.status === 'fulfilled' && guideRes.value.status === 'failed') {
    guideStatus.value = 'error'; errorText.value = guideRes.value.error_message || '后台精讲生成失败，请点击下方按钮重试。'
  } else await handleGenerate(false)
})

onUnmounted(() => { disposed = true; stopGeneratingTimers() })

const goToPractice = () => {
  if (!resolvedMaterialId.value || !kpId.value) return
  safeNavigateTo(
    `/subpackages/material/pages/questions/index?material_id=${encodeURIComponent(resolvedMaterialId.value)}&kp_id=${encodeURIComponent(kpId.value)}`,
    { failMessage: '打开出题页失败，请重试' },
  )
}
</script>

<style lang="scss" scoped>
@import '../../../../styles/common.scss';
@import '../../../../styles/tokens.scss';
@import '../../course.scss';

.knowledge-page { padding: 24rpx 28rpx calc(170rpx + env(safe-area-inset-bottom)); min-height: 100vh; }
.kp-header { padding: 24rpx 26rpx; margin-bottom: 18rpx; }
.kp-header-top { display: flex; align-items: center; justify-content: space-between; gap: 12rpx; margin-bottom: 10rpx; }
.kp-chapter { font-size: 22rpx; color: $color-ink-subtle; flex: 1; min-width: 0; }
.kp-title-row { display: flex; align-items: flex-start; justify-content: space-between; gap: 16rpx; }
.kp-title { flex: 1; min-width: 0; font-size: 34rpx; font-weight: 700; color: $color-ink-primary; line-height: 1.35; }
.regen-btn { flex-shrink: 0; height: 56rpx; padding: 0 20rpx; margin: 0; line-height: 1.4; font-size: 22rpx; font-weight: 600; color: $color-academic-blue; background: $color-blue-bg; border: 1px solid $color-blue-border; border-radius: 999rpx; display: flex; align-items: center; &::after { border: none; } }
.regen-btn.is-disabled { opacity: 0.55; }
.tab-bar { display: flex; background: $color-bg-card; border: 1px solid $color-paper-border; border-radius: 14rpx; padding: 6rpx; gap: 6rpx; margin-bottom: 20rpx; }
.tab-item { flex: 1; text-align: center; padding: 14rpx 6rpx; border-radius: 10rpx; }
.tab-item.active { background: $color-academic-blue; }
.tab-text { font-size: 24rpx; font-weight: 600; color: $color-ink-secondary; }
.tab-item.active .tab-text { color: $color-ink-on-primary; }
.tab-body { display: flex; flex-direction: column; gap: 18rpx; }
.status-banner { padding: 24rpx; background: $color-blue-bg; border-color: $color-blue-border; }
.status-banner-head { display: flex; align-items: center; gap: 12rpx; margin-bottom: 8rpx; }
.status-dot-pulse { width: 14rpx; height: 14rpx; border-radius: 999rpx; background: $color-academic-blue; }
.status-banner-title { font-size: 28rpx; font-weight: 700; color: $color-academic-blue; }
.status-banner-desc { display: block; font-size: 24rpx; color: $color-ink-secondary; line-height: 1.55; }
.generate-now-btn { margin-top: 18rpx; height: 76rpx; font-size: 26rpx; }
.preview-card { padding: 24rpx; }
.preview-label { display: block; font-size: 24rpx; font-weight: 700; color: $color-ink-subtle; margin-bottom: 12rpx; }
.preview-formulas { margin-top: 14rpx; display: flex; flex-direction: column; gap: 10rpx; }
.preview-formula-item { background: $color-surface-subtle; border-radius: 8rpx; padding: 12rpx 16rpx; }
.practice-btn { flex: 1; height: 84rpx; margin: 0; line-height: 1.4; font-size: 27rpx; font-weight: 600; background: $color-blue-bg; color: $color-academic-blue; border: 1px solid $color-blue-border; border-radius: 12rpx; display: flex; align-items: center; justify-content: center; &::after { border: none; } }
.coach-btn { flex: 1; height: 84rpx; font-size: 27rpx; }
</style>
