<script setup lang="ts">
import { onLaunch, onShow, onHide } from '@dcloudio/uni-app'
import { useAuthStore } from '@/stores/auth'
import { useBackgroundTaskStore } from '@/stores/backgroundTask'
import { initKatexFonts } from '@/utils/katexFonts'

onLaunch(() => {
  console.log('App Launch: 智练温润学术版')
  initKatexFonts()
})

onShow(() => {
  console.log('App Show')
  try {
    const authStore = useAuthStore()
    if (authStore.isLoggedIn()) {
      void useBackgroundTaskStore().refreshActiveTasks()
    }
  } catch (err) {
    console.error('[App] onShow 恢复后台轮询失败:', err)
  }
})

onHide(() => {
  console.log('App Hide')
  try {
    useBackgroundTaskStore().stopPolling()
  } catch (err) {
    console.error('[App] onHide 暂停后台轮询失败:', err)
  }
})
</script>

<style lang="scss">
@import '@/styles/katex-mp.scss';

/* 温润学术 Design Tokens 全局基础变量与样式 */
page {
  --color-paper-bg: #F7F5F0;
  --color-paper-card: #FFFFFF;
  --color-bg-card: #FFFFFF;
  --color-ink-primary: #1C1917;
  --color-ink-body: #44403C;
  --color-ink-secondary: #57534E;
  --color-ink-subtle: #78716C;
  --color-ink-muted: #A8A29E;
  --color-ink-slate: #334155;
  --color-ink-slate-muted: #475569;
  --color-ink-slate-subtle: #64748B;
  --color-ink-on-primary: #FFFFFF;

  --color-surface-subtle: #FAFAF9;
  --color-surface-muted: #F5F5F4;
  --color-surface-slate: #F8FAFC;
  --color-surface-warm: #FBFBF9;

  --color-paper-border: #E7E5E4;
  --color-border-strong: #D6D3D1;
  --color-border-slate: #CBD5E1;

  --color-academic-blue: #1E3A8A;
  --color-blue-accent: #3B82F6;
  --color-blue-bg: #EFF6FF;
  --color-blue-border: #BFDBFE;
  --color-blue-border-strong: #93C5FD;
  --color-blue-tint: rgba(30, 58, 138, 0.08);
  --color-blue-shadow: rgba(30, 58, 138, 0.35);
  --color-blue-badge: rgba(30, 58, 138, 0.8);

  --color-academic-teal: #0D9488;
  --color-teal-dark: #245C51;
  --color-teal-accent: #176B62;
  --color-teal-bg: #EEF7F4;
  --color-teal-tint: rgba(13, 148, 136, 0.1);

  --color-correct: #15803D;
  --color-success: #059669;
  --color-success-strong: #166534;
  --color-success-bg: #ECFDF5;
  --color-success-bg-soft: #F0FDF4;
  --color-success-border: #86EFAC;
  --color-success-border-soft: #BBF7D0;

  --color-warm-amber: #D97706;
  --color-warning-strong: #B45309;
  --color-warning-deep: #92400E;
  --color-warning-dark: #78350F;
  --color-warning-bg: #FFFBEB;
  --color-warning-bg-strong: #FEF3C7;
  --color-warning-border: #FDE68A;

  --color-orange: #EA580C;
  --color-orange-strong: #C2410C;
  --color-orange-deep: #9A3412;
  --color-orange-bg: #FFF7ED;
  --color-orange-border: #FED7AA;

  --color-wrong: #B91C1C;
  --color-danger: #DC2626;
  --color-danger-strong: #991B1B;
  --color-danger-bg: #FEF2F2;
  --color-danger-bg-soft: #FEE2E2;
  --color-danger-border: #FECACA;
  --color-danger-border-strong: #FCA5A5;

  --color-sky: #0284C7;
  --color-sky-bg: #E0F2FE;
  --color-purple: #7E22CE;
  --color-purple-bg: #F3E8FF;

  --color-overlay: rgba(28, 25, 23, 0.45);
  --color-overlay-strong: rgba(28, 25, 23, 0.45);
  --color-bar-bg: #FFFFFF;
  --color-scrim-light: rgba(28, 25, 23, 0.08);
  --color-white-translucent: rgba(255, 255, 255, 0.2);

  --shadow-bar: 0 -6rpx 20rpx rgba(28, 25, 23, 0.06);
  --shadow-sheet: 0 -12rpx 36rpx rgba(28, 25, 23, 0.12);
  --shadow-modal: 0 12rpx 36rpx rgba(28, 25, 23, 0.14);

  --z-sticky: 20;
  --z-bottom-bar: 40;
  --z-fab: 60;
  --z-sheet: 200;
  --z-coach: 300;
  --z-modal: 400;

  background-color: var(--color-paper-bg);
  color: var(--color-ink-primary);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
}

view, text, scroll-view, textarea, button, input {
  box-sizing: border-box;
}

/* 统一学术书卷卡片样式 */
.paper-card {
  background: var(--color-paper-card);
  border: 1px solid var(--color-paper-border);
  border-radius: 16rpx;
  box-shadow: 0 4rpx 16rpx rgba(28, 25, 23, 0.03);
}

.paper-btn-primary {
  background-color: var(--color-academic-blue);
  color: var(--color-ink-on-primary);
  border-radius: 12rpx;
  font-weight: 500;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: opacity 0.2s;
}

.paper-btn-primary:active {
  opacity: 0.85;
}
</style>
