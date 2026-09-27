import { describe, expect, it, vi, beforeEach } from 'vitest';
import { mount } from '@vue/test-utils';
import SelfGradeModal from '@/subpackages/report/components/SelfGradeModal.vue';
import RegradeModal from '@/subpackages/report/components/RegradeModal.vue';
import * as diagnosisApi from '@/api/diagnosis';

describe('Grading Modals (SelfGradeModal & RegradeModal)', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  describe('SelfGradeModal.vue', () => {
    it('does not render when visible is false', () => {
      const wrapper = mount(SelfGradeModal, {
        props: {
          visible: false,
          attemptItemId: 'att_001',
        },
      });
      expect(wrapper.find('.modal-card').exists()).toBe(false);
    });

    it('renders questions, answers, rubric and score information when visible', () => {
      const wrapper = mount(SelfGradeModal, {
        props: {
          visible: true,
          attemptItemId: 'att_001',
          stem: '请阐述虚拟内存的页面置换算法。',
          userAnswer: '使用了LRU算法与FIFO算法',
          standardAnswer: '核心置换算法包括OPT、FIFO、LRU和Clock算法。',
          maxScore: 10.0,
          currentScore: 4.0,
          rubric: {
            要点1: '列举3种以上置换算法（3分）',
            要点2: '阐述淘汰策略与缺页中断关联（7分）',
          },
        },
      });

      expect(wrapper.find('.modal-card').exists()).toBe(true);
      expect(wrapper.text()).toContain('主观题自主评分');
      expect(wrapper.text()).toContain('请阐述虚拟内存的页面置换算法。');
      expect(wrapper.text()).toContain('使用了LRU算法与FIFO算法');
      expect(wrapper.text()).toContain('核心置换算法包括OPT、FIFO、LRU和Clock算法。');
      expect(wrapper.text()).toContain('列举3种以上置换算法（3分）');
      expect(wrapper.text()).toContain('4.0');
      expect(wrapper.text()).toContain('/ 10.0 分');
    });

    it('adjusts score via quick adjust pills and slider events', async () => {
      const wrapper = mount(SelfGradeModal, {
        props: {
          visible: true,
          attemptItemId: 'att_001',
          maxScore: 10.0,
          currentScore: 5.0,
        },
      });

      // Find quick adjust pills: -0.5, 0, 半分, 满分, +0.5
      const pills = wrapper.findAll('.adjust-pill');
      expect(pills.length).toBe(5);

      // Tap +0.5
      await pills[4].trigger('tap');
      expect(wrapper.find('.current-score-text').text()).toBe('5.5');

      // Tap -0.5
      await pills[0].trigger('tap');
      expect(wrapper.find('.current-score-text').text()).toBe('5.0');

      // Tap 满分
      await pills[3].trigger('tap');
      expect(wrapper.find('.current-score-text').text()).toBe('10.0');

      // Tap 0 分
      await pills[1].trigger('tap');
      expect(wrapper.find('.current-score-text').text()).toBe('0.0');

      // Tap 半分 (10 / 2 = 5)
      await pills[2].trigger('tap');
      expect(wrapper.find('.current-score-text').text()).toBe('5.0');

      // Slider change event
      const slider = wrapper.findComponent({ name: 'slider' });
      if (slider.exists()) {
        await slider.vm.$emit('change', { detail: { value: 7.5 } });
        expect(wrapper.find('.current-score-text').text()).toBe('7.5');
      }
    });

    it('submits self grade successfully and emits submit & success events', async () => {
      const selfGradeSpy = vi.spyOn(diagnosisApi, 'selfGradeQuestion').mockResolvedValue({
        code: 0,
        message: 'success',
        data: { grading_record_id: 'rec_999', score: 8.0 },
      });

      const wrapper = mount(SelfGradeModal, {
        props: {
          visible: true,
          attemptItemId: 'att_001',
          maxScore: 10.0,
          currentScore: 8.0,
        },
      });

      // Type feedback
      const textarea = wrapper.find('.feedback-textarea');
      await textarea.setValue('已按评分细则核对核心关键词');

      // Click submit
      const submitBtn = wrapper.find('.btn-primary');
      await submitBtn.trigger('tap');

      expect(selfGradeSpy).toHaveBeenCalledTimes(1);
      expect(selfGradeSpy).toHaveBeenCalledWith({
        attempt_item_id: 'att_001',
        score: 8.0,
        feedback: '已按评分细则核对核心关键词',
      });

      expect(wrapper.emitted('submit')?.[0]).toEqual([
        {
          attempt_item_id: 'att_001',
          score: 8.0,
          feedback: '已按评分细则核对核心关键词',
        },
      ]);
      expect(wrapper.emitted('success')?.[0]).toEqual([
        {
          attempt_item_id: 'att_001',
          score: 8.0,
          feedback: '已按评分细则核对核心关键词',
        },
      ]);
      expect(wrapper.emitted('update:visible')?.[0]).toEqual([false]);
    });

    it('handles self grade API failure gracefully', async () => {
      vi.spyOn(diagnosisApi, 'selfGradeQuestion').mockResolvedValue({
        code: 40001,
        message: '判分数值超出上限',
        data: null as unknown as { grading_record_id: string; score: number },
      });

      const wrapper = mount(SelfGradeModal, {
        props: {
          visible: true,
          attemptItemId: 'att_001',
          maxScore: 5.0,
        },
      });

      const submitBtn = wrapper.find('.btn-primary');
      await submitBtn.trigger('tap');

      expect(wrapper.emitted('submit')).toBeTruthy();
      expect(wrapper.emitted('success')).toBeFalsy();
    });

    it('emits update:visible(false) when close or cancel button is tapped', async () => {
      const wrapper = mount(SelfGradeModal, {
        props: {
          visible: true,
          attemptItemId: 'att_001',
        },
      });

      const closeBtn = wrapper.find('.close-btn');
      await closeBtn.trigger('tap');
      expect(wrapper.emitted('update:visible')?.[0]).toEqual([false]);

      const cancelBtn = wrapper.find('.btn-secondary');
      await cancelBtn.trigger('tap');
      expect(wrapper.emitted('update:visible')?.[1]).toEqual([false]);
    });
  });

  describe('RegradeModal.vue', () => {
    it('does not render when visible is false', () => {
      const wrapper = mount(RegradeModal, {
        props: {
          visible: false,
          attemptItemId: 'att_002',
        },
      });
      expect(wrapper.find('.modal-card').exists()).toBe(false);
    });

    it('renders instruction, stem, and validates reason length', async () => {
      const wrapper = mount(RegradeModal, {
        props: {
          visible: true,
          attemptItemId: 'att_002',
          stem: '简述死锁的四个必要条件。',
        },
      });

      expect(wrapper.find('.modal-card').exists()).toBe(true);
      expect(wrapper.text()).toContain('申请重新判题');
      expect(wrapper.text()).toContain('简述死锁的四个必要条件。');
      expect(wrapper.text()).toContain('至少 2 个字符');

      // Submit button should be disabled initially
      const submitBtn = wrapper.find('.btn-primary');
      expect(submitBtn.classes()).toContain('disabled');

      // Enter 1 character -> still disabled
      const textarea = wrapper.find('.reason-textarea');
      await textarea.setValue('错');
      expect(submitBtn.classes()).toContain('disabled');

      // Enter >= 2 characters -> enabled
      await textarea.setValue('已包含互斥与不可剥夺条件');
      expect(submitBtn.classes()).not.toContain('disabled');
    });

    it('submits regrade request successfully and emits submit & success events', async () => {
      const regradeSpy = vi.spyOn(diagnosisApi, 'requestRegrade').mockResolvedValue({
        code: 0,
        message: 'success',
        data: { attempt_item_id: 'att_002', status: 'success', score: 4.2 },
      });

      const wrapper = mount(RegradeModal, {
        props: {
          visible: true,
          attemptItemId: 'att_002',
        },
      });

      const textarea = wrapper.find('.reason-textarea');
      await textarea.setValue('模型未识别到核心公式证明过程');

      const submitBtn = wrapper.find('.btn-primary');
      await submitBtn.trigger('tap');

      expect(regradeSpy).toHaveBeenCalledTimes(1);
      expect(regradeSpy).toHaveBeenCalledWith({
        attempt_item_id: 'att_002',
        reason: '模型未识别到核心公式证明过程',
      });

      expect(wrapper.emitted('submit')?.[0]).toEqual([
        {
          attempt_item_id: 'att_002',
          reason: '模型未识别到核心公式证明过程',
        },
      ]);
      // success 事件必须携带重判真实终态与回传新分数，供上层就地更新
      expect(wrapper.emitted('success')?.[0]).toEqual([
        {
          attempt_item_id: 'att_002',
          reason: '模型未识别到核心公式证明过程',
          status: 'success',
          score: 4.2,
        },
      ]);
      expect(wrapper.emitted('update:visible')?.[0]).toEqual([false]);
    });

    it('handles regrade API failure gracefully', async () => {
      vi.spyOn(diagnosisApi, 'requestRegrade').mockResolvedValue({
        code: 50001,
        message: '重判服务繁忙',
        data: null as unknown as { attempt_item_id: string; status: string },
      });

      const wrapper = mount(RegradeModal, {
        props: {
          visible: true,
          attemptItemId: 'att_002',
        },
      });

      const textarea = wrapper.find('.reason-textarea');
      await textarea.setValue('重判理由完整充分');

      const submitBtn = wrapper.find('.btn-primary');
      await submitBtn.trigger('tap');

      expect(wrapper.emitted('submit')).toBeTruthy();
      expect(wrapper.emitted('success')).toBeFalsy();
    });

    it('emits update:visible(false) when close or cancel button is tapped', async () => {
      const wrapper = mount(RegradeModal, {
        props: {
          visible: true,
          attemptItemId: 'att_002',
        },
      });

      const closeBtn = wrapper.find('.close-btn');
      await closeBtn.trigger('tap');
      expect(wrapper.emitted('update:visible')?.[0]).toEqual([false]);

      const cancelBtn = wrapper.find('.btn-secondary');
      await cancelBtn.trigger('tap');
      expect(wrapper.emitted('update:visible')?.[1]).toEqual([false]);
    });
  });
});
