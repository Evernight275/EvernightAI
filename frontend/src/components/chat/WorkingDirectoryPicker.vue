<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue';
import { ArrowUp, ChevronRight, File, Folder, FolderPlus, X } from '@lucide/vue';
import {
  browseWorkspace,
  createWorkspace,
  listWorkspaceProjects,
  addWorkspaceProject,
  type WorkspaceDirectory,
  type WorkspaceProject,
} from '../../api/workspaces';
import { workingDirectory, workingRoot } from '../../runtime/workingDirectory';
import { useDialog } from '../common/dialog';

let mounted = true;
onUnmounted(() => {
  mounted = false;
});
const open = ref(false);
const listing = ref<WorkspaceDirectory | null>(null);
const busy = ref(false);
const error = ref('');
const name = ref('');
const creating = ref(false);
const projects = ref<WorkspaceProject[]>([]);
const projectPath = ref('');
const fullPath = computed(() =>
  workingDirectory.value && /^(\/|[A-Za-z]:[\\/])/.test(workingDirectory.value)
    ? workingDirectory.value
    : `${workingRoot.value}/${workingDirectory.value || ''}`,
);
const canGoParent = computed(
  () => listing.value && listing.value.path !== '.' && listing.value.path !== listing.value.root,
);
const dialog = useDialog(
  () => open.value,
  () => {
    open.value = false;
  },
);
const label = computed(() =>
  workingDirectory.value && workingDirectory.value !== '.'
    ? workingDirectory.value.split(/[\\/]/).at(-1)
    : '工作文件夹',
);
async function load(path = '.') {
  if (busy.value) return;
  busy.value = true;
  error.value = '';
  try {
    const result = await browseWorkspace(path);
    if (!result.root || !Array.isArray(result.entries)) throw new Error('当前服务不支持工作文件夹');
    listing.value = result;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '无法读取文件夹';
  } finally {
    busy.value = false;
  }
}
async function show() {
  open.value = true;
  name.value = '';
  creating.value = false;
  projectPath.value = '';
  await Promise.all([load(workingDirectory.value || '.'), loadProjects()]);
}
async function loadProjects() {
  try {
    projects.value = await listWorkspaceProjects();
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '无法读取项目列表';
  }
}
async function openProject() {
  if (busy.value || !projectPath.value.trim()) return;
  busy.value = true;
  error.value = '';
  try {
    listing.value = await addWorkspaceProject(projectPath.value.trim());
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '无法打开项目';
  } finally {
    busy.value = false;
  }
  if (!error.value) choose();
}
function choose() {
  if (!listing.value || busy.value || error.value) return;
  workingDirectory.value = listing.value.path;
  workingRoot.value = listing.value.root;
  localStorage.setItem(
    'evernight.workingDirectory',
    JSON.stringify({ root: workingRoot.value, path: workingDirectory.value }),
  );
  open.value = false;
}
async function create() {
  if (!listing.value || busy.value || !name.value.trim()) return;
  busy.value = true;
  error.value = '';
  try {
    listing.value = await createWorkspace(listing.value.path, name.value.trim());
    name.value = '';
    creating.value = false;
  } catch (cause) {
    error.value = cause instanceof Error ? cause.message : '创建失败';
  } finally {
    busy.value = false;
  }
}
function parent() {
  if (listing.value?.parent) {
    void load(listing.value.parent);
    return;
  }
  if (!canGoParent.value) return;
  const parts = listing.value?.path.split('/') || [];
  parts.pop();
  void load(parts.join('/') || '.');
}
onMounted(async () => {
  const saved = localStorage.getItem('evernight.workingDirectory');
  if (!saved) return;
  try {
    const value = JSON.parse(saved) as { root: string; path: string };
    const directory = await browseWorkspace(value.path);
    if (mounted && directory.root === value.root) {
      workingDirectory.value = directory.path;
      workingRoot.value = directory.root;
    }
  } catch {
    localStorage.removeItem('evernight.workingDirectory');
  }
});
</script>
<template>
  <button
    class="chat-workspace-button"
    type="button"
    aria-label="选择工作文件夹"
    aria-haspopup="dialog"
    :title="workingDirectory ? fullPath : '打开项目或切换工作文件夹'"
    @click="show"
  >
    <Folder :size="17" aria-hidden="true" /><span
      >{{ label }}<small>{{ workingDirectory ? '点击切换' : '浏览与切换' }}</small></span
    ><ChevronRight :size="15" aria-hidden="true" />
  </button>
  <dialog
    :ref="dialog.setDialog"
    class="workspace-picker-dialog"
    aria-labelledby="workspace-picker-title"
    @cancel="dialog.onCancel"
    @click="dialog.onBackdropClick"
    @keydown="dialog.onKeydown"
  >
    <header>
      <div>
        <h2 id="workspace-picker-title">工作文件夹</h2>
        <p>选择当前项目，文件、终端、Git 和项目任务会一起切换。</p>
      </div>
      <button class="icon-button" aria-label="关闭工作文件夹" autofocus @click="open = false">
        <X :size="18" />
      </button>
    </header>
    <div class="workspace-picker-body">
      <form class="workspace-open-form" @submit.prevent="openProject">
        <label for="workspace-project-path">打开已有项目</label>
        <div>
          <input
            id="workspace-project-path"
            v-model="projectPath"
            aria-label="现有项目路径"
            placeholder="后端主机上的项目绝对路径"
            :disabled="busy"
          />
          <button :disabled="busy || !projectPath.trim()">添加并打开</button>
        </div>
      </form>
      <label v-if="projects.length" class="workspace-project-select">
        已添加项目
        <select
          aria-label="已添加项目"
          :value="listing?.root"
          :disabled="busy"
          @change="load(($event.target as HTMLSelectElement).value)"
        >
          <option v-for="project in projects" :key="project.path" :value="project.path">
            {{ project.name }} · {{ project.path }}
          </option>
        </select>
      </label>
      <p class="workspace-root" v-if="listing">{{ listing.root }}</p>
      <div class="workspace-picker-toolbar">
        <button :disabled="busy || !canGoParent" aria-label="上一级文件夹" @click="parent">
          <ArrowUp :size="16" /></button
        ><strong>{{ listing?.path === '.' ? '根目录' : listing?.path || '选择目录' }}</strong
        ><button :disabled="busy || !listing" @click="creating = !creating">
          <FolderPlus :size="16" /> 新建
        </button>
      </div>
      <form v-if="creating" class="workspace-create-form" @submit.prevent="create">
        <input
          v-model="name"
          aria-label="新文件夹名称"
          placeholder="文件夹名称"
          :disabled="busy"
          maxlength="200"
        /><button :disabled="busy || !name.trim()">创建文件夹</button>
      </form>
      <p v-if="error" role="alert" class="chat-status-error">
        {{ error }} <button :disabled="busy" @click="load('.')">返回根目录</button>
      </p>
      <p v-if="busy" role="status">正在读取…</p>
      <ul v-else-if="listing" class="workspace-file-list" aria-label="工作文件夹内容">
        <li v-for="entry in listing.entries" :key="entry.path">
          <button v-if="entry.is_directory" @click="load(entry.path)">
            <Folder :size="17" /><span>{{ entry.name }}</span
            ><ChevronRight :size="15" />
          </button>
          <div v-else>
            <File :size="17" /><span>{{ entry.name }}</span>
          </div>
        </li>
      </ul>
      <p v-if="listing && !listing.entries.length && !busy" class="workspace-empty">
        此文件夹为空，可以作为新的工作目录。
      </p>
      <p v-if="listing?.truncated" class="workspace-empty">仅显示前 500 项。</p>
    </div>
    <footer>
      <p>切换对下一次请求生效；运行中的任务继续使用原项目。</p>
      <button class="button-primary" :disabled="busy || !listing || !!error" @click="choose">
        使用此文件夹
      </button>
    </footer>
  </dialog>
</template>
