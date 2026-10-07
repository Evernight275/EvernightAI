import { workingDirectory } from '../../runtime/workingDirectory';
import { computed, onUnmounted, ref, watch, type ComponentPublicInstance } from 'vue';
import type { ChatSubmission } from '../../domain/chat';
import type { ProviderCatalog } from '../../domain/workspace';
import { formatChatState } from './chatRequestStatus';
import {
  composeContextPreview,
  type AgentRunRequest,
  type ChatSkill,
  type Content,
  type SkillDefinition,
  type ToolDefinition,
} from '../../api';
import { parseSkillVariables } from '../../domain/skillParameters';
import { editableRunOptions } from '../../runtime/runEditor';
import { useChatAttachments } from './chatAttachments';

export type ChatRequestFormProps = {
  skills?: SkillDefinition[];
  contextId?: string | null;
  sessionId?: string | null;
  tools?: ToolDefinition[];
  catalog: ProviderCatalog;
  busy: boolean;
  sessionReady: boolean;
  state?: string;
  canStop?: boolean;
  defaultProviderId?: string | null;
  defaultModelId?: string | null;
  editRequest?: { id: string; request: AgentRunRequest } | null;
};

export type ChatRequestFormEmits = {
  submit: [submission: ChatSubmission];
  cancel: [];
};

type ChatRequestFormEmit = (event: 'submit', submission: ChatSubmission) => void;

