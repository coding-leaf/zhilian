import { describe, expect, it } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { adaptKnowledgeSnippet, adaptStructuredContent } from '@/api/adapters/knowledge'
import KnowledgeSnippetModal from '@/subpackages/material/components/KnowledgeSnippetModal.vue'
import {
  formatSnippetPageRange,
  hasStructuredContent,
  trimSnippetExcerpt,
} from '@/subpackages/material/utils/courseStudy'
import type { KnowledgeSnippet, KnowledgeTreeNode } from '@/types'

function buildPoint(overrides: Partial<KnowledgeTreeNode> = {}): KnowledgeTreeNode {
  return {
    id: 'kp-svm',
    material_id: 'm-1',
    version_id: 'v-1',
    parent_id: 'kp-ch',
    name: '软间隔支持向量机',
    description: '允许部分样本违背最大间隔约束的分类模型',
    structured_content: {
      core_summary: '引入松弛变量并权衡间隔最大化与分类误差，提升线性不可分或含噪数据的泛化能力。',
      key_takeaways: [
        '松弛变量越大表示对应样本偏离正确间隔的程度越大',
        '惩罚系数 C 越大对误分类的惩罚越重，模型越倾向过拟合',
      ],
      key_formulas: [
        '$\\min_{w,b,\\xi} \\frac{1}{2}\\|w\\|^2 + C\\sum_{i=1}^n \\xi_i$，其中 $w$ 为法向量，$C>0$ 为惩罚系数',
      ],
      derivation_steps: [
        '构造含松弛变量与非负约束的原始优化目标',
        '引入拉格朗日乘子并利用 KKT 条件消去原始变量',
        '求解对偶二次规划得到支持向量及分类超平面',
      ],
      boundary_notes: [
        '硬间隔要求严格线性可分，软间隔适用于轻度线性不可分或存在噪声点的数据',
      ],
      common_mistakes: [
        '误区：增大 C 一定提升泛化能力；正解：C 过大易过拟合训练噪声',
      ],
    },
    level: 2,
    sort_order: 1,
    children: [],
    ...overrides,
  }
}

const modalStubs = {
  RichContent: {
    props: ['content'],
    template: '<div class="stub-rich">{{ content }}</div>',
  },
  'scroll-view': {
    template: '<div><slot /></div>',
  },
}

