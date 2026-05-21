"""KG Dreamer helpers — re-exports shared utilities from _kg_pipeline.

Works both within Agent Zero (plugins namespace) and standalone (direct imports).
"""

import sys
import os
import importlib
import logging

logger = logging.getLogger(__name__)

_pipeline_path = os.path.abspath(os.path.join(
    os.path.dirname(os.path.dirname(__file__)), '..', '_kg_pipeline'
))

if _pipeline_path not in sys.path:
    sys.path.insert(0, _pipeline_path)


def _import_class(module_name: str, class_name: str):
    """Import a class from _kg_pipeline pipeline directory."""
    # Try direct import first (standalone mode with sys.path set)
    try:
        mod = importlib.import_module(f'pipeline.{module_name}')
        return getattr(mod, class_name)
    except (ImportError, AttributeError):
        pass

    # Try Agent Zero plugin namespace
    try:
        mod = importlib.import_module(f'plugins._kg_pipeline.pipeline.{module_name}')
        return getattr(mod, class_name)
    except (ImportError, AttributeError):
        pass

    # Try with spec from file path
    try:
        file_path = os.path.join(_pipeline_path, 'pipeline', f'{module_name}.py')
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return getattr(mod, class_name)
    except Exception as e:
        logger.error(f"Failed to import {class_name} from {module_name}: {e}")
        raise


def get_kg_client(config: dict):
    """Create KGClient with correct parameters from dreamer config.
    
    KGClient(base_url: str, timeout: int = 300)
    """
    cls = _import_class('kg_client', 'KGClient')
    dreamer = config.get('dreamer', config)
    base_url = dreamer.get('kg_service_url', 'http://100.78.79.41:8010/api/v1')
    timeout = dreamer.get('kg_timeout', 60)
    return cls(base_url=base_url, timeout=timeout)


def get_audit_chain(config: dict):
    """Create AuditChain with correct parameters from dreamer config.
    
    AuditChain(audit_dir: str, enabled: bool = True)
    """
    cls = _import_class('audit_chain', 'AuditChain')
    dreamer = config.get('dreamer', config)
    audit_dir = dreamer.get('log_dir', '/a0/usr/workdir/logs/kg_dreams')
    return cls(audit_dir=audit_dir, enabled=True)


def get_health_scorer(config: dict):
    """Create HealthScorer with correct parameters from dreamer config.
    
    HealthScorer expects kg_client and config dict.
    """
    cls = _import_class('health_scorer', 'HealthScorer')
    kg_client = get_kg_client(config)
    return cls(kg_client=kg_client, config=config)


__all__ = ['get_kg_client', 'get_audit_chain', 'get_health_scorer']
