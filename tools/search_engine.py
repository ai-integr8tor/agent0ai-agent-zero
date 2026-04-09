import os
import asyncio
from helpers import dotenv, perplexity_search, duckduckgo_search
from helpers.tool import Tool, Response
from helpers.print_style import PrintStyle
from helpers.errors import handle_error
from helpers.searxng import search as searxng
from helpers import exa_search

SEARCH_ENGINE_RESULTS = 10


class SearchEngine(Tool):
    async def execute(self, query="", **kwargs):

        if exa_search.is_available():
            result = await self.exa_search(query)
        else:
            result = await self.searxng_search(query)

        await self.agent.handle_intervention(
            result
        )  # wait for intervention and handle it, if paused

        return Response(message=result, break_loop=False)

    async def exa_search(self, question):
        try:
            results = await exa_search.search(question)
            return self.format_results(results, "Exa Search")
        except Exception as e:
            handle_error(e)
            # fall back to SearXNG on Exa failure
            return await self.searxng_search(question)

    async def searxng_search(self, question):
        results = await searxng(question)
        return self.format_result_searxng(results, "Search Engine")

    def format_results(self, results, source):
        if isinstance(results, Exception):
            handle_error(results)
            return f"{source} search failed: {str(results)}"

        outputs = []
        for item in (results or []):
            outputs.append(f"{item['title']}\n{item['url']}\n{item['content']}")

        return "\n\n".join(outputs[:SEARCH_ENGINE_RESULTS]).strip()

    def format_result_searxng(self, result, source):
        if isinstance(result, Exception):
            handle_error(result)
            return f"{source} search failed: {str(result)}"

        outputs = []
        for item in (result or {}).get("results", []):
            outputs.append(f"{item['title']}\n{item['url']}\n{item['content']}")

        return "\n\n".join(outputs[:SEARCH_ENGINE_RESULTS]).strip()
