<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { createKnowledge, listProjects } from '../api/client'
import type { Project } from '../types'

type Mode = 'text' | 'screenshot' | 'voice'

const router = useRouter()
const mode = ref<Mode>('text')
const projects = ref<Project[]>([])
const project_id = ref<number | ''>('')
const title = ref('')
const content = ref('')
const tags = ref('')
const error = ref('')
const notice = ref('')
const busy = ref(false)

// screenshot
const imageFile = ref<File | null>(null)
const imagePreview = ref('')

// voice
const recording = ref(false)
const seconds = ref(0)
const audioBlob = ref<Blob | null>(null)
const audioPreview = ref('')
const recorderSupported = typeof MediaRecorder !== 'undefined'

let mediaRecorder: MediaRecorder | null = null
let timer: number | null = null

onMounted(async () => {
  try {
    projects.value = await listProjects()
  } catch {
    /* project list is optional here */
  }
})

function pickImage(useCamera: boolean) {
  const input = document.createElement('input')
  input.type = 'file'
  input.accept = 'image/*'
  if (useCamera) input.setAttribute('capture', 'environment')
  input.onchange = () => {
    const f = input.files?.[0]
    if (f) {
      imageFile.value = f
      imagePreview.value = URL.createObjectURL(f)
      if (!title.value) title.value = `截图 ${new Date().toLocaleString('zh-CN', { hour12: false })}`
    }
  }
  input.click()
}

function clearImage() {
  imageFile.value = null
  imagePreview.value = ''
}

function toggleRecording() {
  if (recording.value) {
    mediaRecorder?.stop()
  } else {
    startRecording()
  }
}

async function startRecording() {
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    const mime = MediaRecorder.isTypeSupported('audio/webm') ? 'audio/webm' : ''
    mediaRecorder = new MediaRecorder(stream, mime ? { mimeType: mime } : undefined)
    const chunks: BlobPart[] = []
    mediaRecorder.ondataavailable = (e) => {
      if (e.data.size) chunks.push(e.data)
    }
    mediaRecorder.onstop = () => {
      stream.getTracks().forEach((t) => t.stop())
      audioBlob.value = new Blob(chunks, { type: mediaRecorder?.mimeType || 'audio/webm' })
      if (audioPreview.value) URL.revokeObjectURL(audioPreview.value)
      audioPreview.value = URL.createObjectURL(audioBlob.value)
      seconds.value = 0
      recording.value = false
      if (timer) window.clearInterval(timer)
      if (!title.value) title.value = `语音 ${new Date().toLocaleString('zh-CN', { hour12: false })}`
    }
    mediaRecorder.start()
    recording.value = true
    seconds.value = 0
    timer = window.setInterval(() => (seconds.value += 1), 1000)
  } catch (e) {
    error.value = `录音启动失败：${e instanceof Error ? e.message : String(e)}`
  }
}

function clearAudio() {
  audioBlob.value = null
  if (audioPreview.value) URL.revokeObjectURL(audioPreview.value)
  audioPreview.value = ''
  seconds.value = 0
  recording.value = false
  if (timer) window.clearInterval(timer)
}

function audioFileName(mime: string): string {
  const ext = mime.includes('ogg') ? 'ogg' : mime.includes('mp4') ? 'm4a' : 'webm'
  return `voice-${Date.now()}.${ext}`
}

