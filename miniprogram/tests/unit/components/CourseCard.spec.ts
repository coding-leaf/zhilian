import { describe, it, expect, vi, beforeEach } from 'vitest';
import { mount } from '@vue/test-utils';
import CourseCard from '@/components/course/CourseCard.vue';
import type { FolderItem } from '@/types/folder';

const EMOJI_REGEX = /[\u{1F300}-\u{1FAFF}\u{1F600}-\u{1F64F}\u{1F680}-\u{1F6FF}\u{2600}-\u{26FF}]/u;

function makeFolder(overrides: Partial<FolderItem> = {}): FolderItem {
  return {
    id: 'f1',
    name: '高等数学',
    is_archived: false,
    material_count: 3,
    ready_material_count: 2,
    knowledge_point_count: 12,
    question_count: 30,
    last_practice_at: '2026-09-25T10:00:00Z',
    created_at: '2026-09-20T00:00:00Z',
    ...overrides,
  };
}

describe('CourseCard.vue', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders course name, counts and recent practice meta', () => {
    const wrapper = mount(CourseCard, { props: { folder: makeFolder() } });

    expect(wrapper.text()).toContain('高等数学');
    expect(wrapper.text()).toContain('3');
    expect(wrapper.text()).toContain('12');
    expect(wrapper.text()).toContain('30');
    expect(wrapper.text()).toContain('资料');
    expect(wrapper.text()).toContain('考点');
    expect(wrapper.text()).toContain('题目');
    expect(wrapper.text()).toContain('最近练习 09-25');
  });

  it('falls back to ready count when no practice history exists', () => {
    const wrapper = mount(CourseCard, {
      props: { folder: makeFolder({ last_practice_at: null }) },
    });
    expect(wrapper.text()).toContain('2 份已就绪');
  });

  it('emits enter, rename and archive with the folder payload', async () => {
    const folder = makeFolder();
    const wrapper = mount(CourseCard, { props: { folder } });

    await wrapper.trigger('tap');
    expect(wrapper.emitted('enter')?.[0]).toEqual([folder]);

    const links = wrapper.findAll('.action-link');
    await links[0].trigger('tap');
    expect(wrapper.emitted('rename')?.[0]).toEqual([folder]);

    await links[1].trigger('tap');
    expect(wrapper.emitted('archive')?.[0]).toEqual([folder]);
  });

  it('strictly satisfies zero-emoji policy', () => {
    const wrapper = mount(CourseCard, { props: { folder: makeFolder() } });
    expect(EMOJI_REGEX.test(wrapper.text())).toBe(false);
  });
});
