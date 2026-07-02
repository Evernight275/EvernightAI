# Toast 通知系统文档

## 升级时间
2025年（frontend-ui 分支）

## 升级目标
实现全局通知系统，为用户操作提供即时、优雅的反馈

---

## 1. 系统概览

### 核心组件
```
ToastContainer.vue    - 容器组件，管理所有通知
Toast.vue            - 单个通知组件
useToast.ts          - 可组合函数，提供全局 API
```

### 通知类型
- **Success** - 成功操作（绿色）
- **Error** - 错误提示（红色）
- **Warning** - 警告信息（橙色）
- **Info** - 一般信息（蓝色）

---

## 2. 使用方法

### 2.1 基本用法

```typescript
import { useToast } from '@/composables/useToast'

const toast = useToast()

// 成功通知
toast.success('操作成功')

// 错误通知
toast.error('操作失败')

// 警告通知
toast.warning('请注意')

// 信息通知
toast.info('提示信息')
```

### 2.2 自定义时长

```typescript
// 默认 3 秒
toast.success('默认显示 3 秒')

// 自定义 5 秒
toast.success('显示 5 秒', { duration: 5000 })

// 更短的 1.5 秒
toast.info('快速提示', { duration: 1500 })
```

---

## 3. 功能特性

### 3.1 自动消失
- 默认 3 秒后自动消失
- 可自定义持续时间
- 进度条显示剩余时间

### 3.2 交互控制
- **Hover 暂停**：鼠标悬停时暂停倒计时
- **手动关闭**：点击 X 按钮立即关闭
- **自动恢复**：鼠标离开后恢复倒计时

### 3.3 多通知堆叠
- 新通知从右侧滑入
- 旧通知向下平移
- 删除通知时平滑过渡

### 3.4 视觉反馈
- 图标区分类型
- 颜色编码语义
- 进度条显示时间
- 优雅的动画效果

---

## 4. 技术实现

### 4.1 组件架构

**Toast.vue**
```vue
<script setup lang="ts">
// 单个通知的生命周期管理
- 进入动画
- 倒计时
- 进度条更新
- 暂停/恢复
- 退出动画
</script>
```

**ToastContainer.vue**
```vue
<script setup lang="ts">
// 通知列表管理
- 添加通知
- 移除通知
- TransitionGroup 动画
- 暴露 API 给外部调用
</script>
```

### 4.2 状态管理

**ToastService 单例**
```typescript
class ToastService {
  private handler = null
  
  setHandler(handler) {
    this.handler = handler
  }
  
  success(message, options) {
    this.handler?.success(message, options?.duration)
  }
}

export const toast = new ToastService()
```

**初始化流程**
```typescript
// App.vue
onMounted(() => {
  if (toastContainer.value) {
    toast.setHandler({
      success: toastContainer.value.success,
      error: toastContainer.value.error,
      warning: toastContainer.value.warning,
      info: toastContainer.value.info,
    })
  }
})
```

### 4.3 倒计时实现

```typescript
function startTimer() {
  const startTime = Date.now()
  const updateInterval = 50

  // 更新进度条
  progressTimerId = setInterval(() => {
    const elapsed = Date.now() - startTime
    progress.value = Math.max(0, 100 - (elapsed / duration) * 100)
  }, updateInterval)

  // 自动关闭
  timerId = setTimeout(() => {
    close()
  }, duration)
}
```

### 4.4 暂停/恢复机制

```typescript
// Hover 暂停
function pauseTimer() {
  clearTimeout(timerId)
  clearInterval(progressTimerId)
}

// 离开恢复
function resumeTimer() {
  const remainingTime = (progress.value / 100) * duration
  // 使用剩余时间重新启动
  timerId = setTimeout(() => close(), remainingTime)
}
```

---

## 5. 样式设计

### 5.1 布局

```css
.toast-container {
  position: fixed;
  top: 20px;
  right: 20px;
  z-index: 9999;
  width: 100%;
  max-width: 420px;
}
```

### 5.2 通知卡片

```css
.toast-item {
  background: var(--paper);
  border-radius: 8px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12);
  overflow: hidden;
}
```

### 5.3 类型颜色

| 类型 | 图标颜色 | 进度条颜色 |
|------|----------|------------|
| Success | `var(--success)` | `var(--success)` |
| Error | `var(--danger)` | `var(--danger)` |
| Warning | `var(--warning)` | `var(--warning)` |
| Info | `var(--info)` | `var(--info)` |

### 5.4 动画

**进入动画**
```css
.toast-item {
  transform: translateY(20px);
  opacity: 0;
  transition: transform 300ms cubic-bezier(0.2, 0.8, 0.2, 1);
}

.toast-item.toast-visible {
  transform: translateY(0);
  opacity: 1;
}
```

**列表过渡**
```css
.toast-list-enter-from {
  transform: translateX(100%);
  opacity: 0;
}

.toast-list-leave-to {
  transform: translateX(100%);
  opacity: 0;
}
```

---

## 6. 已集成的功能

