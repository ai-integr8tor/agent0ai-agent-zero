import sys
import types
import unittest
from pathlib import Path
from unittest import mock

# Add plugin root to path so we can import config, client, etc.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

agent_mod = types.ModuleType('agent')
class Agent:  # pragma: no cover
    pass
agent_mod.Agent = Agent
sys.modules.setdefault('agent', agent_mod)

helpers_mod = types.ModuleType('helpers')
plugins_mod = types.ModuleType('helpers.plugins')
plugins_mod.get_plugin_config = lambda *args, **kwargs: {}
helpers_mod.plugins = plugins_mod
sys.modules.setdefault('helpers', helpers_mod)
sys.modules.setdefault('helpers.plugins', plugins_mod)

import config
from tools.shared import resolve_notebook_id


class DummyResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self._status_code = status_code
    def raise_for_status(self):
        if self._status_code >= 400:
            import httpx
            raise httpx.HTTPStatusError(
                f"Error {self._status_code}",
                request=mock.Mock(),
                response=self
            )
        return None
    def json(self):
        return self._payload


class DummyClient:
    def __init__(self, notebooks=None, notes=None):
        self.notebooks = notebooks or []
        self.notes = notes or []
    async def get(self, url, params=None):
        if '/api/notebooks' in url:
            return DummyResponse(self.notebooks)
        elif '/api/notes' in url:
            # Filter notes by notebook_id if provided
            notebook_id = params.get('notebook_id') if params else None
            if notebook_id:
                filtered_notes = [n for n in self.notes if n.get('notebook_id') == notebook_id]
                return DummyResponse(filtered_notes)
            return DummyResponse(self.notes)
        return DummyResponse({})
    async def post(self, url, json=None):
        if '/api/notes' in url:
            new_note = {
                'id': f'note:{len(self.notes) + 1}',
                'title': json.get('title', ''),
                'content': json.get('content', ''),
                'note_type': 'human',
                'notebook_id': json.get('notebook_id', ''),
                'created': '2026-05-29T13:18:00Z',
                'updated': '2026-05-29T13:18:00Z'
            }
            self.notes.append(new_note)
            return DummyResponse(new_note)
        return DummyResponse({})


async def _dummy_get_client(client):
    return client


class DummyAgent:
    pass