describe('knowledge review card adaptation & rendering', () => {
  it('adapts 6-field structured_content and remains backward compatible with 4-field data', () => {
    const full = adaptStructuredContent({
      core_summary: '  核技巧通过内积映射隐式升维  ',
      key_takeaways: ['  将低维线性不可分映射为高维线性可分  ', '  '],
      key_formulas: ['K(x, z) = \\langle \\phi(x), \\phi(z) \\rangle'],
      derivation_steps: ['步骤一：写对偶内积', '步骤二：替换为核函数'],
      boundary_notes: ['核函数需满足 Mercer 半正定条件'],
      common_mistakes: ['混淆高斯核带宽参数对过拟合的影响'],
    })

    expect(full).toEqual({
      core_summary: '核技巧通过内积映射隐式升维',
      key_takeaways: ['将低维线性不可分映射为高维线性可分'],
      key_formulas: ['K(x, z) = \\langle \\phi(x), \\phi(z) \\rangle'],
      derivation_steps: ['步骤一：写对偶内积', '步骤二：替换为核函数'],
      boundary_notes: ['核函数需满足 Mercer 半正定条件'],
      common_mistakes: ['混淆高斯核带宽参数对过拟合的影响'],
    })

    const legacy = adaptStructuredContent({
      core_summary: '旧版四字段摘要',
      key_takeaways: ['要点一'],
      key_formulas: [],
      boundary_notes: ['边界一'],
    })

    expect(legacy).toEqual({
      core_summary: '旧版四字段摘要',
      key_takeaways: ['要点一'],
      key_formulas: [],
      derivation_steps: [],
      boundary_notes: ['边界一'],
      common_mistakes: [],
    })

    expect(adaptStructuredContent(null)).toBeNull()
  })

  it('adapts WireSnippetSource page_end to KnowledgeSnippet.pageEnd and formats page ranges', () => {
    const merged = adaptKnowledgeSnippet({
      id: 's-1',
      page_index: 12,
      page_end: 13,
      chapter_title: ' 第三章 核方法 ',
      content: '跨页合并内容',
    })
    const single = adaptKnowledgeSnippet({
      id: 's-2',
      page_index: 5,
      page_end: null,
      content: '单页内容',
    })
    const samePage = adaptKnowledgeSnippet({
      id: 's-3',
      page_index: 5,
      page_end: 5,
      content: '同页值回退为 null',
    })

    expect(merged.pageEnd).toBe(13)
    expect(single.pageEnd).toBeNull()
    expect(samePage.pageEnd).toBeNull()

    expect(formatSnippetPageRange(12, 13)).toBe('第 12–13 页')
    expect(formatSnippetPageRange(5, null)).toBe('第 5 页')
    expect(formatSnippetPageRange(5, 5)).toBe('第 5 页')
  })

  it('checks structured content presence and trims long excerpts without breaking math', () => {
    expect(
      hasStructuredContent({
        core_summary: '',
        key_takeaways: [],
        key_formulas: [],
        derivation_steps: ['仅推导步骤非空'],
        boundary_notes: [],
        common_mistakes: [],
      }),
    ).toBe(true)

    expect(
      hasStructuredContent({
        core_summary: '   ',
        key_takeaways: [],
        key_formulas: [],
        derivation_steps: [],
        boundary_notes: [],
        common_mistakes: [],
      }),
    ).toBe(false)

    const longContent =
      '第一句讲解基本思想，保证完整可读。'
      + '第二句给出核心公式 $f(x) = \\sum_{i=1}^n \\alpha_i y_i K(x_i, x) + b$，'
      + '其中系数满足对偶约束条件。'
      + '补充说明：'.repeat(30)
      + '结尾句。'
    const trimmed = trimSnippetExcerpt(longContent, 120)
    expect(trimmed.truncated).toBe(true)
    expect(trimmed.text.endsWith('…')).toBe(true)
    const dollarCount = (trimmed.text.match(/\$/g) ?? []).length
    expect(dollarCount % 2).toBe(0)
  })

  it('renders 5-section review card, page ranges, garbled guard, and expand/collapse toggle', async () => {
    const longSnippetText =
      '支持向量机通过最大化分类间隔寻找最优超平面。'
      + '在线性不可分场景下引入松弛变量与惩罚系数权衡经验误差。'.repeat(12)
    const snippets: KnowledgeSnippet[] = [
      {
        id: 'snip-1',
        page_index: 12,
        pageEnd: 13,
        chapter_title: '第 3 章 软间隔',
        content: longSnippetText,
      },
      {
        id: 'snip-2',
        page_index: 15,
        pageEnd: null,
        chapter_title: '第 3 章 对偶问题',
        content: '原始目标含 ☒_{i=1}^n 损坏字形',
      },
    ]

    const wrapper = mount(KnowledgeSnippetModal, {
      props: {
        visible: true,
        point: buildPoint(),
        pointDetail: null,
        pointHierarchy: '第三章 > 软间隔支持向量机',
        masteryEntry: { score: 0.72, level: 'basic', practiceCount: 2 },
        snippets,
        loadingSnippets: false,
        snippetLoadFailed: false,
      },
      global: { stubs: modalStubs },
    })

    expect(wrapper.text()).toContain('核心定义与直觉')
    expect(wrapper.text()).toContain('关键结论与要点')
    expect(wrapper.text()).toContain('核心公式与符号')
    expect(wrapper.text()).toContain('推导 / 解题步骤')
    expect(wrapper.text()).toContain('适用条件与易错边界')
    expect(wrapper.text()).toContain('高频易错点')
    expect(wrapper.text()).toContain('易错辨析')
    expect(wrapper.findAll('.step-index').map((n) => n.text())).toEqual(['1', '2', '3'])

    await wrapper.get('.snippet-toggle-row').trigger('tap')
    await flushPromises()

    expect(wrapper.findAll('.snip-page').map((n) => n.text())).toEqual(['第 12–13 页', '第 15 页'])
    expect(wrapper.text()).toContain('检测到旧版讲义公式编码异常')
    expect(wrapper.text()).not.toContain('☒')

    const expandBtn = wrapper.get('.snip-expand-btn')
    expect(expandBtn.text()).toBe('展开全文')
    expect(wrapper.text()).not.toContain(longSnippetText)

    await expandBtn.trigger('tap')
    await flushPromises()
    expect(wrapper.get('.snip-expand-btn').text()).toBe('收起')
    expect(wrapper.text()).toContain(longSnippetText)

    wrapper.unmount()
  })

  it('hides empty sections on legacy 4-field data and renders friendly empty evidence prompt', async () => {
    const legacyPoint = buildPoint({
      structured_content: {
        core_summary: '旧版四字段摘要内容',
        key_takeaways: ['要点一'],
        key_formulas: [],
        boundary_notes: ['适用边界说明'],
      },
    })

    const wrapper = mount(KnowledgeSnippetModal, {
      props: {
        visible: true,
        point: legacyPoint,
        pointDetail: null,
        pointHierarchy: '',
        snippets: [],
        loadingSnippets: false,
        snippetLoadFailed: false,
      },
      global: { stubs: modalStubs },
    })

    expect(wrapper.text()).toContain('核心定义与直觉')
    expect(wrapper.text()).toContain('关键结论与要点')
    expect(wrapper.text()).toContain('适用条件与易错边界')
    expect(wrapper.text()).not.toContain('核心公式与符号')
    expect(wrapper.text()).not.toContain('推导 / 解题步骤')
    expect(wrapper.text()).not.toContain('高频易错点')

    await wrapper.get('.snippet-toggle-row').trigger('tap')
    await flushPromises()
    expect(wrapper.text()).toContain('当前暂无高质量教材原文依据，建议点击讲义页「重新解析」升级')

    wrapper.unmount()
  })
})
