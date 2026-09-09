<script setup lang="ts">
import { RouterLink, RouterView } from 'vue-router'
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
    </nav>
  </div>
  <main class="main">
    <RouterView />
  </main>
  <RouterLink to="/knowledge/new" class="fab" title="快速录入">＋</RouterLink>
</template>
