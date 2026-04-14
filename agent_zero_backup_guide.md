# Agent Zero Backup & Persistence Setup Guide

## 1. Built-in Backup System Setup (Recommended)

### How to Access
1. Start Agent Zero with Docker
2. Open the Web UI (usually http://localhost:PORT)
3. Click **Settings** (gear icon in sidebar)
4. Navigate to **Backup & Restore** tab
5. Use **Create Backup** or **Restore from Backup**

### Default Backup Patterns
The built-in system automatically backs up:

**✅ SAFE TO BACKUP (User Data):**
```
# Knowledge (excluding defaults)
/a0/knowledge/**
!/a0/knowledge/default/**

# Instruments (excluding defaults) 
/a0/instruments/**
!/a0/instruments/default/**

# Memory (excluding embeddings cache)
/a0/memory/**
!/a0/memory/**/embeddings/**

# Critical Configuration Files
/a0/.env                    # API keys & config (CRITICAL!)
/a0/tmp/settings.json       # Your settings
/a0/tmp/secrets.env         # Secrets
/a0/tmp/chats/**           # Chat history
/a0/tmp/scheduler/**       # Scheduled tasks
/a0/tmp/uploads/**         # Uploaded files

# User data directory
/a0/usr/**
```

### How to Create Backups
1. Settings → Backup & Restore → **Create Backup**
2. Review/edit the JSON patterns if needed
3. Click **Dry Run** to preview files
4. Click **Create Backup** to download .zip file
5. Store backup file safely on your local system

### How to Restore Backups
1. Settings → Backup & Restore → **Restore from Backup**
2. Upload your .zip backup file
3. Review/edit restore patterns
4. Choose overwrite policy (overwrite/skip/backup existing)
5. Click **Dry Run** to preview changes
6. Click **Restore Files** to execute

---

## 2. Selective Directory Mapping (Alternative/Additional)

### ✅ SAFE Directories to Map

```bash
# Recommended selective mapping (choose what you need):
-v /your/local/path/memory:/a0/memory
-v /your/local/path/knowledge:/a0/knowledge  
-v /your/local/path/instruments:/a0/instruments
-v /your/local/path/usr:/a0/usr
-v /your/local/path/tmp:/a0/tmp
```

### 🔴 CRITICAL Files (Map individually)
```bash
# Essential config files (backup these!)
-v /your/local/path/.env:/a0/.env
-v /your/local/path/settings.json:/a0/tmp/settings.json
```

### ❌ AVOID Mapping These Directories

**DO NOT MAP** (these change between versions):
- `/a0` (entire root directory)
- `/a0/data/**` (system files) 
- `/a0/python/**` (application code)
- `/a0/webui/**` (web interface)
- `/a0/docs/**` (documentation)
- `/a0/prompts/agent.system.*` (system prompts)
- `/a0/knowledge/default/**` (default knowledge)
- `/a0/instruments/default/**` (default instruments)

---

## 3. Complete Docker Setup Examples

### Option A: Built-in Backup Only (Recommended)
```bash
# Simple setup - use built-in backup/restore
docker run -d \
  --name agent-zero \
  -p 8080:80 \
  agent0ai/agent-zero
```

### Option B: Selective Directory Mapping
```bash
# Map only user data directories
docker run -d \
  --name agent-zero \
  -p 8080:80 \
  -v /your/agent-zero-data/memory:/a0/memory \
  -v /your/agent-zero-data/knowledge:/a0/knowledge \
  -v /your/agent-zero-data/instruments:/a0/instruments \
  -v /your/agent-zero-data/usr:/a0/usr \
  -v /your/agent-zero-data/tmp:/a0/tmp \
  -v /your/agent-zero-data/.env:/a0/.env \
  agent0ai/agent-zero
```

### Option C: Hybrid Approach (Best of Both)
```bash
# Map critical user data + use backup system for safety
docker run -d \
  --name agent-zero \
  -p 8080:80 \
  -v /your/agent-zero-data/memory:/a0/memory \
  -v /your/agent-zero-data/knowledge:/a0/knowledge \
  -v /your/agent-zero-data/tmp:/a0/tmp \
  -v /your/agent-zero-data/.env:/a0/.env \
  agent0ai/agent-zero
```

---

## 4. Update-Safe Workflow

### Before Updating Agent Zero:
1. **Create backup** via Settings → Backup & Restore
2. Download and save the .zip file
3. Note your current volume mappings (if using any)

### Update Process:
```bash
# Stop current container
docker stop agent-zero

# Remove container (data is safe in volumes/backups)
docker rm agent-zero

# Pull latest image
docker pull agent0ai/agent-zero

# Run new container with same volume mappings
docker run -d \
  --name agent-zero \
  -p 8080:80 \
  [your volume mappings here] \
  agent0ai/agent-zero
```

### After Update:
1. If any issues, restore from backup
2. Check that all settings and data are intact
3. Create new backup of updated system

---

## 5. Directory Structure Breakdown

### User-Safe Directories (OK to map/backup):
```
/a0/memory/          - Agent's learned memories
/a0/knowledge/custom/ - Your custom knowledge files  
/a0/instruments/custom/ - Your custom tools/functions
/a0/usr/             - Your user files
/a0/tmp/chats/       - Chat history
/a0/tmp/settings.json - Your preferences
/a0/.env             - API keys & configuration
```

### System Directories (DO NOT map):
```
/a0/python/          - Application source code
/a0/webui/           - Web interface files
/a0/data/            - System data files
/a0/prompts/         - System prompt templates
/a0/knowledge/default/ - Default knowledge base
/a0/instruments/default/ - Default tools
```

---

## 6. Best Practices

### Backup Strategy:
- ✅ Use built-in backup system for complete safety
- ✅ Create backups before any major changes
- ✅ Store backup files outside the container
- ✅ Test restore process occasionally

### Directory Mapping Strategy:
- ✅ Only map directories you actively work with
- ✅ Map individual files for critical configs
- ✅ Avoid mapping entire `/a0` directory
- ✅ Keep volume paths consistent between updates

### Update Safety:
- ✅ Always backup before updating
- ✅ Use same volume mapping paths after update  
- ✅ Test functionality after update
- ✅ Keep previous backup until new version is stable

---

## 7. Troubleshooting

### If you mapped `/a0` entirely:
1. Stop container
2. Create backup of your `/a0` folder
3. Remove container and restart with selective mapping
4. Copy important files back manually

### If backup/restore fails:
1. Check file permissions on mapped volumes
2. Ensure enough disk space for backups
3. Verify .zip file isn't corrupted
4. Try restoring with "backup existing" policy

### If settings are lost after update:
1. Check if `.env` and `settings.json` are preserved
2. Restore from backup if needed
3. Reconfigure API keys if necessary