import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { ref } from 'vue'
import type { FolderItem } from '@/types'

const hooks = vi.hoisted(() => ({
  request: vi.fn(),
  showCbs: [] as Array<() => void>,
}))

vi.mock('@dcloudio/uni-app', () => ({
  onShow: (cb: () => void) => hooks.showCbs.push(cb),
  onPullDownRefresh: vi.fn(),
}))

vi.mock('@/utils/request', () => ({
  request: (options: unknown) => hooks.request(options),
  uploadFile: vi.fn(),
}))

import AiCoachDrawer from '@/components/AiCoachDrawer.vue'
import CoachScopeSelector from '@/components/CoachScopeSelector.vue'
import IndexPage from '@/pages/index/index.vue'
import { useHomeCoach } from '@/pages/index/composables/useHomeCoach'
import { useAuthStore } from '@/stores/auth'
import { useFolderStore } from '@/stores/folder'

function makeFolder(id: string, name: string, readyCount = 2, kpCount = 5): FolderItem {
  return {
    id,
    name,
    parent_id: null,
    sort_order: 0,
    is_archived: false,
    material_count: readyCount,
    ready_material_count: readyCount,
    knowledge_point_count: kpCount,
    question_count: 0,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  }
}

describe('Home coach decoupling & CoachScopeSelector', () => {
  let wrapper: VueWrapper | undefined

  beforeEach(() => {
    hooks.request.mockReset()
    hooks.showCbs.length = 0
    uni.clearStorageSync()
  })

  afterEach(() => {
    wrapper?.unmount()
    wrapper = undefined
  })

  it('useHomeCoach defaults to undefined (global) and resets safely when focused folder is archived', async () => {
    const folders = ref<FolderItem[]>([
      makeFolder('f-se', '软件工程', 3, 12),
      makeFolder('f-os', '操作系统', 1, 4),
    ])
    const homeCoach = useHomeCoach(() => folders.value)

    expect(homeCoach.coachFocusedFolderId.value).toBeUndefined()
    expect(homeCoach.coachTitle.value).toBe('全局学习助教')
    expect(homeCoach.coachContextText.value).toContain('全局学习模式（未限定课程）')

    homeCoach.selectCoachFolder('f-se')
    expect(homeCoach.coachFocusedFolderId.value).toBe('f-se')
    expect(homeCoach.coachTitle.value).toContain('软件工程')
    expect(homeCoach.coachContextText.value).toContain('12 个考点')

    // Simulate archiving the focused folder -> safely falls back to global (undefined)
    folders.value = [makeFolder('f-os', '操作系统', 1, 4)]
    await flushPromises()
    expect(homeCoach.coachFocusedFolderId.value).toBeUndefined()
    expect(homeCoach.coachTitle.value).toBe('全局学习助教')
  })

  it('CoachScopeSelector renders global mode by default and emits folder switches on pill tap', async () => {
    const folders = [
      makeFolder('f-se', '软件工程', 3, 12),
      makeFolder('f-os', '操作系统', 0, 0),
    ]
    wrapper = mount(CoachScopeSelector, {
      props: {
        folders,
        selectedFolderId: undefined,
      },
      global: {
        stubs: {
          'scroll-view': { template: '<div class="sv"><slot /></div>' },
        },
      },
    })

    expect(wrapper.text()).toContain('全局学习模式（未限定课程）')
    expect(wrapper.text()).toContain('全部资料 · 全局')
    expect(wrapper.text()).toContain('软件工程')

    const pills = wrapper.findAll('.scope-pill')
    expect(pills).toHaveLength(3)
    expect(pills[0].classes()).toContain('active')

    await pills[1].trigger('tap')
    expect(wrapper.emitted('select')?.[0]).toEqual(['f-se'])

    await wrapper.setProps({ selectedFolderId: 'f-se' })
    expect(wrapper.text()).toContain('聚焦课程「软件工程」')
    expect(wrapper.text()).toContain('仅检索本课程 3 份就绪资料')
    expect(wrapper.findAll('.scope-pill')[1].classes()).toContain('active')

    await wrapper.findAll('.scope-pill')[0].trigger('tap')
    expect(wrapper.emitted('select')?.[1]).toEqual([undefined])
  })

  it('AiCoachDrawer only renders CoachScopeSelector when scope selector is enabled', () => {
    setActivePinia(createPinia())

    const plainDrawer = mount(AiCoachDrawer, {
      props: {
        visible: true,
        materialId: 'm-1',
      },
      global: {
        stubs: {
          CoachMessageList: true,
        },
      },
    })
    expect(plainDrawer.findComponent(CoachScopeSelector).exists()).toBe(false)
    plainDrawer.unmount()

    const homeDrawer = mount(AiCoachDrawer, {
      props: {
        visible: true,
        selectableFolders: [makeFolder('f-se', '软件工程')],
        enableScopeSelector: true,
      },
      global: {
        stubs: {
          CoachMessageList: true,
          'scroll-view': { template: '<div><slot /></div>' },
        },
      },
    })
    expect(homeDrawer.findComponent(CoachScopeSelector).exists()).toBe(true)
    homeDrawer.unmount()
  })

  it('keeps IndexPage AiCoachDrawer in global mode regardless of folder filter or new folder creation', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    useAuthStore().setToken('tok-home')

    const folderList = [makeFolder('f-se', '软件工程', 2, 10), makeFolder('f-db', '数据库', 1, 5)]
    hooks.request.mockImplementation(async ({ url, method }: { url: string; method?: string }) => {
      if (url.startsWith('/folders') && method === 'POST') {
        return makeFolder('f-new', '计算机网络', 0, 0)
      }
      if (url.startsWith('/folders')) return { items: folderList, total: 2 }
      if (url.startsWith('/materials')) return { items: [], total: 0 }
      if (url.startsWith('/questions/jobs')) return { items: [], total: 0 }
      return {}
    })

    const drawerStub = {
      name: 'AiCoachDrawer',
      props: {
        visible: Boolean,
        title: String,
        contextText: String,
        folderId: String,
        selectableFolders: Array,
        enableScopeSelector: Boolean,
      },
      emits: ['update:visible', 'select-folder'],
      template: '<div class="drawer-stub" />',
    }

    wrapper = mount(IndexPage, {
      global: {
        plugins: [pinia],
        stubs: {
          BackgroundTaskBar: true,
          AiCoachDrawer: drawerStub,
          FolderFilterBar: {
            name: 'FolderFilterBar',
            props: ['folders', 'currentFolderId', 'activeFolder'],
            emits: ['select', 'create', 'rename', 'archive'],
            template: '<div class="filter-stub" />',
          },
          FolderFormModal: true,
          MaterialItemCard: true,
        },
      },
    })
    await flushPromises()

    const folderStore = useFolderStore()
    const drawer = wrapper.findComponent(drawerStub)
    expect(drawer.props('folderId')).toBeUndefined()
    expect(drawer.props('enableScopeSelector')).toBe(true)

    // Selecting a course in the home material filter must NOT bind the coach to it
    wrapper.findComponent({ name: 'FolderFilterBar' }).vm.$emit('select', 'f-se')
    await flushPromises()
    expect(folderStore.currentFolderId).toBe('f-se')
    expect(drawer.props('folderId')).toBeUndefined()

    // Creating a new folder switches material filter to it, but coach stays global
    await folderStore.createFolder('计算机网络')
    await flushPromises()
    expect(folderStore.currentFolderId).toBe('f-new')
    expect(drawer.props('folderId')).toBeUndefined()

    // Explicit selection inside coach drawer focuses the chosen folder, then switches back to global
    drawer.vm.$emit('select-folder', 'f-se')
    await flushPromises()
    expect(drawer.props('folderId')).toBe('f-se')

    drawer.vm.$emit('select-folder', undefined)
    await flushPromises()
    expect(drawer.props('folderId')).toBeUndefined()
  })
})
