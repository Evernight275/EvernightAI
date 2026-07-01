# 聊天功能增强文档

## 升级时间
2025年（frontend-ui 分支）

## 升级目标
提升聊天体验，增加实用功能和更好的视觉反馈

---

## 1. 代码块复制功能

### 实现方式
动态插入复制按钮到每个代码块：

```typescript
function addCodeCopyButtons() {
  // 查找所有代码块
  const codeBlocks = thread.querySelectorAll('pre.hljs')
  
  // 为每个代码块添加复制按钮
  codeBlocks.forEach((block, index) => {
    const button = document.createElement('button')
    button.className = 'code-copy-button'
    // ... 添加点击事件和图标
    block.appendChild(button)
  })
}
```

### 交互特点
- **隐藏显示**：默认隐藏，hover 代码块时显示
- **复制反馈**：点击后图标变为对勾，背景变为成功色
- **自动恢复**：2秒后自动恢复为复制图标
- **位置固定**：绝对定位在右上角，不影响代码布局

### 样式细节
```css
.code-copy-button {
  position: absolute;
  top: 8px;
  right: 8px;
  opacity: 0;  /* 默认隐藏 */
}

pre:hover .code-copy-button {
  opacity: 1;  /* hover 时显示 */
}

.code-copy-button.copied {
  color: var(--success);
  background: var(--success-light);
}
```

---

## 2. 消息操作增强

### 新增功能

#### 2.1 复制消息
- **所有消息可复制**：用户消息和助手消息都可以一键复制
- **视觉反馈**：复制后图标变为对勾，2秒后恢复
- **快速访问**：hover 消息时显示操作按钮

#### 2.2 重试助手回复
- **保留原功能**：助手消息可以重试
- **更明显**：操作按钮始终在同一位置
- **禁用状态**：发送中或无上下文索引时禁用

### 操作栏布局
```html
<div class="message-actions">
  <!-- 重试按钮（仅助手消息） -->
  <button v-if="message.role === 'assistant'">
    <Icon name="rotate-ccw" />
  </button>
  
  <!-- 复制按钮（所有消息） -->
  <button>
    <Icon :name="copied ? 'check' : 'copy'" />
  </button>
</div>
```

### 状态管理
```typescript
const copiedMessageIndex = ref<number | null>(null)

function copyMessage(message, index) {
  navigator.clipboard.writeText(message.text)
  copiedMessageIndex.value = index
  setTimeout(() => {
    copiedMessageIndex.value = null
  }, 2000)
}
```

---

## 3. 视觉改进

### 3.1 消息类型区分

**用户消息：**
```css
.chat-thread-message.user {
  background: var(--soft);       /* 浅灰背景 */
  border: 1px solid var(--line-soft);
}
```

**助手消息：**
```css
.chat-thread-message.assistant {
  background: var(--paper);      /* 白色背景 */
  border: 1px solid var(--line-soft);
}
```

**待处理消息：**
```css
.chat-thread-message.pending {
  border: 1px dashed var(--primary);  /* 蓝色虚线 */
  background: var(--primary-light);    /* 浅蓝背景 */
}
```

### 3.2 操作按钮视觉

**改动前：**
- Hover 变为黑色文字，灰色背景

**改动后：**
- Hover 变为主题色文字，浅蓝背景
- 更柔和的过渡效果

```css
.message-action-button:hover {
  color: var(--primary);
  background: var(--primary-light);
}
```

### 3.3 加载状态

**待处理消息的脉动效果：**
- 使用主题色的点
- 更快的动画（1.2s）
- 虚线边框 + 浅色背景

---

## 4. 响应式优化

### 移动端改进

**小屏幕（≤860px）：**
```css
@media (max-width: 860px) {
  /* 消息操作始终可见 */
  .message-actions {
    opacity: 1;
  }
}
```

**原因：**
- 移动端没有 hover 状态
- 确保用户能随时访问复制和重试功能

---

## 5. 用户体验提升

### 5.1 复制体验

| 操作 | 反馈 |
|------|------|
| 复制代码块 | 按钮图标变对勾，背景变绿 |
| 复制消息 | 图标变对勾 |
| 复制成功 | 2秒后自动恢复 |
| 复制失败 | 控制台错误日志 |

### 5.2 视觉反馈层次

**状态层级：**
1. **默认**：灰色，透明背景
2. **Hover**：主题色，浅色背景
3. **活动**：成功色，成功背景（复制成功）
4. **禁用**：低透明度，不可点击

### 5.3 一致性

所有按钮遵循相同的设计语言：
- 28px × 28px 尺寸
- 6px 圆角
- 主题色 hover 状态
- 140-160ms 过渡动画

