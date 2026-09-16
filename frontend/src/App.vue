<script setup lang="ts">
import { RouterLink, RouterView } from 'vue-router'
import { globalError } from './globalError'
</script>

<template>
  <div class="topbar">
    <RouterLink to="/" class="brand">知识库</RouterLink>
    <nav>
      <RouterLink to="/">首页</RouterLink>
      <RouterLink to="/knowledge">知识</RouterLink>
      <RouterLink to="/projects">项目</RouterLink>
      <RouterLink to="/search">搜索</RouterLink>
      <RouterLink to="/graph">图谱</RouterLink>
      <RouterLink to="/review">待审</RouterLink>
      <RouterLink to="/audit">日志</RouterLink>
    </nav>
  </div>
  <!-- A page that failed and a page with nothing to show look identical to
       a viewer. This is the difference made visible, right where it
       happened, on the device where it happened — no console needed. -->
  <div v-if="globalError" class="error-bar global-error">
    <b>页面出错了：</b>{{ globalError }}
    <button class="btn small" @click="globalError = null">关闭</button>
  </div>
  <main class="main">
    <RouterView />
  </main>
  <RouterLink to="/knowledge/new" class="fab" title="快速录入">＋</RouterLink>
</template>

<style scoped>
.global-error {
  margin: 10px 16px 0;
  white-space: pre-wrap;
  word-break: break-word;
  display: flex;
  align-items: flex-start;
  gap: 10px;
}
.global-error button {
  margin-left: auto;
  flex-shrink: 0;
}
</style>
