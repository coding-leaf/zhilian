<template>
  <view />
</template>

<script setup lang="ts">
import { onLaunch, onShow, onHide } from '@dcloudio/uni-app';
import { useUserStore } from './stores/userStore';

const userStore = useUserStore();

onLaunch(() => {
  userStore.initFromStorage();
});

onShow(() => {
  // 应用进入前台运行
});

onHide(() => {
  // 应用进入后台运行
});
</script>

<style lang="scss">
@import './uni.scss';
</style>
