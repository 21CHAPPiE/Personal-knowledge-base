import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'dashboard', component: () => import('../views/Dashboard.vue') },
    { path: '/knowledge', name: 'knowledge', component: () => import('../views/KnowledgeList.vue') },
    { path: '/knowledge/new', name: 'knowledge-new', component: () => import('../views/KnowledgeCreate.vue') },
    { path: '/knowledge/:id', name: 'knowledge-detail', component: () => import('../views/KnowledgeDetail.vue'), props: true },
    { path: '/projects', name: 'projects', component: () => import('../views/Projects.vue') },
    { path: '/projects/:id', name: 'project-detail', component: () => import('../views/ProjectDetail.vue'), props: true },
    { path: '/search', name: 'search', component: () => import('../views/Search.vue') },
    { path: '/graph', name: 'graph', component: () => import('../views/KnowledgeGraph.vue') },
    { path: '/review', name: 'review', component: () => import('../views/Review.vue') },
    { path: '/:pathMatch(.*)*', name: 'not-found', component: () => import('../views/Dashboard.vue') },
  ],
})

export default router
