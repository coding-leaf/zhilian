import { describe, expect, it } from 'vitest';
import { mount } from '@vue/test-utils';
import DiagnosisSummaryCard from '@/subpackages/report/components/DiagnosisSummaryCard.vue';
import WeakKnowledgeCard from '@/subpackages/report/components/WeakKnowledgeCard.vue';
import type { DiagnosisReport, WeakPoint } from '@/types/report';

describe('Diagnosis Cards Components', () => {
  describe('DiagnosisSummaryCard.vue', () => {
    const baseReport: DiagnosisReport = {
      id: 'rep_123',
      practice_id: 'prac_456',
      overall_score: 88,
      score_rate: 0.88,
      mastery_rate: 88,
      wrong_count: 2,
      total_questions: 10,
      weak_points: [],
      created_at: '2026-09-25T11:00:00Z',
    };

    it('renders basic score, metrics, and duration correctly', () => {
      const wrapper = mount(DiagnosisSummaryCard, {
        props: {
          report: baseReport,
          durationSeconds: 125,
        },
      });

      expect(wrapper.text()).toContain('学情综合诊断');
      expect(wrapper.text()).toContain('88');
      expect(wrapper.text()).toContain('88%');
      expect(wrapper.text()).toContain('02:05'); // 125s -> 02:05
      expect(wrapper.text()).toContain('2'); // wrong count
      expect(wrapper.text()).toContain('精通');
      expect(wrapper.find('.pending-regrade-banner').exists()).toBe(false);
      expect(wrapper.find('.degraded-tag').exists()).toBe(false);
    });

    it('renders pending regrade banner when pending_regrade_count > 0', () => {
      const reportWithPending: DiagnosisReport = {
        ...baseReport,
        pending_regrade_count: 2,
      };

      const wrapper = mount(DiagnosisSummaryCard, {
        props: {
          report: reportWithPending,
          durationSeconds: 60,
        },
      });

      const banner = wrapper.find('.pending-regrade-banner');
      expect(banner.exists()).toBe(true);
      expect(banner.text()).toContain('当前有 2 道主观题待重新判题');
    });

    it('renders degradation tag when is_structure_degraded is true', () => {
      const reportDegraded: DiagnosisReport = {
        ...baseReport,
        is_structure_degraded: true,
      };

      const wrapper = mount(DiagnosisSummaryCard, {
        props: {
          report: reportDegraded,
        },
      });

      const degradedTag = wrapper.find('.degraded-tag');
      expect(degradedTag.exists()).toBe(true);
      expect(degradedTag.text()).toContain('降级模式');
    });
  });

  describe('WeakKnowledgeCard.vue', () => {
    it('renders empty placeholder when weakPoints is empty', () => {
      const wrapper = mount(WeakKnowledgeCard, {
        props: {
          weakPoints: [],
        },
      });

      expect(wrapper.text()).toContain('薄弱知识点诊断');
      expect(wrapper.find('.empty-state').exists()).toBe(true);
      expect(wrapper.text()).toContain('暂无显著薄弱考点');
    });

    it('renders weak points list with regression badges and historical decay indicators', async () => {
      const weakPoints: WeakPoint[] = [
        {
          knowledge_point_id: 'kp_1',
          knowledge_name: '二叉树遍历',
          current_score: 0.35,
          score_delta: -0.15,
          cause_explanation: '递归基定义模糊',
          actionable_advice: '加强递归回溯基础练习',
          associated_mistakes: [], // FR-50: triggers historical decay tag
        },
        {
          knowledge_point_id: 'kp_2',
          knowledge_name: '红黑树染色',
          current_score: 0.55,
          score_delta: 0.05,
          cause_explanation: '旋转变换条件混淆',
          actionable_advice: '对照双红冲突规则推演',
          associated_mistakes: [{ question_id: 'q_123' }],
        },
      ];

      const wrapper = mount(WeakKnowledgeCard, {
        props: {
          weakPoints,
        },
      });

      expect(wrapper.text()).toContain('共 2 个薄弱点');
      expect(wrapper.text()).toContain('二叉树遍历');
      expect(wrapper.text()).toContain('红黑树染色');
      expect(wrapper.text()).toContain('35%');
      expect(wrapper.text()).toContain('55%');

      // Regression badge check: kp_1 regressed (-0.15), kp_2 did not (+0.05)
      const items = wrapper.findAll('.point-item');
      expect(items.length).toBe(2);
      expect(items[0].find('.regression-badge').exists()).toBe(true);
      expect(items[0].text()).toContain('退步');
      expect(items[1].find('.regression-badge').exists()).toBe(false);

      // FR-50 evidence origin check: kp_1 has empty associated_mistakes
      expect(items[0].find('.evidence-origin').exists()).toBe(true);
      expect(items[0].text()).toContain('【证据来源：历史掌握度低/时间衰减】');
      expect(items[1].find('.evidence-origin').exists()).toBe(false);

      // Tap event emit test
      await items[0].trigger('tap');
      expect(wrapper.emitted('click-point')).toBeTruthy();
      expect(wrapper.emitted('click-point')?.[0]).toEqual([weakPoints[0]]);
    });
  });
});
