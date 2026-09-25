import { describe, expect, it, vi, beforeEach } from 'vitest';
import { mount } from '@vue/test-utils';
import MasteryDashboardBar, {
  calculateTierPercentages,
  resolveOverallTier,
} from '@/components/home/MasteryDashboardBar.vue';
import type { UserMasteryOverview } from '@/types/report';

describe('MasteryDashboardBar.vue & Pure Calculation Kernels', () => {
  const EMOJI_REGEX =
    /[\u{1F300}-\u{1FAFF}\u{1F600}-\u{1F64F}\u{1F680}-\u{1F6FF}\u{2600}-\u{26FF}]/u;

  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('Pure Function: calculateTierPercentages', () => {
    it('returns 100% unlearned when input is null, undefined, or empty', () => {
      expect(calculateTierPercentages(null)).toEqual({
        masteredPct: 0,
        proficientPct: 0,
        weakPct: 0,
        unlearnedPct: 100,
      });

      expect(calculateTierPercentages(undefined)).toEqual({
        masteredPct: 0,
        proficientPct: 0,
        weakPct: 0,
        unlearnedPct: 100,
      });

      expect(
        calculateTierPercentages({
          mastered_count: 0,
          proficient_count: 0,
          weak_count: 0,
          unlearned_count: 0,
        }),
      ).toEqual({
        masteredPct: 0,
        proficientPct: 0,
        weakPct: 0,
        unlearnedPct: 100,
      });
    });

    it('distributes 25% to each tier for equal counts and sums to strictly 100%', () => {
      const res = calculateTierPercentages({
        mastered_count: 5,
        proficient_count: 5,
        weak_count: 5,
        unlearned_count: 5,
      });
      expect(res).toEqual({
        masteredPct: 25,
        proficientPct: 25,
        weakPct: 25,
        unlearnedPct: 25,
      });
      expect(res.masteredPct + res.proficientPct + res.weakPct + res.unlearnedPct).toBe(100);
    });

    it('normalizes rounding remainders so total is strictly 100%', () => {
      const res = calculateTierPercentages({
        mastered_count: 1,
        proficient_count: 1,
        weak_count: 1,
        unlearned_count: 0,
      });
      expect(res.masteredPct + res.proficientPct + res.weakPct + res.unlearnedPct).toBe(100);
    });

    it('handles 100% mastered boundary correctly', () => {
      const res = calculateTierPercentages({
        mastered_count: 20,
        proficient_count: 0,
        weak_count: 0,
        unlearned_count: 0,
      });
      expect(res).toEqual({
        masteredPct: 100,
        proficientPct: 0,
        weakPct: 0,
        unlearnedPct: 0,
      });
    });
  });

  describe('Pure Function: resolveOverallTier', () => {
    it('maps undefined, null, or zero to unlearned tier with DESIGN.md color tokens', () => {
      const emptyRes = resolveOverallTier(undefined);
      expect(emptyRes).toEqual({
        tier: 'unlearned',
        label: '未学',
        color: '#64748B',
        bgColor: '#F1F5F9',
        fillColor: '#94A3B8',
      });

      const zeroRes = resolveOverallTier(0);
      expect(zeroRes.tier).toBe('unlearned');
      expect(zeroRes.label).toBe('未学');
    });

    it('maps weak tier (0 < score < 0.40 or 0 < score < 40)', () => {
      const resDec = resolveOverallTier(0.35);
      expect(resDec).toEqual({
        tier: 'weak',
        label: '需巩固',
        color: '#B45309',
        bgColor: '#FFFBEB',
        fillColor: '#F59E0B',
      });

      const resHundred = resolveOverallTier(20);
      expect(resHundred.tier).toBe('weak');
      expect(resHundred.label).toBe('需巩固');
    });

    it('maps proficient tier (0.40 <= score < 0.70 or 40 <= score < 70)', () => {
      const resBoundary = resolveOverallTier(0.4);
      expect(resBoundary).toEqual({
        tier: 'proficient',
        label: '良好',
        color: '#059669',
        bgColor: '#ECFDF5',
        fillColor: '#10B981',
      });

      const resMid = resolveOverallTier(65);
      expect(resMid.tier).toBe('proficient');
      expect(resMid.label).toBe('良好');
    });

    it('maps mastered tier (score >= 0.70 or score >= 70)', () => {
      const resBoundary = resolveOverallTier(0.7);
      expect(resBoundary).toEqual({
        tier: 'mastered',
        label: '精通',
        color: '#7C3AED',
        bgColor: '#F5F3FF',
        fillColor: '#8B5CF6',
      });

      const resFull = resolveOverallTier(98);
      expect(resFull.tier).toBe('mastered');
      expect(resFull.label).toBe('精通');
    });
  });

  describe('Component Mounting & Interactions', () => {
    const mockOverview: UserMasteryOverview = {
      mastered_count: 12,
      proficient_count: 8,
      weak_count: 3,
      unlearned_count: 15,
      overall_score: 78,
    };

    it('renders overall score, badge and point counts accurately', () => {
      const wrapper = mount(MasteryDashboardBar, {
        props: {
          overview: mockOverview,
        },
      });

      expect(wrapper.text()).toContain('78分');
      expect(wrapper.text()).toContain('精通');
      expect(wrapper.text()).toContain('共 38 个');
      expect(wrapper.text()).toContain('精通 12');
      expect(wrapper.text()).toContain('良好 8');
      expect(wrapper.text()).toContain('需巩固 3');
      expect(wrapper.text()).toContain('未学 15');
    });

    it('renders placeholder score and unlearned badge when overview is null', () => {
      const wrapper = mount(MasteryDashboardBar, {
        props: {
          overview: null,
        },
      });

      expect(wrapper.text()).toContain('--');
      expect(wrapper.text()).toContain('未学');
      expect(wrapper.text()).toContain('共 0 个');
    });

    it('supports 0.0~1.0 normalized score display', () => {
      const wrapper = mount(MasteryDashboardBar, {
        props: {
          overview: {
            ...mockOverview,
            overall_score: 0.85,
          },
        },
      });

      expect(wrapper.text()).toContain('85分');
      expect(wrapper.text()).toContain('精通');
    });

    it('emits tap-detail and click on tap without redundant navigateTo', async () => {
      const navSpy = vi.spyOn(uni, 'navigateTo');
      const wrapper = mount(MasteryDashboardBar, {
        props: {
          overview: mockOverview,
        },
      });

      await wrapper.trigger('tap');

      expect(wrapper.emitted('tap-detail')).toBeTruthy();
      expect(wrapper.emitted('click')).toBeTruthy();
      expect(navSpy).not.toHaveBeenCalled();
    });

    it('strictly satisfies zero-emoji policy', () => {
      const wrapper = mount(MasteryDashboardBar, {
        props: {
          overview: mockOverview,
        },
      });

      expect(EMOJI_REGEX.test(wrapper.text())).toBe(false);
    });

    it('applies is-loading class when loading prop is true', () => {
      const wrapper = mount(MasteryDashboardBar, {
        props: {
          overview: mockOverview,
          loading: true,
        },
      });

      expect(wrapper.classes()).toContain('is-loading');
    });
  });
});