export function useChatRequestForm(props: ChatRequestFormProps, emit: ChatRequestFormEmit) {
  const providerId = ref('');
  const modelId = ref('');
  const text = ref('');
  const selectedSkill = ref('');
  const skillVariables = ref('{}');
  const skillList = ref<string | null>(null);
  const inputJson = ref(false);
  const sourceMessage = ref<Content | null>(null);
  const sourceSkill = ref<ChatSkill | null>(null);
  const optionsJson = ref<string | null>(null);
  const draftNotice = ref('');
  const optionsError = ref('');
  const sessionKey = () => props.sessionId || props.contextId || 'new';
  const {
    attachments,
    error: attachmentError,
    uploading,
    addFiles,
    remove,
    retry,
    clear: clearAttachments,
    setArtifacts,
  } = useChatAttachments(sessionKey, () => props.busy || !props.sessionReady);
  const preview = ref('');
  const previewing = ref(false);
  let previewGeneration = 0;
  const availableSkills = computed(() =>
    (props.skills || []).filter(
      (skill) => skill.is_enabled !== false && skill.capabilities?.includes('agent'),
    ),
  );
  const currentSkill = computed(() =>
    props.skills?.find((skill) => skill.name === selectedSkill.value),
  );
  const missingSkillTools = computed(() =>
    (currentSkill.value?.required_tools || []).filter(
      (name) => !props.tools?.some((tool) => tool.name === name),
    ),
  );
  const skillUnavailable = computed(
    () =>
      !!selectedSkill.value &&
      (!availableSkills.value.some((skill) => skill.name === selectedSkill.value) ||
        missingSkillTools.value.length > 0),
  );
  watch(
    selectedSkill,
    () => {
      skillVariables.value = '{}';
      preview.value = '';
      optionsError.value = '';
    },
    { flush: 'sync' },
  );
  watch(skillVariables, () => {
    preview.value = '';
    optionsError.value = '';
  });
  watch(
    [
      selectedSkill,
      skillVariables,
      modelId,
      text,
      () => props.contextId,
      () => props.skills,
      () => props.tools,
    ],
    () => {
      previewGeneration++;
      preview.value = '';
      previewing.value = false;
    },
  );
  onUnmounted(() => previewGeneration++);
  function currentSkills() {
    if (skillList.value !== null) {
      const parsed: unknown = JSON.parse(skillList.value);
      if (
        !Array.isArray(parsed) ||
        parsed.some(
          (skill) => !skill || typeof skill !== 'object' || typeof skill.skill_name !== 'string',
        )
      )
        throw new Error('技能声明必须是包含 skill_name 的 JSON 数组');
      for (const skill of parsed) {
        const definition = availableSkills.value.find((item) => item.name === skill.skill_name);
        if (!definition) throw new Error(`技能 ${skill.skill_name} 不可用`);
        if (
          definition.required_tools?.some(
            (name) => !props.tools?.some((tool) => tool.name === name),
          )
        )
          throw new Error(`技能 ${skill.skill_name} 缺少必需工具`);
      }
      return parsed as ChatSkill[];
    }
    if (!selectedSkill.value) return undefined;
    if (skillUnavailable.value) throw new Error('当前技能不可用或缺少必需工具');
    return [
      {
        ...(sourceSkill.value?.skill_name === selectedSkill.value ? sourceSkill.value : {}),
        skill_name: selectedSkill.value,
        variables: parseSkillVariables(skillVariables.value),
      },
    ];
  }
  async function previewContext() {
    if (!props.contextId || previewing.value) return;
    const current = ++previewGeneration;
    previewing.value = true;
    optionsError.value = '';
    preview.value = '';
    try {
      const response = await composeContextPreview(props.contextId, {
        model_id: modelId.value,
        messages: currentMessages(),
        skills: currentSkills(),
        tools: props.tools,
        metadata: props.sessionId ? { session_id: props.sessionId } : {},
      });
      if (current === previewGeneration) preview.value = JSON.stringify(response, null, 2);
    } catch (cause) {
      if (current === previewGeneration)
        optionsError.value = cause instanceof Error ? cause.message : '预览失败';
    } finally {
      if (current === previewGeneration) previewing.value = false;
    }
  }
  const textarea = ref<HTMLTextAreaElement | null>(null);
  watch(
    [text, textarea],
    () => {
      if (!textarea.value) return;
      textarea.value.style.height = 'auto';
      textarea.value.style.height = `${textarea.value.scrollHeight}px`;
    },
    { flush: 'post' },
  );

  const enabledProviders = computed(() =>
    props.catalog.providers.filter((provider) => provider.is_enabled !== false),
  );
  const selectedProviderDisabled = computed(() =>
    props.catalog.providers.some(
      (provider) => provider.provider_id === providerId.value && provider.is_enabled === false,
    ),
  );
  const models = computed(
    () =>
      props.catalog.modelGroups.find((group) => group.provider.provider_id === providerId.value)
        ?.models || [],
  );
  const imageCapabilityUnsupported = computed(() => {
    if (!attachments.value.length) return false;
    const provider = props.catalog.providers.find(
      (provider) => provider.provider_id === providerId.value,
    );
    const localModel = Object.values(provider?.model || {}).find(
      (model) => model.model_id === modelId.value,
    );
    const model = localModel?.capabilities?.length
      ? localModel
      : models.value.find((item) => item.model_id === modelId.value);
    return !!model?.capabilities?.length && !model.capabilities.includes('image_recognition');
  });

  const canSubmit = computed(
    () =>
      enabledProviders.value.some((provider) => provider.provider_id === providerId.value) &&
      !skillUnavailable.value &&
      !imageCapabilityUnsupported.value &&
      !uploading.value &&
      attachments.value.every((item) => item.status === 'ready') &&
      canSubmitChat({
        busy: props.busy,
        sessionReady: props.sessionReady,
        providerId: providerId.value,
        modelId: modelId.value,
        text: text.value,
        hasAttachments:
          attachments.value.length > 0 &&
          attachments.value.every((item) => item.status === 'ready'),
      }),
  );

  watch(
    () => props.catalog.providers,
    (providers) => {
      if (!providers.some((provider) => provider.provider_id === providerId.value)) {
        providerId.value = enabledProviders.value[0]?.provider_id || '';
      }
    },
    { immediate: true },
  );

  watch(
    [providerId, models],
    ([selectedProvider, availableModels], [previousProvider, previousModels]) => {
      if (selectedProviderDisabled.value) return;
      const removedDeclaredModel =
        previousModels?.some((model) => model.model_id === modelId.value) &&
        !availableModels.some((model) => model.model_id === modelId.value);
      if (selectedProvider !== previousProvider || !modelId.value || removedDeclaredModel) {
        modelId.value = availableModels[0]?.model_id || '';
      }
    },
    { immediate: true, flush: 'sync' },
  );

  let appliedDefaults = '';
  watch(
    [
      () => props.defaultProviderId,
      () => props.defaultModelId,
      () => props.sessionId,
      () => props.catalog.providers,
    ],
    ([defaultProviderId, defaultModelId, sessionId]) => {
      if (!defaultProviderId) {
        appliedDefaults = '';
        return;
      }
      if (!props.catalog.providers.some((provider) => provider.provider_id === defaultProviderId)) {
        return;
      }
      const defaults = JSON.stringify([sessionId, defaultProviderId, defaultModelId]);
      if (appliedDefaults === defaults) return;
      appliedDefaults = defaults;
      providerId.value = defaultProviderId;
      modelId.value = defaultModelId?.trim() || models.value[0]?.model_id || '';
    },
    { immediate: true, flush: 'sync' },
  );

  function submit(): void {
    if (!canSubmit.value) {
      return;
    }

    optionsError.value = '';
    let skills, messages, runOptions;
    const imageParts = attachments.value
      .filter((item) => item.status === 'ready')
      .map(({ artifact }) => ({
        type: 'image',
        artifact_id: artifact.artifact_id,
        mime_type: artifact.mime_type,
        metadata: { filename: artifact.name },
      }));
    try {
      skills = currentSkills();
      messages = currentMessages();
      if (imageParts.length) {
        if (!inputJson.value && messages.length === 1 && messages[0]?.role === 'user') {
          const existingIds = new Set((messages[0].content || []).map((part) => part.artifact_id));
          messages[0] = {
            ...messages[0],
            content: [
              ...(messages[0].content || []),
              ...imageParts.filter((part) => !existingIds.has(part.artifact_id)),
            ],
          };
        } else {
          messages.push({ role: 'user', content: imageParts });
        }
      }
      if (optionsJson.value !== null) {
        const options: unknown = JSON.parse(optionsJson.value);
        if (
          !options ||
          typeof options !== 'object' ||
          Array.isArray(options) ||
          Object.keys(options).some(
            (key) =>
              ![
                'tools',
                'memory_query',
                'max_tool_rounds',
                'recover_tool_errors',
                'write_memory',
                'metadata',
              ].includes(key),
          )
        )
          throw new Error('运行参数包含不支持的字段');
        runOptions = editableRunOptions(options as AgentRunRequest);
      }
    } catch (cause) {
      optionsError.value = cause instanceof Error ? cause.message : '请求参数无效';
      return;
    }
    emit('submit', {
      workingDirectory: workingDirectory.value,
      providerId: providerId.value,
      modelId: modelId.value.trim(),
      text: text.value.trim(),
      ...(skills ? { skills } : {}),
      ...(inputJson.value || sourceMessage.value || imageParts.length ? { messages } : {}),
      ...(runOptions ? { runOptions } : {}),
    });
    text.value = '';
    clearAttachments();
  }

  function currentMessages(): Content[] {
    if (inputJson.value) {
      const value: unknown = JSON.parse(text.value);
      if (
        !Array.isArray(value) ||
        !value.length ||
        value.some((item) => !item || typeof item !== 'object' || typeof item.role !== 'string')
      )
        throw new Error('输入消息必须是包含 role 的 JSON 数组');
      return value as Content[];
    }
    const retainedImageIds = new Set(attachments.value.map((item) => item.artifact.artifact_id));
    return [
      {
        ...(sourceMessage.value || {}),
        role: 'user',
        content: replaceTextPart(
          (sourceMessage.value?.content || []).filter(
            (part) => !part.artifact_id || retainedImageIds.has(part.artifact_id),
          ),
          text.value.trim(),
        ),
      },
    ];
  }

  const draftKey = () => `evernight.chatDraft.${sessionKey()}`;
  watch(
    () => props.sessionId || props.contextId || 'new',
    () => {
      if (typeof sessionStorage === 'undefined') return;
      try {
        const saved = JSON.parse(sessionStorage.getItem(draftKey()) || 'null');
        if (
          !saved ||
          typeof saved.text !== 'string' ||
          typeof saved.providerId !== 'string' ||
          typeof saved.modelId !== 'string'
        ) {
          text.value = '';
          selectedSkill.value = '';
          skillVariables.value = '{}';
          skillList.value = null;
          inputJson.value = false;
          sourceMessage.value = null;
          sourceSkill.value = null;
          optionsJson.value = null;
          draftNotice.value = '';
          return;
        }
        providerId.value = saved.providerId;
        modelId.value = saved.modelId;
        text.value = saved.text;
        selectedSkill.value = typeof saved.selectedSkill === 'string' ? saved.selectedSkill : '';
        skillVariables.value =
          typeof saved.skillVariables === 'string' ? saved.skillVariables : '{}';
        skillList.value = typeof saved.skillList === 'string' ? saved.skillList : null;
        inputJson.value = saved.inputJson === true;
        sourceMessage.value = saved.sourceMessage || null;
        sourceSkill.value = saved.sourceSkill || null;
        optionsJson.value = typeof saved.optionsJson === 'string' ? saved.optionsJson : null;
        workingDirectory.value =
          typeof saved.workingDirectory === 'string' ? saved.workingDirectory : undefined;
      } catch {
        /* Keep the current draft if browser storage is unavailable. */
      }
    },
    { immediate: true, flush: 'post' },
  );
  watch(
    [
      providerId,
      modelId,
      text,
      selectedSkill,
      skillVariables,
      skillList,
      inputJson,
      sourceMessage,
      sourceSkill,
      optionsJson,
      workingDirectory,
      attachments,
    ],
    () => {
      if (typeof sessionStorage === 'undefined') return;
      try {
        sessionStorage.setItem(
          draftKey(),
          JSON.stringify({
            providerId: providerId.value,
            modelId: modelId.value,
            text: text.value,
            selectedSkill: selectedSkill.value,
            skillVariables: skillVariables.value,
            skillList: skillList.value,
            inputJson: inputJson.value,
            sourceMessage: sourceMessage.value,
            sourceSkill: sourceSkill.value,
            optionsJson: optionsJson.value,
            workingDirectory: workingDirectory.value,
            attachments: attachments.value
              .filter((item) => !item.artifact.artifact_id.startsWith('uploading-'))
              .map(({ artifact }) => artifact),
          }),
        );
      } catch {
        /* Editing does not depend on storage. */
      }
    },
    { flush: 'post', deep: true },
  );
  watch(
    () => props.editRequest,
    (draft) => {
      if (!draft) return;
      const request = draft.request;
      const first = request.messages?.[0];
      inputJson.value = !(
        request.messages?.length === 1 &&
        first?.role === 'user' &&
        !first.tool_calls?.length &&
        (first.content || []).filter((part) => part.type === 'text').length <= 1 &&
        (first.content || []).every(
          (part) => part.type === 'text' || (part.type === 'image' && !!part.artifact_id),
        )
      );
      const existingImages = !inputJson.value
        ? (first?.content || []).filter(
            (part) => part.type === 'image' && typeof part.artifact_id === 'string',
          )
        : [];
      sourceMessage.value = inputJson.value ? null : JSON.parse(JSON.stringify(first || null));
      void setArtifacts(
        existingImages.map((part) => ({
          artifact_id: part.artifact_id!,
          name: String(part.metadata?.filename || part.metadata?.name || 'image'),
          title: null,
          mime_type: part.mime_type || 'image/png',
          size_bytes: 0,
          preview_kind: 'image' as const,
          created_at: '',
        })),
      );
      text.value = inputJson.value
        ? JSON.stringify(request.messages || [], null, 2)
        : first?.content?.find((part) => part.type === 'text')?.text || '';
      providerId.value = request.provider_id;
      modelId.value = request.model_id;
      sourceSkill.value = JSON.parse(JSON.stringify(request.skills?.[0] || null));
      skillList.value =
        (request.skills?.length || 0) > 1 ? JSON.stringify(request.skills, null, 2) : null;
      selectedSkill.value = skillList.value === null ? sourceSkill.value?.skill_name || '' : '';
      skillVariables.value = JSON.stringify(sourceSkill.value?.variables || {}, null, 2);
      optionsJson.value = JSON.stringify(editableRunOptions(request), null, 2);
      workingDirectory.value = request.working_directory || undefined;
      optionsError.value = '';
      draftNotice.value = '原请求已载入草稿';
      textarea.value?.focus();
    },
    { flush: 'post' },
  );

  function handleMessageKeydown(event: KeyboardEvent): void {
    if (!shouldSubmitChatKeydown(event)) {
      return;
    }
    event.preventDefault();
    submit();
  }

  function handleFileChange(event: Event): void {
    const input = event.target as HTMLInputElement;
    void addFiles(input.files || []);
    input.value = '';
  }

  return {
    skillList,
    inputJson,
    optionsJson,
    draftNotice,
    availableSkills,
    currentSkill,
    missingSkillTools,
    skillUnavailable,
    selectedSkill,
    skillVariables,
    optionsError,
    attachmentError,
    attachments,
    uploading,
    addFiles,
    remove,
    retry,
    handleFileChange,
    imageCapabilityUnsupported,
    preview,
    previewing,
    previewContext,
    setTextarea(element: Element | ComponentPublicInstance | null): void {
      textarea.value = element as HTMLTextAreaElement | null;
    },
    providerId,
    modelId,
    models,
    text,
    canSubmit,
    selectedProviderDisabled,
    providerDisabled: computed(
      () => props.busy || !props.sessionReady || enabledProviders.value.length === 0,
    ),
    modelDisabled: computed(
      () =>
        props.busy || !props.sessionReady || providerId.value === '' || models.value.length === 0,
    ),
    messageDisabled: computed(() => props.busy || !props.sessionReady),
    submitLabel: computed(() =>
      !props.sessionReady
        ? '请先选择会话'
        : props.busy
          ? formatChatState(props.state || 'streaming')
          : '发送',
    ),
    handleMessageKeydown,
    submit,
  };
}

export function shouldSubmitChatKeydown(
  event: Pick<KeyboardEvent, 'key' | 'shiftKey' | 'isComposing'>,
): boolean {
  return event.key === 'Enter' && !event.shiftKey && !event.isComposing;
}

export function canSubmitChat(values: {
  busy: boolean;
  sessionReady?: boolean;
  providerId: string;
  modelId: string;
  text: string;
  hasAttachments?: boolean;
}): boolean {
  return (
    !values.busy &&
    values.sessionReady !== false &&
    values.providerId !== '' &&
    values.modelId.trim() !== '' &&
    (values.text.trim() !== '' || values.hasAttachments === true)
  );
}

function replaceTextPart(parts: NonNullable<Content['content']>, text: string) {
  let replaced = false;
  const next = parts.map((part) => {
    if (part.type !== 'text' || replaced) return part;
    replaced = true;
    return { ...part, text };
  });
  return replaced || !text ? next : [...next, { type: 'text', text }];
}
