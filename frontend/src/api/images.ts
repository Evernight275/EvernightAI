import { requestJson } from './client';

export type ImageGenerationRequest = {
  model_id: string;
  prompt: string;
  count?: number;
  size?: string;
  quality?: string;
  output_format?: 'png' | 'jpeg' | 'webp';
  background?: 'auto' | 'transparent' | 'opaque';
  result_format?: 'url' | 'base64';
  timeout_seconds?: number;
};
export type GeneratedImage = {
  url?: string;
  base64_data?: string;
  mime_type?: 'image/png' | 'image/jpeg' | 'image/webp';
  revised_prompt?: string;
};
export type ImageEditInput = {
  base64_data: string;
  mime_type: 'image/png' | 'image/jpeg' | 'image/webp';
};
export type ImageMaskInput = { base64_data: string; mime_type: 'image/png' };
export type ImageEditRequest = ImageGenerationRequest & {
  images: ImageEditInput[];
  mask?: ImageMaskInput | null;
};
export type LegacyImageEditRequest = ImageGenerationRequest & { image: ImageEditInput };
export type ImageGenerationResponse = {
  model_id: string;
  images: GeneratedImage[];
  created?: number;
  usage?: { input_tokens?: number; output_tokens?: number; total_tokens?: number };
  record_id?: string;
  persistence_warning?: 'archive_incomplete' | 'save_failed' | 'record_deleted';
};
export type ImageGenerationSummary = {
  record_id: string;
  provider_id: string;
  model_id: string;
  prompt_preview: string;
  image_count: number;
  created_at: string;
  archived: boolean;
};
export type ImageGenerationRecord = {
  record_id: string;
  provider_id: string;
  request: ImageGenerationRequest | ImageEditRequest | LegacyImageEditRequest;
  response: ImageGenerationResponse;
  created_at: string;
};
export type ImageHistoryPage = { items: ImageGenerationSummary[]; next_cursor?: string };
export type ImageTaskStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'interrupted';
export type ImageTask = {
  task_id: string;
  provider_id: string;
  model_id: string;
  prompt_preview: string;
  kind: 'generate' | 'edit';
  session_id?: string;
  status: ImageTaskStatus;
  record_id?: string;
  error_type?: string;
  error_message?: string;
  created_at: string;
  updated_at: string;
};
export type ImageTaskSubmission = {
  task_id: string;
  provider_id: string;
  request: ImageGenerationRequest | ImageEditRequest;
  session_id?: string;
};
export type ImageTaskPage = { items: ImageTask[]; next_cursor?: string };

export function submitImageTask(
  submission: ImageTaskSubmission,
  signal?: AbortSignal,
): Promise<ImageTask> {
  return requestJson('/images/tasks', { method: 'POST', body: submission, signal });
}
export function getImageTask(taskId: string, signal?: AbortSignal): Promise<ImageTask> {
  return requestJson(`/images/tasks/${encodeURIComponent(taskId)}`, { signal });
}
export function listImageTasks(
  sessionId?: string,
  cursor?: string,
  signal?: AbortSignal,
): Promise<ImageTaskPage> {
  const query = new URLSearchParams({ limit: '20' });
  if (sessionId) query.set('session_id', sessionId);
  if (cursor) query.set('cursor', cursor);
  return requestJson(`/images/tasks?${query}`, { signal });
}
export function generateImages(
  providerId: string,
  request: ImageGenerationRequest,
  signal?: AbortSignal,
): Promise<ImageGenerationResponse> {
  return requestJson('/images/generations', {
    method: 'POST',
    body: { provider_id: providerId, request },
    signal,
  });
}

export function editImages(
  providerId: string,
  request: ImageEditRequest,
  signal?: AbortSignal,
): Promise<ImageGenerationResponse> {
  return requestJson('/images/edits', {
    method: 'POST',
    body: { provider_id: providerId, request },
    signal,
  });
}

export function listImageRecords(cursor?: string, signal?: AbortSignal): Promise<ImageHistoryPage> {
  const query = new URLSearchParams({ limit: '20' });
  if (cursor) query.set('cursor', cursor);
  return requestJson(`/images/records?${query}`, { signal });
}
export function getImageRecord(
  recordId: string,
  signal?: AbortSignal,
): Promise<ImageGenerationRecord> {
  return requestJson(`/images/records/${encodeURIComponent(recordId)}`, { signal });
}
export function deleteImageRecord(recordId: string, signal?: AbortSignal): Promise<void> {
  return requestJson(`/images/records/${encodeURIComponent(recordId)}`, {
    method: 'DELETE',
    signal,
  });
}
