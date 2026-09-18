import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from EvernightAI.bootstrap.http import create_app
from EvernightAI.core.domain.tool import ToolManager, ToolRegister
from EvernightAI.core.error.base import ConflictError, ValidationError
from EvernightAI.core.error.tool import ToolPolicyError
from EvernightAI.core.schema.tool import ToolCall
from EvernightAI.infra.adapters.tool.workspace_directory import WorkspaceDirectoryStore
from EvernightAI.infra.registrations.tool.restricted_filesystem import register_restricted_filesystem_tools


def test_workspace_browse_create_and_reject_escape(tmp_path: Path) -> None:
    root = tmp_path / 'root'
    root.mkdir()
    (root / 'note.txt').write_text('hello')
    (root / 'external').symlink_to(tmp_path, target_is_directory=True)
    store = WorkspaceDirectoryStore(root)
    assert [item.name for item in store.browse('.').entries] == ['note.txt']
    created = store.create('.', '项目')
    assert created.path == '项目'
    assert created.entries == []
    assert store.browse('.').entries[0].is_directory
    for path in ['..', str(tmp_path), 'external']:
        with pytest.raises(ValidationError):
            store.browse(path)
    for name in ['../escape', '.', '', '/absolute', 'a/b']:
        with pytest.raises(ValidationError):
            store.create('.', name)
    with pytest.raises(ConflictError):
        store.create('.', '项目')


def test_workspace_http_auth_and_creation(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv('EVERNIGHTAI_HTTP_API_KEY', 'test-key')
    monkeypatch.setenv('EVERNIGHTAI_HTTP_AUTH_PERMISSIONS', 'workspaces:list')
    app = create_app(database_path=tmp_path / 'runtime.db', filesystem_root=tmp_path, close_on_shutdown=False)
    with TestClient(app) as client:
        assert client.get('/workspaces').status_code == 401
        headers = {'x-evernight-api-key': 'test-key'}
        response = client.get('/workspaces', headers=headers)
        assert response.status_code == 200
        assert response.json()['root'] == str(tmp_path)
        assert client.post('/workspaces', headers=headers, json={'name': 'denied'}).status_code == 403
        assert not (tmp_path / 'denied').exists()
    asyncio.run(app.state.interface.close())
    monkeypatch.setenv('EVERNIGHTAI_HTTP_AUTH_PERMISSIONS', 'workspaces:list,workspaces:create')
    app = create_app(database_path=tmp_path / 'runtime.db', filesystem_root=tmp_path, close_on_shutdown=False)
    with TestClient(app) as client:
        response = client.post('/workspaces', headers=headers, json={'name': 'new'})
        assert response.status_code == 201
        assert response.json()['path'] == 'new'
        assert client.get('/workspaces', params={'path': '../'}, headers=headers).status_code == 400
        assert client.post('/workspaces', headers=headers, json={'name': 'new'}).status_code == 409
    asyncio.run(app.state.interface.close())


@pytest.mark.asyncio
async def test_file_tools_bind_directory_per_call_and_reject_escape(tmp_path: Path) -> None:
    for name in ['one', 'two']:
        (tmp_path / name).mkdir()
        (tmp_path / name / 'note.txt').write_text(name)
    (tmp_path / 'note.txt').write_text('root')
    register = ToolRegister()
    register_restricted_filesystem_tools(register, root_directory=tmp_path)
    manager = ToolManager(register)
    def call(directory: str, path: str = 'note.txt') -> ToolCall:
        return ToolCall(tool_call_id=directory, tool_call={
            'name': 'read_text_file', 'arguments': {'path': path, '_working_directory': 'two'},
        }, metadata={'working_directory': directory})
    import asyncio
    first, second = await asyncio.gather(manager.execute(call('one')), manager.execute(call('two')))
    assert first.tool_call_result['content'] == 'one'
    assert second.tool_call_result['content'] == 'two'
    with pytest.raises(ToolPolicyError):
        await manager.execute(call('..'))
    from EvernightAI.core.error.tool import ToolExecutionError
    with pytest.raises(ToolExecutionError):
        await manager.execute(call('one', '../note.txt'))
    approval = manager.authorize(ToolCall(tool_call_id='write', tool_call={
        'name': 'write_text_file', 'arguments': {'path': 'new.txt', 'content': 'test'},
    }, metadata={'working_directory': 'one'}))
    assert approval.approval_request is not None
    assert approval.approval_request.metadata['working_directory'] == 'one'
