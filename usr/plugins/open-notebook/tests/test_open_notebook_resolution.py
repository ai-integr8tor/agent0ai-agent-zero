import sys
import types
import unittest
from unittest import mock

# Provide minimal stubs so importing plugin helpers works without the full A0 runtime.
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
    def __init__(self, payload):
        self._payload = payload
    def raise_for_status(self):
        return None
    def json(self):
        return self._payload


class DummyClient:
    def __init__(self, notebooks):
        self.notebooks = notebooks
    async def get(self, url):
        return DummyResponse(self.notebooks)


async def _dummy_get_client(notebooks):
    return DummyClient(notebooks)


class DummyAgent:
    pass


class ResolveNotebookIdTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import client
        self._orig_get_api_url = config.get_api_url
        self._orig_get_client = client.get_client
        self.client = client

    async def asyncTearDown(self):
        config.get_api_url = self._orig_get_api_url
        self.client.get_client = self._orig_get_client

    async def test_resolve_notebook_id_by_name(self):
        config.get_api_url = lambda agent: 'http://example'
        self.client.get_client = lambda: _dummy_get_client([{'id': 'notebook:abc123', 'name': '🕵🏾‍♂️ Agent Zero'}])
        result = await resolve_notebook_id(DummyAgent(), 'Agent Zero')
        self.assertEqual(result, 'notebook:abc123')

    async def test_resolve_notebook_id_by_full_id(self):
        result = await resolve_notebook_id(DummyAgent(), 'notebook:abc123')
        self.assertEqual(result, 'notebook:abc123')


if __name__ == '__main__':
    unittest.main()
