import { describe, expect, it, vi, beforeEach } from 'vitest';
import { mount } from '@vue/test-utils';
import RecentLearningSection from '@/components/home/RecentLearningSection.vue';
import {
  formatRelativeTime,
  extractLatestDraftPractice,
  type ActivePracticeInfo,
} from '@/utils/recentLearning';
import type { MaterialItem } from '@/types/material';
import type { AnswerDraft } from '@/types/practice';

describe('RecentLearningSection.vue & Pure Calculation Kernels', () => {
  const EMOJI_REGEX =
    /[\u{1F300}-\u{1FAFF}\u{1F600}-\u{1F64F}\u{1F680}-\u{1F6FF}\u{2600}-\u{26FF}]/u;

  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('Pure Function: formatRelativeTime', () => {
    const fixedNow = new Date('2026-09-25T12:00:00Z').getTime(); // Reference timestamp

    it('handles null, undefined or invalid timestamp gracefully', () => {
      expect(formatRelativeTime(null, fixedNow)).toBe('最近');
      expect(formatRelativeTime(undefined, fixedNow)).toBe('最近');
      expect(formatRelativeTime(0, fixedNow)).toBe('最近');
      expect(formatRelativeTime('invalid-date', fixedNow)).toBe('最近');
    });

    it('formats less than 1 minute as 刚刚', () => {
      expect(formatRelativeTime(fixedNow - 30_000, fixedNow)).toBe('刚刚');
    });

    it('formats minutes ago accurately', () => {
      expect(formatRelativeTime(fixedNow - 5 * 60_000, fixedNow)).toBe('5分钟前');
    });

    it('formats hours ago accurately', () => {
      expect(formatRelativeTime(fixedNow - 3 * 3600_000, fixedNow)).toBe('3小时前');
    });

    it('formats days ago within a week accurately', () => {
      expect(formatRelativeTime(fixedNow - 2 * 86400_000, fixedNow)).toBe('2天前');
    });

    it('formats older timestamp as MM-DD', () => {
      const older = new Date('2026-09-01T10:00:00Z').getTime();
      const res = formatRelativeTime(older, fixedNow);
      expect(res).toMatch(/^\d{2}-\d{2}$/);
    });
  });

  describe('Pure Function: extractLatestDraftPractice', () => {
    const fixedNow = new Date('2026-09-25T12:00:00Z').getTime();

    it('returns null for empty or invalid drafts object', () => {
      expect(extractLatestDraftPractice(null, null, fixedNow)).toBeNull();
      expect(extractLatestDraftPractice(undefined, null, fixedNow)).toBeNull();
      expect(extractLatestDraftPractice({}, null, fixedNow)).toBeNull();
    });

    it('picks the latest updated draft and accurately counts answered questions', () => {
      const drafts: Record<string, AnswerDraft> = {
        draft_old: {
          practice_id: 'prac_01',
          answers: { q1: 'A' },
          updated_at: fixedNow - 100_000,
        },
        draft_latest: {
          practice_id: 'prac_02',
          answers: { q1: 'A', q2: ['B', 'C'], q3: '', q4: [] },
          updated_at: fixedNow - 10_000,
        },
      };

      const result = extractLatestDraftPractice(drafts, null, fixedNow);
      expect(result).not.toBeNull();
      expect(result?.practiceId).toBe('prac_02');
      expect(result?.answeredCount).toBe(2);
      expect(result?.totalCount).toBe(10);
      expect(result?.updatedAtText).toBe('刚刚');
    });

    it('associates with material title when material_id is present', () => {
      const materials: MaterialItem[] = [
        {
          id: 'mat_101',
          title: '离散数学',
          file_format: 'pdf',
          file_size: 1024,
          source_type: 'local',
          status: 'ready',
          created_at: '2026-09-25T00:00:00Z',
        },
      ];

      const drafts: Record<string, AnswerDraft> = {
        draft_01: {
          practice_id: 'prac_101',
          answers: { q1: 'A' },
          updated_at: fixedNow - 10_000,
          ...({ material_id: 'mat_101' } as unknown as object),
        },
      };

      const result = extractLatestDraftPractice(drafts, materials, fixedNow);
      expect(result?.title).toBe('离散数学 专项练习');
    });

    it('consumes the real total_count and title persisted in the draft (BUG-DIAG-017)', () => {
      const drafts: Record<string, AnswerDraft> = {
        draft_meta: {
          practice_id: 'prac_meta',
          answers: { q1: 'A' },
          updated_at: fixedNow - 1_000,
          total_count: 25,
          title: '操作系统精练',
          material_id: 'mat_meta',
        },
      };

      const result = extractLatestDraftPractice(drafts, [], fixedNow);
      expect(result?.practiceId).toBe('prac_meta');
      expect(result?.totalCount).toBe(25);
      expect(result?.title).toBe('操作系统精练');
    });
  });

  describe('Component Mounting & Interactions', () => {
    const mockActivePractice: ActivePracticeInfo = {
      practiceId: 'prac_live_01',
      title: '高数上册核心考点练习',
      answeredCount: 3,
      totalCount: 10,
      updatedAtText: '10分钟前',
    };

    const mockMaterials: MaterialItem[] = [
      {
        id: 'mat_01',
        title: '微积分导论讲义',
        file_format: 'pdf',
        file_size: 1048576,
        source_type: 'wechat',
        status: 'ready',
        created_at: '2026-09-25T08:00:00Z',
        ...({ key_points_count: 14 } as unknown as object),
      },
      {
        id: 'mat_02',
        title: '线性代数重点公式集',
        file_format: 'docx',
        file_size: 512000,
        source_type: 'local',
        status: 'parsing',
        created_at: '2026-09-25T09:00:00Z',
        ...({ pages_count: 8 } as unknown as object),
      },
      {
        id: 'mat_03',
        title: '第三份资料（应被截断）',
        file_format: 'txt',
        file_size: 10240,
        source_type: 'local',
        status: 'ready',
        created_at: '2026-09-25T09:30:00Z',
      },
    ];

    it('renders Rail 1 (Active Practice) with progress and text when activePractice is provided', () => {
      const wrapper = mount(RecentLearningSection, {
        props: {
          activePractice: mockActivePractice,
          recentMaterials: mockMaterials,
        },
      });

      expect(wrapper.text()).toContain('进行中');
      expect(wrapper.text()).toContain('高数上册核心考点练习');
      expect(wrapper.text()).toContain('已答 3/10 题');
      expect(wrapper.text()).toContain('30%');
      expect(wrapper.text()).toContain('10分钟前');
      expect(wrapper.text()).toContain('继续练习');
    });

    it('does not render Rail 1 when activePractice is null', () => {
      const wrapper = mount(RecentLearningSection, {
        props: {
          activePractice: null,
          recentMaterials: mockMaterials,
        },
      });

      expect(wrapper.find('.active-practice-card').exists()).toBe(false);
      expect(wrapper.text()).not.toContain('已答');
    });

    it('renders at most 2 materials in Rail 2 and formats meta tags', () => {
      const wrapper = mount(RecentLearningSection, {
        props: {
          activePractice: null,
          recentMaterials: mockMaterials,
        },
      });

      const cards = wrapper.findAll('.material-item-card');
      expect(cards.length).toBe(2);
      expect(wrapper.text()).toContain('微积分导论讲义');
      expect(wrapper.text()).toContain('线性代数重点公式集');
      expect(wrapper.text()).not.toContain('第三份资料（应被截断）');

      expect(wrapper.text()).toContain('14 个考点');
      expect(wrapper.text()).toContain('8 页');
      expect(wrapper.text()).toContain('已完成');
      expect(wrapper.text()).toContain('解析中');
    });

    it('emits continue-practice on continue practice tap without navigation', async () => {
      const navSpy = vi.spyOn(uni, 'navigateTo');
      const wrapper = mount(RecentLearningSection, {
        props: {
          activePractice: mockActivePractice,
        },
      });

      const btn = wrapper.find('.btn-continue');
      await btn.trigger('tap');

      expect(wrapper.emitted('continue-practice')?.[0]).toEqual(['prac_live_01']);
      expect(navSpy).not.toHaveBeenCalled();
    });

    it('emits quick-quiz and generate-questions on quick quiz tap without navigation', async () => {
      const navSpy = vi.spyOn(uni, 'navigateTo');
      const wrapper = mount(RecentLearningSection, {
        props: {
          recentMaterials: mockMaterials,
        },
      });

      const quickQuizBtn = wrapper.find('.btn-quick-quiz');
      await quickQuizBtn.trigger('tap');

      expect(wrapper.emitted('quick-quiz')?.[0]).toEqual([mockMaterials[0]]);
      expect(wrapper.emitted('generate-questions')?.[0]).toEqual([mockMaterials[0].id]);
      expect(navSpy).not.toHaveBeenCalled();
    });

    it('emits view-material on material card tap without navigation', async () => {
      const navSpy = vi.spyOn(uni, 'navigateTo');
      const wrapper = mount(RecentLearningSection, {
        props: {
          recentMaterials: mockMaterials,
        },
      });

      const materialCard = wrapper.find('.material-item-card');
      await materialCard.trigger('tap');

      expect(wrapper.emitted('view-material')?.[0]).toEqual([mockMaterials[0].id]);
      expect(navSpy).not.toHaveBeenCalled();
    });

    it('emits view-all-materials and view-all on view-all-materials tap without navigation', async () => {
      const navSpy = vi.spyOn(uni, 'navigateTo');
      const wrapper = mount(RecentLearningSection, {
        props: {
          recentMaterials: mockMaterials,
        },
      });

      const footer = wrapper.find('.section-footer');
      await footer.trigger('tap');

      expect(wrapper.emitted('view-all-materials')).toBeTruthy();
      expect(wrapper.emitted('view-all')).toBeTruthy();
      expect(navSpy).not.toHaveBeenCalled();
    });

    it('renders empty placeholder when no active practice and no materials', () => {
      const wrapper = mount(RecentLearningSection, {
        props: {
          activePractice: null,
          recentMaterials: [],
        },
      });

      expect(wrapper.text()).toContain('暂无最近学习记录');
    });

    it('strictly satisfies zero-emoji policy', () => {
      const wrapper = mount(RecentLearningSection, {
        props: {
          activePractice: mockActivePractice,
          recentMaterials: mockMaterials,
        },
      });

      expect(EMOJI_REGEX.test(wrapper.text())).toBe(false);
    });
  });
});
