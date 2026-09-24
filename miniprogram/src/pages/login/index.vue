<template>
  <view class="login-forwarder">
    <LoginAuthPage />
  </view>
</template>

<script setup lang="ts">
import LoginAuthPage from '../auth/login.vue';
</script>

<style lang="scss" scoped>
.login-forwarder {
  min-height: 100vh;
}
</style>
