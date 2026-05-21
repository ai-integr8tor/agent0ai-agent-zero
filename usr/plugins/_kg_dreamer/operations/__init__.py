"""KG Dreamer operations module.

P1 and P2 Dream Operations for the Knowledge Graph Dreamer plugin.

- ConnectOperation: Create IMPLIED_RELATION edges between co-occurring entities
- PruneOperation: Archive cold-tier entities based on health, age, and usage
- StrengthenOperation: Boost active relationships, decay dormant ones
- ContradictionOperation: Detect conflicting properties across sources
- PatternOperation: Discover unnamed entity clusters, suggest parent concepts
- InsightOperation: Generate proactive observations from graph patterns
"""
from .connector import ConnectOperation
from .contradiction import ContradictionOperation
from .insights import InsightOperation
from .patterns import PatternOperation
from .pruner import PruneOperation
from .strengthener import StrengthenOperation

__all__ = [
    "ConnectOperation",
    "ContradictionOperation",
    "InsightOperation",
    "PatternOperation",
    "PruneOperation",
    "StrengthenOperation",
]