---

## 6. 实现细节

### 6.1 代码块检测
使用 Vue 的 `watch` 和生命周期：

```typescript
watch(
  () => props.messages,
  () => {
    addCodeCopyButtons()  // 消息更新后添加按钮
  },
  { flush: 'post' }
)

onMounted(() => {
  addCodeCopyButtons()  // 初始化时添加
})
```

### 6.2 DOM 操作
直接操作 DOM 插入按钮：
- 检查是否已存在按钮（避免重复）
- 使用内联 SVG 图标
- 添加事件监听器

### 6.3 Clipboard API
```typescript
navigator.clipboard.writeText(text)
  .then(() => {
    // 成功反馈
  })
  .catch((error) => {
    console.error('复制失败:', error)
  })
```

---

## 7. 可访问性

### 7.1 ARIA 标签
```html
<button
  title="复制消息"
  aria-label="复制消息"
>
```

### 7.2 键盘导航
- 所有按钮可通过 Tab 访问
- 焦点样式清晰可见

### 7.3 状态反馈
- 视觉反馈（图标变化）
- 语义化的 title 属性

---

## 8. 性能考虑

### 8.1 防重复
```typescript
const existingButton = block.querySelector('.code-copy-button')
if (existingButton) return  // 避免重复添加
```

### 8.2 事件委托
每个按钮独立事件监听器，简单直接

### 8.3 定时器清理
使用 `setTimeout` 自动恢复状态，无需手动清理

---

## 9. 浏览器兼容性

### Clipboard API
- ✅ Chrome 66+
- ✅ Firefox 63+
- ✅ Safari 13.1+
- ✅ Edge 79+

**降级方案：**
如果不支持，控制台会显示错误，但不会崩溃

---

## 10. 改动文件

### 修改的文件
1. `frontend/src/components/ChatWorkspace.vue`
   - 添加复制相关函数
   - 更新消息模板
   - 添加状态管理

2. `frontend/src/style.css`
   - 代码复制按钮样式
   - 消息操作按钮改进
   - 消息类型视觉区分
   - 移动端优化

---

## 11. 功能对比

| 功能 | 改动前 | 改动后 |
|------|--------|--------|
| 复制代码 | ❌ 无 | ✅ hover 显示按钮 |
| 复制消息 | ❌ 无 | ✅ 所有消息可复制 |
| 重试消息 | ✅ 隐藏在 hover 里 | ✅ 操作栏更明显 |
| 视觉区分 | ⚠️ 仅背景色 | ✅ 背景 + 边框 |
| 待处理状态 | ⚠️ 虚线边框 | ✅ 主题色 + 浅色背景 |
| 移动端操作 | ❌ hover 无法访问 | ✅ 始终显示 |

---

## 12. 测试检查清单

启动前端后检查：

- [ ] 代码块 hover 时显示复制按钮
- [ ] 点击复制按钮，图标变为对勾
- [ ] 复制成功后代码在剪贴板中
- [ ] 2秒后复制按钮恢复原状
- [ ] 消息 hover 时显示操作按钮
- [ ] 点击复制消息，图标变为对勾
- [ ] 助手消息显示重试按钮
- [ ] 用户消息和助手消息有明显视觉区分
- [ ] 待处理消息显示蓝色虚线边框
- [ ] 移动端（窄屏）操作按钮始终可见

---

## 13. 后续优化建议

### 短期（已完成 ✅）
- ✅ 代码块复制
- ✅ 消息复制
- ✅ 视觉区分
- ✅ 移动端优化

### 中期（待实施）
- ⏳ 编辑已发送消息
- ⏳ 删除消息
- ⏳ 消息搜索
- ⏳ 导出对话
- ⏳ 消息时间戳

### 长期（待规划）
- ⏳ 消息引用/回复
- ⏳ 消息反馈（点赞/点踩）
- ⏳ 代码语法高亮主题切换
- ⏳ 消息分组（按日期）

---

## 14. 设计原则

本次增强遵循的原则：

1. **实用性优先**：添加用户最需要的功能
2. **视觉一致性**：所有操作使用相同的设计语言
3. **渐进增强**：不影响现有功能
4. **可访问性**：键盘导航和屏幕阅读器友好
5. **性能优先**：DOM 操作优化，避免重复

---

## 15. 用户反馈点

可以向用户询问的问题：

1. 复制功能是否足够明显？
2. 是否需要复制为纯文本/Markdown 的选项？
3. 是否需要编辑消息的功能？
4. 移动端按钮大小是否合适？
5. 是否需要键盘快捷键（如 Cmd+C 复制选中消息）？

---

生成时间：2025年
作者：Kiro（Claude Code）