### 6.1 模型管理
```typescript
// 刷新成功
toast.success('模型列表刷新成功')

// 刷新失败
toast.error('模型拉取失败')
```

### 6.2 会话操作
```typescript
// 创建会话
toast.success('会话创建成功')

// 重命名
toast.success('会话重命名成功')

// 删除
toast.success('会话删除成功')
```

### 6.3 消息复制
```typescript
// 复制成功
toast.success('已复制到剪贴板')

// 复制失败
toast.error('复制失败，请重试')
```

---

## 7. 响应式设计

### 移动端适配

```css
@media (max-width: 560px) {
  .toast-container {
    top: 10px;
    right: 10px;
    left: 10px;
    max-width: none;
  }
}
```

**移动端优化：**
- 全宽显示
- 更小的间距
- 保持所有交互功能

---

## 8. 可访问性

### 8.1 ARIA 标签
```html
<button
  title="关闭"
  aria-label="关闭通知"
  @click="close"
>
```

### 8.2 键盘支持
- Tab 导航到关闭按钮
- Enter/Space 关闭通知

### 8.3 视觉反馈
- 图标提供视觉线索
- 颜色编码类型
- 进度条显示时间

---

## 9. 性能考虑

### 9.1 内存管理
- 定时器自动清理
- 组件销毁时清理资源
- 限制最大通知数量（TransitionGroup 自动处理）

### 9.2 动画性能
- 使用 `transform` 而非 `position`
- `will-change` 优化（如需要）
- GPU 加速的 CSS 动画

### 9.3 防抖/节流
当前未实现，如需要可以添加：
```typescript
// 防止短时间内重复通知
const recentMessages = new Set()

function deduplicate(message: string) {
  if (recentMessages.has(message)) return
  recentMessages.add(message)
  setTimeout(() => recentMessages.delete(message), 1000)
  // 添加通知
}
```

---

## 10. 未来扩展

### 10.1 已计划功能
- ⏳ 通知位置配置（top-left, bottom-right 等）
- ⏳ 自定义通知模板
- ⏳ 操作按钮（撤销、查看详情）
- ⏳ 通知历史记录

### 10.2 可能的改进
- ⏳ 声音提示（可选）
- ⏳ 桌面通知（Notification API）
- ⏳ 通知分组
- ⏳ 富文本内容支持

---

## 11. 使用示例

### 11.1 基础通知
```typescript
// 成功
toast.success('文件保存成功')

// 带自定义时长
toast.success('文件上传成功', { duration: 5000 })
```

### 11.2 错误处理
```typescript
try {
  await saveData()
  toast.success('保存成功')
} catch (error) {
  toast.error(error.message || '保存失败')
}
```

### 11.3 异步操作
```typescript
async function deleteItem() {
  try {
    await api.delete(id)
    toast.success('删除成功')
    await refresh()
  } catch (error) {
    toast.error('删除失败：' + error.message)
  }
}
```

---

## 12. 测试检查清单

在浏览器中测试：

- [ ] 点击"刷新模型"按钮，是否显示成功通知？
- [ ] 创建新会话，是否显示成功通知？
- [ ] 重命名会话，是否显示成功通知？
- [ ] 删除会话，是否显示成功通知？
- [ ] 复制消息，是否显示成功通知？
- [ ] 复制代码块，是否显示成功通知？
- [ ] 通知是否自动消失？
- [ ] Hover 通知是否暂停倒计时？
- [ ] 离开通知是否恢复倒计时？
- [ ] 点击关闭按钮是否立即关闭？
- [ ] 多个通知是否正确堆叠？
- [ ] 进度条是否正确显示？
- [ ] 不同类型通知颜色是否正确？

---

## 13. 故障排查

### 问题 1：通知不显示
**原因：** ToastContainer 未正确初始化
**解决：** 检查 App.vue 中的 ref 和 onMounted

### 问题 2：通知不消失
**原因：** 定时器未启动
**解决：** 检查 Toast.vue 的 onMounted

### 问题 3：多个通知重叠
**原因：** CSS z-index 或布局问题
**解决：** 检查 .toast-container 的样式

---

## 14. API 参考

### Toast 类型
```typescript
type ToastType = 'success' | 'error' | 'warning' | 'info'
```

### Toast 选项
```typescript
interface ToastOptions {
  duration?: number  // 毫秒，默认 3000
}
```

### useToast() 返回值
```typescript
{
  success(message: string, options?: ToastOptions): void
  error(message: string, options?: ToastOptions): void
  warning(message: string, options?: ToastOptions): void
  info(message: string, options?: ToastOptions): void
}
```

---

## 15. 文件清单

### 新增文件
1. `frontend/src/components/Toast.vue` - 单个通知组件
2. `frontend/src/components/ToastContainer.vue` - 容器组件
3. `frontend/src/composables/useToast.ts` - 可组合函数

### 修改文件
1. `frontend/src/App.vue` - 集成 ToastContainer
2. `frontend/src/components/ChatWorkspace.vue` - 复制通知
3. `frontend/src/composables/useChatController.ts` - 会话操作通知

---

生成时间：2025年
作者：Kiro（Claude Code）
