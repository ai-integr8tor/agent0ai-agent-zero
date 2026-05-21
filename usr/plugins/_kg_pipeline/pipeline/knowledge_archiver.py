#!/usr/bin/env python3
"""Knowledge Archiver - Scans knowledge directory for KG-included files

Scans /a0/usr/knowledge/ for files already in KG (checking via KG API),
moves confirmed KG files to /a0/usr/knowledge/_archived/,
maintains a manifest of archived files, runs as scheduled task.

Usage:
    python3 /a0/usr/plugins/_kg_pipeline/pipeline/knowledge_archiver.py [--dry-run] [--scan-dir PATH]
"""

import json
import hashlib
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
import argparse
import requests

# Configuration
KNOWLEDGE_DIR = Path("/a0/usr/knowledge")
ARCHIVED_DIR = Path("/a0/usr/knowledge/_archived")
ARCHIVE_MANIFEST = Path("/a0/usr/knowledge/_archived/_manifest.json")
ARCHIVE_LOG = Path("/a0/usr/workdir/logs/knowledge_archiver.log")
KG_SERVICE_URL = "http://100.78.79.41:8010"


def log_operation(message: str, dry_run: bool = False) -> None:
    """Log operation with timestamp."""
    prefix = "[DRY RUN] " if dry_run else ""
    timestamp = datetime.now().isoformat()
    log_line = f"{timestamp} {prefix}{message}\n"
    
    ARCHIVE_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(ARCHIVE_LOG, 'a') as f:
        f.write(log_line)
    print(log_line.strip())


def load_manifest() -> Dict[str, Any]:
    """Load archive manifest."""
    if ARCHIVE_MANIFEST.exists():
        with open(ARCHIVE_MANIFEST, 'r') as f:
            return json.load(f)
    return {
        'created': datetime.now().isoformat(),
        'archived_files': []
    }


def save_manifest(manifest: Dict[str, Any]) -> None:
    """Save archive manifest."""
    ARCHIVED_DIR.mkdir(parents=True, exist_ok=True)
    with open(ARCHIVE_MANIFEST, 'w') as f:
        json.dump(manifest, f, indent=2)


def compute_file_hash(file_path: Path) -> str:
    """Compute SHA256 hash of file content."""
    sha256 = hashlib.sha256()
    with open(file_path, 'rb') as f:
        sha256.update(f.read())
    return sha256.hexdigest()[:16]


def check_file_in_kg(file_path: Path) -> Optional[Dict[str, Any]]:
    """Check if file content exists in KG via source_path check."""
    try:
        # Query KG for documents matching this source path pattern
        source_pattern = str(file_path.relative_to(KNOWLEDGE_DIR.parent))
        
        # Use temporal search as a proxy for file existence
        cypher_query = """
        MATCH (d:Document)
        WHERE d.source_path CONTAINS $filename
        RETURN d.doc_id AS doc_id, d.source_path AS source_path, d.created_at AS created
        LIMIT 1
        """
        
        resp = requests.post(
            f"{KG_SERVICE_URL}/api/v1/query",
            json={"query": cypher_query, "params": {"filename": file_path.name}},
            timeout=10
        )
        
        if resp.status_code == 200:
            data = resp.json()
            if data.get('rows', []):
                return {
                    'in_kg': True,
                    'doc_id': data['rows'][0].get('doc_id'),
                    'source_path': data['rows'][0].get('source_path')
                }
        
        return {'in_kg': False}
    except Exception as e:
        log_operation(f"Error checking KG for {file_path}: {e}", dry_run=True)
        return {'in_kg': False, 'error': str(e)}


def get_knowledge_files(base_dir: Path) -> List[Path]:
    """Get all knowledge files recursively."""
    files = []
    if not base_dir.exists():
        return files
    
    for ext in ['*.md', '*.json', '*.txt', '*.yaml', '*.yml']:
        files.extend(base_dir.rglob(ext))
    
    return [f for f in files if not f.name.startswith('_') and '_archived' not in str(f)]


