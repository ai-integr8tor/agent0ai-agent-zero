"""Google Drive upload helper for KG exports."""
import os
import sys
import json
import logging
from typing import Dict, Any

from .kg_client import KGClient

logger = logging.getLogger(__name__)


class KGDriveUploader:
    """Uploads KG exports to Google Drive."""

    def __init__(self, kg_client: KGClient, config: Dict[str, Any]):
        self.kg = kg_client
        self.config = config
        self.gw_path = "/a0/usr/google-workspace"

    def upload_export(self, filepath: str = "") -> Dict[str, Any]:
        """Upload a KG export file to Google Drive."""
        if not filepath:
            filepath = self._export_kg()
        if not filepath or not os.path.exists(filepath):
            return {"status": "error", "message": f"File not found: {filepath}"}

        sys.path.insert(0, self.gw_path)
        try:
            from google_workspace_tools import drive_upload_file
            result = drive_upload_file(
                file_path=filepath,
                file_name=os.path.basename(filepath),
                folder_id=None,
            )
            return {"status": "ok", "result": str(result), "file": filepath}
        except Exception as e:
            logger.error(f"Drive upload failed: {e}")
            return {"status": "error", "message": str(e)}

    def _export_kg(self) -> str:
        """Export KG data and return file path."""
        try:
            data = self.kg.export_data()
            out = "/a0/usr/workdir/logs/kg_export_latest.json"
            with open(out, "w") as f:
                json.dump(data, f, indent=2)
            return out
        except Exception as e:
            logger.error(f"KG export failed: {e}")
            return ""
