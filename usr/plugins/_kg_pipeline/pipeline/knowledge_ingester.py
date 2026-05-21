#!/usr/bin/env python3
"""Knowledge Graph ingestion script - loads files into standalone KG service."""
import os
import sys
import json
import time
import requests
import argparse
from pathlib import Path
from datetime import datetime

KG_SERVICE = os.getenv("KG_SERVICE", "http://100.78.79.41:8010/api/v1")
KNOWLEDGE_DIR = os.getenv("KNOWLEDGE_DIR", "/a0/usr/knowledge")
STATE_FILE = "/a0/usr/workdir/logs/kg_ingest_state.json"
LOG_FILE = "/a0/usr/workdir/logs/kg_ingest.log"
MAX_FILE_SIZE_KB = 50
ARCHIVE_DIR = os.path.join(KNOWLEDGE_DIR, "_archived")

def archive_file(filepath, knowledge_dir):
    """Move successfully ingested file to _archived/ directory."""
    rel_path = os.path.relpath(filepath, knowledge_dir)
    archive_path = os.path.join(ARCHIVE_DIR, rel_path)
    os.makedirs(os.path.dirname(archive_path), exist_ok=True)
    os.rename(filepath, archive_path)
    return archive_path  # Skip files larger than this

def log(msg):
    ts = datetime.utcnow().isoformat()
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")

def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}

def save_state(state):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def detect_domain(filepath):
    p = filepath.lower()
    if any(x in p for x in ["work", "sales", "territory", "deal", "pipeline", "sled"]):
        return "work"
    elif any(x in p for x in ["personal", "life", "home", "bookmark"]):
        return "personal"
    elif any(x in p for x in ["infra", "model", "docker", "server", "system", "framework"]):
        return "technology"
    else:
        return "context"

def find_files(knowledge_dir, limit=None, resume=False, state=None):
    files = []
    for root, dirs, filenames in os.walk(knowledge_dir):
        dirs[:] = [d for d in dirs if d != "_archived"]  # Skip archived files
        for fn in filenames:
            if not fn.endswith(".md"):
                continue
            fp = os.path.join(root, fn)
            size_kb = os.path.getsize(fp) / 1024
            if size_kb > MAX_FILE_SIZE_KB or size_kb < 2.0:
                continue
            # Skip YouTube bookmarks without enriched content
            if "/bookmarks/" in fp:
                try:
                    with open(fp, "r", encoding="utf-8", errors="replace") as f:
                        content = f.read()
                    if ("youtube.com" in content or "youtu.be" in content):
                        if "## Scraped Content" not in content and "## Gemini Summary" not in content:
                            continue  # Skip unenriched YouTube bookmarks
                except:
                    pass
            if resume and state and fp in state and state[fp].get("status") == "done":
                stored_mtime = state[fp].get("mtime", 0)
                current_mtime = os.path.getmtime(fp)
                if stored_mtime == current_mtime:
                    continue  # File unchanged, skip
                # else: file was updated, re-ingest
            files.append((fp, size_kb))
    files.sort(key=lambda x: x[1])  # Sort by size (smallest first)
    if limit:
        files = files[:limit]
    return files

def ingest_file(filepath, size_kb):
    """Ingest a single file into the KG service."""
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        
        if len(content.strip()) < 200:
            return {"status": "skipped", "reason": "too short", "entities": 0, "relationships": 0}
        
        # Add source prefix
        full_content = f"Source: {filepath}\n\n{content[:8000]}"
        domain = detect_domain(filepath)
        
        start = time.time()
        r = requests.post(
            f"{KG_SERVICE}/add",
            json={"content": full_content, "source_path": filepath, "domain": domain},
            timeout=120
        )
        elapsed = time.time() - start
        
        if r.status_code == 200:
            result = r.json()
            return {
                "status": "done",
                "entities": result.get("entities", 0),
                "relationships": result.get("relationships", 0),
                "domain": result.get("domain", domain),
                "elapsed": round(elapsed, 1)
            }
        else:
            return {"status": "failed", "error": f"HTTP {r.status_code}: {r.text[:200]}", "elapsed": round(elapsed, 1)}
    except Exception as e:
        return {"status": "failed", "error": str(e)}