def archive_file(file_path: Path, dry_run: bool = False) -> bool:
    """Move file to archived directory."""
    try:
        # Compute relative path to preserve structure
        rel_path = file_path.relative_to(KNOWLEDGE_DIR)
        dest_path = ARCHIVED_DIR / rel_path
        
        if dry_run:
            log_operation(f"Would archive: {file_path} → {dest_path}", dry_run=True)
            return True
        
        # Create destination directory
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Move file
        shutil.move(str(file_path), str(dest_path))
        log_operation(f"Archived: {file_path} → {dest_path}")
        return True
    except Exception as e:
        log_operation(f"Failed to archive {file_path}: {e}", dry_run=dry_run)
        return False


def run_archiver(dry_run: bool = False, scan_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Run the full archival pipeline."""
    log_operation("=== Starting Knowledge Archiver ===", dry_run)
    
    manifest = load_manifest()
    base_dir = scan_dir or KNOWLEDGE_DIR
    
    # Get all knowledge files
    files = get_knowledge_files(base_dir)
    log_operation(f"Found {len(files)} knowledge files in {base_dir}", dry_run)
    
    archived_count = 0
    failed_count = 0
    skipped_count = 0
    
    for file_path in files:
        # Skip already archived files
        if '_archived' in str(file_path):
            skipped_count += 1
            continue
        
        # Check if already in manifest
        file_hash = compute_file_hash(file_path)
        already_archived = any(
            entry.get('hash') == file_hash for entry in manifest['archived_files']
        )
        
        if already_archived:
            skipped_count += 1
            continue
        
        # Check KG for this file
        kg_check = check_file_in_kg(file_path)
        
        if kg_check.get('in_kg'):
            # File exists in KG, can be archived
            if archive_file(file_path, dry_run):
                # Add to manifest
                manifest['archived_files'].append({
                    'original_path': str(file_path),
                    'archived_path': str(ARCHIVED_DIR / file_path.relative_to(KNOWLEDGE_DIR)),
                    'hash': file_hash,
                    'archived_at': datetime.now().isoformat(),
                    'kg_doc_id': kg_check.get('doc_id'),
                    'file_size': file_path.stat().st_size
                })
                archived_count += 1
            else:
                failed_count += 1
        else:
            # Not in KG, leave in place
            log_operation(f"Not in KG, keeping: {file_path}", dry_run=dry_run)
    
    # Save manifest
    if not dry_run:
        save_manifest(manifest)
    
    summary = {
        'total_files': len(files),
        'archived': archived_count,
        'failed': failed_count,
        'skipped': skipped_count,
        'total_archived_in_manifest': len(manifest['archived_files'])
    }
    
    log_operation(f"=== Archival Complete === {summary}", dry_run)
    return summary


def main():
    parser = argparse.ArgumentParser(description='Knowledge Archiver')
    parser.add_argument('--dry-run', action='store_true', help='Simulate without archiving')
    parser.add_argument('--scan-dir', type=Path, help='Directory to scan (default: /a0/usr/knowledge)')
    parser.add_argument('--check-khealth', action='store_true', help='Check KG health and exit')
    args = parser.parse_args()
    
    if args.check_khealth:
        try:
            resp = requests.get(f"{KG_SERVICE_URL}/api/v1/status", timeout=10)
            if resp.status_code == 200:
                print(f"KG is healthy: {resp.json()}")
            else:
                print(f"KG returned status {resp.status_code}")
                return 1
        except Exception as e:
            print(f"KG connection failed: {e}")
            return 1
        return 0
    
    print(f"=== Knowledge Archiver ===")
    print(f"Knowledge dir: {args.scan_dir or KNOWLEDGE_DIR}")
    print(f"Archive dir: {ARCHIVED_DIR}")
    print(f"Manifest: {ARCHIVE_MANIFEST}")
    print(f"KG URL: {KG_SERVICE_URL}")
    
    result = run_archiver(dry_run=args.dry_run, scan_dir=args.scan_dir)
    
    print(f"\n=== Summary ===")
    print(json.dumps(result, indent=2))
    
    return 0


if __name__ == "__main__":
    exit(main())
