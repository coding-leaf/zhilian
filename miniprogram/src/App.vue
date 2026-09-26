<template>
  <view />
</template>

<script setup lang="ts">
import { onLaunch, onShow, onHide } from '@dcloudio/uni-app';
import { useUserStore } from './stores/userStore';

const userStore = useUserStore();

onLaunch(() => {
  userStore.initFromStorage();
  void userStore.hydrateProfile();
});

onShow(() => {
  // 应用进入前台运行，静默水合校验最新画像
  void userStore.hydrateProfile();
});

onHide(() => {
  // 应用进入后台运行
});
</script>

<style lang="scss">
@import './uni.scss';
</style>
