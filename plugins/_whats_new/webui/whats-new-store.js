import { createStore } from "/js/AlpineStore.js";
import { closeModal } from "/js/modals.js";

const ASSET_BASE = "/plugins/_whats_new/webui/assets";
const NEVER_SHOW_STORAGE_KEY = "a0_whats_new_never_show";

const slides = [
  {
    id: "parallel-tools",
    eyebrow: "Parallel execution",
    title: "Parallel tool calls and subagents",
    summary:
      "Agent Zero can now split work across parallel tool and subagents calls and combine concurrent steps results.",
    mediaType: "video",
    media: `${ASSET_BASE}/parallel-subs.webm`,
    mediaLabel:
      "Four Agent Zero subagents working in parallel while the parent agent coordinates the result.",
    bullets: [
      "Launch coordinated subagents to explore separate paths at the same time.",
      "Run mixed batches together: search queries, code execution, file reads, writes, and more.",
      "Merge the results back into one answer without waiting through every call in sequence.",
    ],
  },
  {
    id: "mcp-configuration",
    eyebrow: "MCP configuration",
    title: "Redesigned MCP configuration UI",
    summary:
      "Global Settings and Projects now share a cleaner MCP setup flow for command and Remote URL transports.",
    mediaType: "image",
    media: `${ASSET_BASE}/mcp-servers.png`,
    mediaLabel:
      "The redesigned MCP servers screen showing server cards, transport controls, and raw JSON mode.",
    bullets: [
      "Configure npx, uvx, or custom command servers with clearer fields.",
      "Connect Remote URL transports from the same accessible editor.",
      "Switch to Raw JSON when you want to paste or move configurations between clients.",
    ],
  },
  {
    id: "skills-scanner",
    eyebrow: "Agent security",
    title: "Skills Scanner powered by Snyk Agent Scan",
    summary:
      "Scan your agent skills and MCP-connected surfaces for prompt injections and vulnerabilities.",
    mediaType: "image",
    media: `${ASSET_BASE}/skills-scanner.png`,
    mediaLabel:
      "The Skills Scanner screen showing Snyk Agent Scan controls and scan guidance.",
    bullets: [
      "Review skills with the same scanning flow you already use for plugins.",
      "Find prompt-injection risks and vulnerable instructions before they reach runtime.",
      "Catch risky skill instructions early, before they become part of an agent workflow.",
    ],
  },
];

function storageValue(key) {
  try {
    return globalThis.localStorage?.getItem(key) || "";
  } catch {
    return "";
  }
}

function isNeverShowEnabled() {
  const value = storageValue(NEVER_SHOW_STORAGE_KEY);
  if (!value) return false;

  try {
    const parsed = JSON.parse(value);
    if (parsed && typeof parsed === "object") return parsed.enabled !== false;
    return Boolean(parsed);
  } catch {
    return !["0", "false", "no", "off"].includes(value.trim().toLowerCase());
  }
}

function persistNeverShowPreference(enabled) {
  try {
    if (enabled) {
      globalThis.localStorage?.setItem(
        NEVER_SHOW_STORAGE_KEY,
        JSON.stringify({
          enabled: true,
          updatedAt: new Date().toISOString(),
        }),
      );
    } else {
      globalThis.localStorage?.removeItem(NEVER_SHOW_STORAGE_KEY);
    }
  } catch {
    // localStorage may be unavailable in private or locked-down browser modes.
  }
}

export const store = createStore("whatsNew", {
  slides,
  currentIndex: 0,
  neverShowAgain: false,

  onOpen() {
    this.currentIndex = 0;
    this.neverShowAgain = isNeverShowEnabled();
  },

  cleanup() {
    persistNeverShowPreference(this.neverShowAgain);
  },

  get currentSlide() {
    return this.slides[this.currentIndex] || this.slides[0];
  },

  isFirst() {
    return this.currentIndex <= 0;
  },

  isLast() {
    return this.currentIndex >= this.slides.length - 1;
  },

  progressLabel() {
    return `${this.currentIndex + 1} of ${this.slides.length}`;
  },

  dotLabel(index) {
    const slide = this.slides[index];
    return slide ? `Show ${slide.title}` : `Show item ${index + 1}`;
  },

  goTo(index) {
    const nextIndex = Number(index);
    if (!Number.isInteger(nextIndex)) return;
    if (nextIndex < 0 || nextIndex >= this.slides.length) return;
    this.currentIndex = nextIndex;
  },

  previous() {
    if (!this.isFirst()) this.currentIndex -= 1;
  },

  setNeverShowAgain(value) {
    this.neverShowAgain = Boolean(value);
    persistNeverShowPreference(this.neverShowAgain);
  },

  next() {
    if (this.isLast()) {
      this.finish();
      return;
    }
    this.currentIndex += 1;
  },

  finish() {
    closeModal();
  },

  skip() {
    closeModal();
  },
});