def main():
    parser = argparse.ArgumentParser(description="Ingest knowledge files into KG service")
    parser.add_argument("--limit", type=int, default=None, help="Max files to process")
    parser.add_argument("--resume", action="store_true", help="Skip already-processed files")
    parser.add_argument("--force-reingest", action="store_true", help="Clear state and reprocess all files")
    parser.add_argument("--status", action="store_true", help="Show current status")
    args = parser.parse_args()

    # Status check
    if args.status:
        try:
            r = requests.get(f"{KG_SERVICE}/status", timeout=5)
            print(json.dumps(r.json(), indent=2))
        except Exception as e:
            print(f"Service error: {e}")
        state = load_state()
        done = sum(1 for v in state.values() if v.get("status") == "done")
        failed = sum(1 for v in state.values() if v.get("status") == "failed")
        print(f"\nState file: {done} done, {failed} failed, {len(state)} total")
        return

    # Health check
    try:
        r = requests.get(f"{KG_SERVICE.replace('/api/v1', '')}/health", timeout=5)
        if r.status_code != 200:
            log("ERROR: KG service not healthy")
            return
        log("KG service healthy")
    except Exception as e:
        log(f"ERROR: Cannot reach KG service: {e}")
        return

    state = {} if args.force_reingest else load_state()
    if args.force_reingest:
        log("Force reingest: clearing state, reprocessing all files")
    files = find_files(KNOWLEDGE_DIR, limit=args.limit, resume=(args.resume and not args.force_reingest), state=state)
    log(f"Found {len(files)} files to process")

    total_ents = 0
    total_rels = 0
    done_count = 0
    fail_count = 0

    for i, (fp, size_kb) in enumerate(files):
        log(f"[{i+1}/{len(files)}] Processing: {fp} ({size_kb:.1f}KB)")
        result = ingest_file(fp, size_kb)
        state[fp] = {"status": result["status"], **result, "mtime": os.path.getmtime(fp), "timestamp": datetime.utcnow().isoformat()}
        # Archive successfully ingested file (skip bookmarks for karakeep sync)
        if result.get("status") == "done" and "/bookmarks/" not in fp:
            try:
                archive_path = archive_file(fp, KNOWLEDGE_DIR)
                log(f"  -> Archived to {archive_path}")
            except Exception as e:
                log(f"  -> Archive failed: {e}")

        save_state(state)

        if result["status"] == "done":
            total_ents += result.get("entities", 0)
            total_rels += result.get("relationships", 0)
            done_count += 1
            log(f"  -> {result['entities']} entities, {result['relationships']} rels in {result.get('elapsed', 0)}s")
        elif result["status"] == "skipped":
            log(f"  -> Skipped: {result.get('reason')}")
        else:
            fail_count += 1
            log(f"  -> FAILED: {result.get('error', 'unknown')}")

    # Final summary
    log(f"\n=== INGESTION COMPLETE ===")
    log(f"Files processed: {done_count} done, {fail_count} failed")
    log(f"Entities added: {total_ents}")
    log(f"Relationships added: {total_rels}")

    # Run janitor after ingest (normalize + orphans, skip fuzzy for speed)
    if done_count > 0:
        log("\nRunning janitor (normalize + orphans)...")
        try:
            r = requests.post(f"{KG_SERVICE.replace('/api/v1', '')}/api/v1/janitor",
                json={"passes": ["normalize", "orphans"], "dry_run": False}, timeout=60)
            if r.status_code == 200:
                result = r.json()
                total = result.get("total_actions", 0)
                log(f"Janitor: {total} cleanup actions performed")
            else:
                log(f"Janitor: returned status {r.status_code}")
        except Exception as e:
            log(f"Janitor: error - {e}")

    # Get final status from service
    try:
        r = requests.get(f"{KG_SERVICE}/status", timeout=5)
        svc_status = r.json()
        log(f"Service status: {svc_status['entities']} entities, {svc_status['relationships']} relationships, {svc_status['documents']} documents")
    except:
        pass

if __name__ == "__main__":
    main()
