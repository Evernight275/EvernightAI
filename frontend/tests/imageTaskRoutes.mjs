// Adapt existing provider mocks to the durable task API while preserving their assertions.
export function imageTaskRoutes(handler) {
  const tasks = new Map();
  const records = new Map();
  return async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname.replace('/mock-api', '');
    const owner = request.headers()['x-evernight-api-key'] || 'anonymous';
    if (path === '/images/tasks' && request.method() === 'POST') {
      const body = request.postDataJSON();
      const existing = tasks.get(body.task_id);
      if (existing) return route.fulfill({ status: 202, json: existing.summary });
      const task = {
        owner,
        summary: {
          task_id: body.task_id,
          provider_id: body.provider_id,
          model_id: body.request.model_id,
          prompt_preview: body.request.prompt,
          kind: body.request.images ? 'edit' : 'generate',
          session_id: body.session_id,
          status: 'running',
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        },
      };
      tasks.set(body.task_id, task);
      const virtual = {
        request: () => ({
          url: () =>
            request
              .url()
              .replace(
                '/images/tasks',
                body.request.images ? '/images/edits' : '/images/generations',
              ),
          method: () => 'POST',
          headers: () => request.headers(),
          postDataJSON: () => ({ provider_id: body.provider_id, request: body.request }),
        }),
        fulfill: async ({ status = 200, json }) => {
          if (status >= 400 || json.persistence_warning === 'save_failed') {
            task.summary.status = 'failed';
            task.summary.error_message = json.error?.message || '图片保存失败，请检查历史记录。';
          } else {
            const recordId = json.record_id || body.task_id;
            records.set(recordId, {
              record_id: recordId,
              provider_id: body.provider_id,
              request: body.request,
              response: { ...json, record_id: recordId },
              created_at: task.summary.created_at,
            });
            task.summary.status = 'succeeded';
            task.summary.record_id = recordId;
          }
        },
      };
      void handler(virtual);
      return route.fulfill({ status: 202, json: task.summary });
    }
    if (path === '/images/tasks') {
      const session = url.searchParams.get('session_id');
      return route.fulfill({
        json: {
          items: [...tasks.values()]
            .filter(
              (task) => task.owner === owner && (!session || task.summary.session_id === session),
            )
            .reverse()
            .map((task) => task.summary),
        },
      });
    }
    if (path.startsWith('/images/tasks/')) {
      const task = tasks.get(path.split('/').at(-1));
      return route.fulfill(
        task?.owner === owner
          ? { json: task.summary }
          : { status: 404, json: { error: { message: 'Task not found' } } },
      );
    }
    if (path.startsWith('/images/records/')) {
      const id = path.split('/').at(-1);
      if (request.method() === 'GET' && records.has(id))
        return route.fulfill({ json: records.get(id) });
      if (request.method() === 'DELETE') {
        return handler({
          request: () => request,
          fulfill: async (options) => {
            if (options.status === 204) {
              records.delete(id);
              for (const [taskId, task] of tasks)
                if (task.summary.record_id === id) tasks.delete(taskId);
            }
            return route.fulfill(options);
          },
        });
      }
    }
    return handler(route);
  };
}
