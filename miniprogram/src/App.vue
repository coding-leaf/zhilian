<script setup lang="ts">
import { onLaunch, onShow, onHide } from '@dcloudio/uni-app'

onLaunch(() => {
  console.log('App Launch: 智练温润学术版')
})

onShow(() => {
  console.log('App Show')
})

onHide(() => {
  console.log('App Hide')
})
</script>

<style>
/* 温润学术 Design Tokens 全局基础变量与样式 */
page {
  --color-paper-bg: #F7F5F0;
  --color-paper-card: #FFFFFF;
  --color-ink-primary: #1C1917;
  --color-ink-secondary: #57534E;
  --color-ink-muted: #A8A29E;
  --color-academic-blue: #1E3A8A;
  --color-academic-teal: #0D9488;
  --color-warm-amber: #D97706;
  --color-paper-border: #E7E5E4;
  --color-correct: #15803D;
  --color-wrong: #B91C1C;

  background-color: var(--color-paper-bg);
  color: var(--color-ink-primary);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
  -webkit-font-smoothing: antialiased;
}

view, text, button, input {
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
  color: #FFFFFF;
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