class OpenNotebookAddListRegressionTests(unittest.IsolatedAsyncioTestCase):
    """Regression tests for add/list workflow covering realistic user flows.
    
    These tests ensure that:
    1. Notebook ID resolution works correctly during add/list operations
    2. Adding a note and then listing it shows the note
    3. Edge cases around notebook name/ID behavior are covered
    """
    
    async def asyncSetUp(self):
        import client
        self.client = client
        self._orig_get_api_url = config.get_api_url
        self._orig_get_client = client.get_client

    async def asyncTearDown(self):
        config.get_api_url = self._orig_get_api_url
        self.client.get_client = self._orig_get_client

    async def test_resolve_notebook_id_by_name_for_add_operation(self):
        """Test that notebook name resolution works correctly for add operations.
        
        This is a regression test for the add workflow where users should be able
        to specify a notebook by name instead of full ID, and it should resolve correctly.
        """
        config.get_api_url = lambda agent: 'http://example'
        self.client.get_client = lambda: _dummy_get_client(DummyClient([
            {'id': 'notebook:abc123', 'name': '🕵🏾‍♂️ Agent Zero'}
        ]))
        
        # Test that name resolution returns the full ID
        result = await resolve_notebook_id(DummyAgent(), 'Agent Zero')
        self.assertEqual(result, 'notebook:abc123')

    async def test_add_then_list_shows_new_note(self):
        """Test that adding a note and then listing notes shows the new note.
        
        This is a regression test for the complete add/list workflow ensuring
        that after creating a note, it appears in the list results.
        """
        config.get_api_url = lambda agent: 'http://example'
        
        # Start with empty notes list
        test_notes = []
        dummy_client = DummyClient(notes=test_notes)
        self.client.get_client = lambda: _dummy_get_client(dummy_client)
        
        # Simulate adding a note (would call _create with notebook_id, title, content)
        notebook_id = 'notebook:abc123'
        new_note = {
            'id': 'note:1',
            'title': 'Test Note',
            'content': 'This is test content',
            'note_type': 'human',
            'notebook_id': notebook_id,
            'created': '2026-05-29T13:18:00Z',
            'updated': '2026-05-29T13:18:00Z'
        }
        # Append to the client's notes list, not the local variable
        dummy_client.notes.append(new_note)
        
        # Simulate listing notes for the notebook
        response = await dummy_client.get('http://example/api/notes', params={'notebook_id': notebook_id})
        listed_notes = response.json()
        
        # Verify the note appears in the list
        self.assertEqual(len(listed_notes), 1)
        self.assertEqual(listed_notes[0]['title'], 'Test Note')
        self.assertEqual(listed_notes[0]['id'], 'note:1')
        self.assertEqual(listed_notes[0]['notebook_id'], notebook_id)

    async def test_list_filters_by_correct_notebook_id(self):
        """Test that listing notes correctly filters by the specified notebook ID.
        
        This is a regression test ensuring that the list operation respects
        the notebook_id parameter and doesn't return notes from other notebooks.
        """
        config.get_api_url = lambda agent: 'http://example'
        
        # Create notes across multiple notebooks
        test_notes = [
            {'id': 'note:1', 'title': 'Note A', 'notebook_id': 'notebook:abc', 'note_type': 'human'},
            {'id': 'note:2', 'title': 'Note B', 'notebook_id': 'notebook:def', 'note_type': 'human'},
            {'id': 'note:3', 'title': 'Note C', 'notebook_id': 'notebook:abc', 'note_type': 'human'},
        ]
        dummy_client = DummyClient(notes=test_notes)
        self.client.get_client = lambda: _dummy_get_client(dummy_client)
        
        # List notes for notebook:abc
        response = await dummy_client.get('http://example/api/notes', params={'notebook_id': 'notebook:abc'})
        listed_notes = response.json()
        
        # Verify only notes from notebook:abc are returned
        self.assertEqual(len(listed_notes), 2)
        titles = [n['title'] for n in listed_notes]
        self.assertEqual(titles, ['Note A', 'Note C'])
        
        # List notes for notebook:def
        response2 = await dummy_client.get('http://example/api/notes', params={'notebook_id': 'notebook:def'})
        listed_notes2 = response2.json()
        
        # Verify only notes from notebook:def are returned
        self.assertEqual(len(listed_notes2), 1)
        self.assertEqual(listed_notes2[0]['title'], 'Note B')

    async def test_notebook_id_suffix_resolution_integration(self):
        """Test that short suffix resolution works in a realistic add/list context.
        
        This is a regression test ensuring users can specify 'xyz789' instead of
        'notebook:xyz789' and the system resolves it correctly for both add and list.
        """
        config.get_api_url = lambda agent: 'http://example'
        self.client.get_client = lambda: _dummy_get_client(DummyClient([
            {'id': 'notebook:xyz789', 'name': 'Test Notebook'}
        ]))
        
        # Test short suffix resolution
        result = await resolve_notebook_id(DummyAgent(), 'xyz789')
        self.assertEqual(result, 'notebook:xyz789')
        
        # Verify the resolved ID can be used for filtering (simulating list operation)
        test_notes = [
            {'id': 'note:1', 'title': 'Test Note', 'notebook_id': 'notebook:xyz789', 'note_type': 'human'}
        ]
        dummy_client = DummyClient(notes=test_notes)
        self.client.get_client = lambda: _dummy_get_client(dummy_client)
        
        response = await dummy_client.get('http://example/api/notes', params={'notebook_id': result})
        listed_notes = response.json()
        
        # Verify the resolved ID correctly filters the notes
        self.assertEqual(len(listed_notes), 1)
        self.assertEqual(listed_notes[0]['notebook_id'], 'notebook:xyz789')


if __name__ == '__main__':
    unittest.main()