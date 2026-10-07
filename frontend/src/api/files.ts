import { requestBlob, requestJson } from './client';

export type FileArtifactInfo = {
  artifact_id: string;
  name: string;
  title: string | null;
  mime_type: string;
  size_bytes: number;
  preview_kind: 'image' | 'html' | 'none';
  created_at: string;
};

export function uploadFileArtifact(
  file: Blob,
  filename: string,
  signal?: AbortSignal,
): Promise<FileArtifactInfo> {
  return requestJson<FileArtifactInfo>(`/files/upload?filename=${encodeURIComponent(filename)}`, {
    method: 'POST',
    body: file,
    contentType: file.type,
    signal,
  });
}

export function getFileArtifact(
  artifactId: string,
  signal?: AbortSignal,
): Promise<FileArtifactInfo> {
  return requestJson(`/files/${encodeURIComponent(artifactId)}`, { signal });
}

export function readFileArtifact(
  artifactId: string,
  signal?: AbortSignal,
  download = false,
): Promise<Blob> {
  return requestBlob(
    `/files/${encodeURIComponent(artifactId)}/content${download ? '?download=true' : ''}`,
    { signal },
  );
}
