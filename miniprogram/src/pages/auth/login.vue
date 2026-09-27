<template>
  <view class="login-page">
    <view class="login-card">
      <view class="brand-badge">智练平台</view>
      <view class="login-title">账号授权登录</view>
      <view class="login-desc">登录后即可同步学习资料、生成智能诊断与练习题库</view>

      <view class="action-section">
        <button
          class="wechat-login-btn"
          :loading="isSubmitting"
          :disabled="isSubmitting"
          @tap="handleWeChatLogin"
        >
          微信一键登录
        </button>

        <button class="back-btn" :disabled="isSubmitting" @tap="handleNavigateBack">
          返回工作台
        </button>
      </view>

      <view class="agreement-notice">登录即代表同意用户服务协议与隐私保护指引</view>
    </view>
  </view>
</template>

<script setup lang="ts">
import { ref } from 'vue';
import { useUserStore } from '@/stores/userStore';
import { loginByWechat } from '@/api/auth';

const userStore = useUserStore();
const isSubmitting = ref(false);

async function handleWeChatLogin(): Promise<void> {
  if (isSubmitting.value) {
    return;
  }
  isSubmitting.value = true;

  try {
    let code = 'dev_code';
    if (typeof uni !== 'undefined' && typeof uni.login === 'function') {
      try {
        const loginRes = await new Promise<UniApp.LoginRes>((resolve, reject) => {
          uni.login({
            provider: 'weixin',
            success: resolve,
            fail: reject,
          });
        });
        if (loginRes?.code) {
          code = loginRes.code;
        }
      } catch {
        // 在无微信真实客户端或开发测试环境下使用标准开发 code
        code = 'dev_code';
      }
    }

    // 不提交硬编码昵称/头像：未获取真实微信画像时保持字段缺省，
    // 由后端仅在字段被显式提供且非空时更新，避免覆盖用户真实画像。
    const res = await loginByWechat({ code });

    if (!res?.data?.access_token) {
      throw new Error(res?.message || '登录失败，未获取到有效凭据');
    }

    userStore.setTokens(res.data);

    userStore.setUserProfile({
      id: 'usr_current',
      nickname: '学员用户',
      avatar_url: '',
      created_at: new Date().toISOString(),
    });

    void userStore.hydrateProfile();

    uni.showToast({
      title: '登录成功',
      icon: 'success',
    });

    setTimeout(() => {
      uni.reLaunch({
        url: '/pages/index/index',
      });
    }, 500);
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : '登录失败，请重试';
    uni.showToast({
      title: message,
      icon: 'none',
    });
  } finally {
    isSubmitting.value = false;
  }
}

function handleNavigateBack(): void {
  uni.reLaunch({
    url: '/pages/index/index',
  });
}
</script>

<style lang="scss" scoped>
.login-page {
  min-height: 100vh;
  background-color: #f8fafc;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40rpx;
  box-sizing: border-box;
}

.login-card {
  width: 100%;
  background-color: #ffffff;
  border-radius: 24rpx;
  padding: 48rpx 36rpx;
  border: 1px solid #e2e8f0;
  box-shadow:
    0 8rpx 24rpx -4rpx rgba(15, 23, 42, 0.05),
    0 2rpx 6rpx -1rpx rgba(15, 23, 42, 0.02);
  text-align: center;
  box-sizing: border-box;
}

.brand-badge {
  display: inline-block;
  font-size: 22rpx;
  color: #2563eb;
  background-color: #eff6ff;
  border: 1px solid #bfdbfe;
  padding: 4rpx 16rpx;
  border-radius: 9999rpx;
  font-weight: 600;
  margin-bottom: 24rpx;
}

.login-title {
  font-size: 36rpx;
  font-weight: 700;
  color: #0f172a;
  margin-bottom: 12rpx;
}

.login-desc {
  font-size: 24rpx;
  color: #64748b;
  line-height: 1.5;
  margin-bottom: 48rpx;
}

.action-section {
  display: flex;
  flex-direction: column;
  gap: 20rpx;
}

.wechat-login-btn {
  height: 88rpx;
  line-height: 88rpx;
  border-radius: 9999rpx;
  background-color: #2563eb;
  color: #ffffff;
  font-size: 28rpx;
  font-weight: 700;
  border: none;
  box-shadow: 0 8rpx 20rpx -2rpx rgba(37, 99, 235, 0.32);

  &:active {
    background-color: #1d4ed8;
    transform: scale(0.985);
  }
}

.back-btn {
  height: 88rpx;
  line-height: 88rpx;
  border-radius: 9999rpx;
  background-color: #f1f5f9;
  color: #475569;
  font-size: 28rpx;
  font-weight: 600;
  border: 1px solid #e2e8f0;

  &:active {
    background-color: #e2e8f0;
  }
}

.agreement-notice {
  font-size: 20rpx;
  color: #94a3b8;
  margin-top: 36rpx;
}
</style>
