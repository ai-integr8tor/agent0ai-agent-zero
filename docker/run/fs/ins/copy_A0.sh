#!/bin/bash
set -e

# Paths
SOURCE_DIR="/git/agent-zero"
TARGET_DIR="/a0"

# Get the git commit hash from the image's bundled source
IMAGE_COMMIT=$(git -C "$SOURCE_DIR" rev-parse HEAD 2>/dev/null || echo "unknown")

# Get the git commit hash from the mounted volume (if it exists and has a git repo)
VOLUME_COMMIT=$(git -C "$TARGET_DIR" rev-parse HEAD 2>/dev/null || echo "none")

if [ ! -f "$TARGET_DIR/run_ui.py" ]; then
    # Volume is empty / first run — do initial copy
    echo "No existing installation found. Copying files from $SOURCE_DIR to $TARGET_DIR..."
    cp -rn --no-preserve=ownership,mode "$SOURCE_DIR/." "$TARGET_DIR"
elif [ "$IMAGE_COMMIT" != "$VOLUME_COMMIT" ] && [ "$IMAGE_COMMIT" != "unknown" ]; then
    # Image ships a different (newer) commit than what the volume contains — sync code files
    echo "Image commit ($IMAGE_COMMIT) differs from volume commit ($VOLUME_COMMIT)."
    echo "Updating $TARGET_DIR with new image code from $SOURCE_DIR..."
    # Use rsync-style copy: overwrite existing files, but preserve user data not in the source
    # --no-preserve keeps ownership/mode from causing permission issues on the bind mount
    cp -r --no-preserve=ownership,mode "$SOURCE_DIR/." "$TARGET_DIR"
    echo "Update complete."
else
    echo "Volume is up to date with image (commit: $IMAGE_COMMIT). Skipping copy."
fi
