from helpers.extension import Extension
from helpers.print_style import PrintStyle


class InvalidateEmbeddingCaches(Extension):
    def execute(self, **kwargs):
        # Clear VectorDB embedding cache
        from helpers.vector_db import VectorDB
        count = len(VectorDB._cached_embeddings)
        VectorDB._cached_embeddings.clear()

        # Clear Memory index cache so VectorDBs are re-initialized with new embeddings
        try:
            from plugins._memory.helpers.memory import Memory
            mem_count = len(Memory.index)
            Memory.index.clear()
        except ImportError:
            mem_count = 0

        PrintStyle().print(
            f"Embedding model changed: cleared {count} cached embedding(s) "
            f"and {mem_count} memory index(es)."
        )