async function submit() {
  if (busy.value) return
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    const tagList = tags.value.split(/[,，]/).map((t) => t.trim()).filter(Boolean)
    if (mode.value === 'screenshot') {
      if (!imageFile.value) throw new Error('请选择或拍摄一张图片')
      const created = await createKnowledge({
        title: title.value.trim() || '截图',
        content: content.value,
        type: 'screenshot',
        project_id: project_id.value === '' ? null : Number(project_id.value),
        tags: tagList,
        source: 'mobile',
        file: imageFile.value,
      })
      router.push(`/knowledge/${created.id}`)
    } else if (mode.value === 'voice') {
      if (!audioBlob.value) throw new Error('先录制一段语音')
      const ext = audioFileName(audioBlob.value.type)
      const file = new File([audioBlob.value], ext, { type: audioBlob.value.type })
      const created = await createKnowledge({
        title: title.value.trim() || '语音',
        content: content.value,
        type: 'voice',
        project_id: project_id.value === '' ? null : Number(project_id.value),
        tags: tagList,
        source: 'mobile',
        file,
      })
      router.push(`/knowledge/${created.id}`)
    } else {
      if (!title.value.trim()) throw new Error('标题不能为空')
      const created = await createKnowledge({
        title: title.value.trim(),
        content: content.value,
        type: 'text',
        project_id: project_id.value === '' ? null : Number(project_id.value),
        tags: tagList,
        source: 'manual',
      })
      router.push(`/knowledge/${created.id}`)
    }
  } catch (e) {
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <h1>录入知识</h1>
  <div style="display:flex;gap:6px;margin-bottom:12px;">
    <button class="btn small" :class="{ primary: mode === 'text' }" @click="mode = 'text'">文本</button>
    <button class="btn small" :class="{ primary: mode === 'screenshot' }" @click="mode = 'screenshot'">截图</button>
    <button class="btn small" :class="{ primary: mode === 'voice' }" @click="mode = 'voice'">语音</button>
  </div>

  <div v-if="notice" class="ok-bar">{{ notice }}</div>
  <div v-if="error" class="error-bar">{{ error }}</div>

  <div class="card">
    <div v-if="mode === 'screenshot'">
      <div v-if="!imageFile" style="display:flex;gap:8px;flex-wrap:wrap;">
        <button class="btn" @click="pickImage(true)">📷 拍照</button>
        <button class="btn" @click="pickImage(false)">🖼 选择图片</button>
      </div>
      <div v-else>
        <img :src="imagePreview" class="img-att" style="max-height:280px;" alt="截图预览" />
        <div style="margin-top:8px;display:flex;gap:8px;align-items:center;">
          <span style="font-size:0.82rem;color:var(--text-dim);">{{ imageFile.name }} ({{ (imageFile.size / 1024).toFixed(1) }} KB)</span>
          <button class="btn small" @click="clearImage">重选</button>
        </div>
      </div>
      <div style="font-size:0.78rem;color:var(--text-faint);margin-top:8px;">
        原图会完整保存；图片理解（OCR/VLM）后续通过 LLM Provider 接入，当前不伪装识别结果。
      </div>
    </div>

    <div v-if="mode === 'voice'">
      <div v-if="!recorderSupported" class="error-bar">浏览器不支持 MediaRecorder，建议用 Chrome / Edge / 手机浏览器</div>
      <div style="display:flex;gap:10px;align-items:center;">
        <button class="btn primary" @click="toggleRecording">
          {{ recording ? '⏹ 停止' : '⏺ 开始录音' }}
        </button>
        <span class="time" style="color:var(--text-dim);font-variant-numeric:tabular-nums;">
          {{ String(Math.floor(seconds / 60)).padStart(2, '0') }}:{{ String(seconds % 60).padStart(2, '0') }}
        </span>
        <button v-if="audioBlob" class="btn small" @click="clearAudio">重新录制</button>
      </div>
      <audio v-if="audioPreview" :src="audioPreview" controls style="margin-top:10px;" />
      <div style="font-size:0.78rem;color:var(--text-faint);margin-top:8px;">
        原始音频完整保存；配置 STT Provider 后自动转写填入正文，否则正文留空不虚构。
      </div>
    </div>

    <div class="field" style="margin-top:14px;">
      <label>标题</label>
      <input v-model="title" :placeholder="mode === 'text' ? '这条知识是什么？' : '（可留空，自动生成）'" />
    </div>
    <div class="field" v-if="mode !== 'voice' || !audioBlob">
      <label>{{ mode === 'voice' ? '补充说明（可留空）' : '正文' }}</label>
      <textarea v-model="content" rows="8" placeholder="内容…"></textarea>
    </div>
    <div class="field">
      <label>项目（可选）</label>
      <select v-model="project_id">
        <option value="">（日常知识 / 无项目）</option>
        <option v-for="p in projects" :key="p.id" :value="p.id">{{ p.name }}</option>
      </select>
    </div>
    <div class="field">
      <label>标签（逗号分隔，可选）</label>
      <input v-model="tags" placeholder="例如：架构, 部署" />
    </div>
    <button class="btn primary" :disabled="busy" @click="submit">
      {{ busy ? '保存中…' : '保存' }}
    </button>
  </div>
</template>
