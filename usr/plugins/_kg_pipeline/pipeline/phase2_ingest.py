#!/usr/bin/env python3
"""Phase 2 Ingestion Script: FAISS summary output + KG HTTP ingestion."""

import json
import os
import time
import requests
import sys

WORKDIR = '/a0/usr/workdir'
DELTA_FILE = f'{WORKDIR}/logs/delta_sorted_phase2.json'
RESULTS_FILE = f'{WORKDIR}/logs/phase2_ingest_results.json'
FAISS_MANIFEST = f'{WORKDIR}/logs/phase2_faiss_manifest.json'
KG_API = 'http://100.78.79.41:8010/api/v1/add'
KG_TIMEOUT = 60
KG_DELAY = 0.5
FAISS_AREA = 'strategic_workdir'
MAX_FAISS_CHARS = 2000
MAX_KG_CHARS = 5000

results = {
    'scanned': 0,
    'faiss_queued': 0,
    'kg_success': 0,
    'kg_fail': 0,
    'kg_failures': [],
    'started_at': time.strftime('%Y-%m-%dT%H:%M:%S')
}

def main():
    print("=" * 60)
    print("Phase 2 Ingestion: KG HTTP + FAISS Manifest")
    print("=" * 60)

    with open(DELTA_FILE, 'r') as f:
        delta = json.load(f)

    results['scanned'] = len(delta)
    print(f"Files to process: {len(delta)}")

    # Phase 1: Build FAISS manifest (for memory_save calls)
    faiss_queue = []
    for file_info in delta:
        path = file_info['path']
        score = file_info.get('score', 0)
        reason = file_info.get('reason', 'unknown')
        full_path = os.path.join(WORKDIR, path)

        if not os.path.exists(full_path):
            print(f"  SKIP (not found): {path}")
            continue

        try:
            with open(full_path, 'r', errors='replace') as f:
                content = f.read()
        except Exception as e:
            print(f"  SKIP (read error): {path}: {e}")
            continue

        summary = content[:MAX_FAISS_CHARS]
        faiss_queue.append({
            'path': path,
            'score': score,
            'reason': reason,
            'size': file_info.get('size', 0),
            'summary': summary,
            'full_content': content[:MAX_KG_CHARS]
        })

    results['faiss_queued'] = len(faiss_queue)

    # Save FAISS manifest for memory_save tool calls
    with open(FAISS_MANIFEST, 'w') as f:
        json.dump(faiss_queue, f, indent=2)
    print(f"\nFAISS manifest saved: {len(faiss_queue)} files -> {FAISS_MANIFEST}")

    # Phase 2: KG ingestion
    print(f"\nStarting KG ingestion...")
    kg_success = 0
    kg_fail = 0
    kg_failures = []

    for i, item in enumerate(faiss_queue):
        path = item['path']
        score = item['score']
        content = item['full_content']

        print(f"  [{i+1}/{len(faiss_queue)}] [{score}] {path}...", end=' ', flush=True)

        try:
            payload = {
                'content': content,
                'source_path': f'workdir/strategic/{os.path.basename(path)}',
                'domain': 'context'
            }
            resp = requests.post(KG_API, json=payload, timeout=KG_TIMEOUT)
            if resp.status_code == 200:
                kg_success += 1
                print(f"OK")
            else:
                kg_fail += 1
                err_msg = f"HTTP {resp.status_code}: {resp.text[:200]}"
                print(f"FAIL ({err_msg})")
                kg_failures.append({'path': path, 'score': score, 'error': err_msg})
        except requests.exceptions.Timeout:
            kg_fail += 1
            print(f"TIMEOUT")
            kg_failures.append({'path': path, 'score': score, 'error': 'timeout'})
        except Exception as e:
            kg_fail += 1
            print(f"ERROR: {e}")
            kg_failures.append({'path': path, 'score': score, 'error': str(e)})

        time.sleep(KG_DELAY)

        # Progress every 20 files
        if (i + 1) % 20 == 0:
            elapsed = time.time() - start_time
            print(f"\n--- Progress: {i+1}/{len(faiss_queue)} ({elapsed:.0f}s elapsed) ---")
            print(f"    KG: {kg_success} ok / {kg_fail} fail")

    # Save results
    results['kg_success'] = kg_success
    results['kg_fail'] = kg_fail
    results['kg_failures'] = kg_failures
    results['completed_at'] = time.strftime('%Y-%m-%dT%H:%M:%S')

    with open(RESULTS_FILE, 'w') as f:
        json.dump(results, f, indent=2)

    print(f"\n{'=' * 60}")
    print(f"KG INGESTION COMPLETE")
    print(f"{'=' * 60}")
    print(f"Files scanned:    {results['scanned']}")
    print(f"FAISS queued:     {results['faiss_queued']}")
    print(f"KG success:       {kg_success}")
    print(f"KG failed:        {kg_fail}")
    print(f"Results saved:    {RESULTS_FILE}")
    print(f"FAISS manifest:   {FAISS_MANIFEST}")

start_time = time.time()

if __name__ == '__main__':
    main()
