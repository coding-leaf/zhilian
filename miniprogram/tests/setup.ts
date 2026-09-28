const storage = new Map<string, any>()

export const uniMock = {
  getStorageSync: (key: string) => storage.get(key) || '',
  setStorageSync: (key: string, data: any) => storage.set(key, data),
  removeStorageSync: (key: string) => storage.delete(key),
  clearStorageSync: () => storage.clear(),
  showToast: () => {},
  showLoading: () => {},
  hideLoading: () => {},
  navigateTo: () => {},
  redirectTo: () => {},
  reLaunch: () => {},
  switchTab: () => {},
  showModal: ({ success }: any) => success && success({ confirm: true }),
}

;(globalThis as any).uni = uniMock
