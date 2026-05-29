import { createStore } from "/js/AlpineStore.js";

// ── Proxy-based API communication ─────────────────────────────
// All requests go through the A0 proxy for secure access.
let _callJsonApi = null;
async function getApi() {
    if (!_callJsonApi) { const m = await import("/js/api.js"); _callJsonApi = m.callJsonApi; }
    return _callJsonApi;
}

async function proxyFetch(path, options = {}) {
    const method = (options.method || "GET").toUpperCase();
    // FormData uploads are not supported through the JSON proxy
    if (typeof FormData !== 'undefined' && options.body instanceof FormData) {
        throw new Error('File uploads are not supported in proxy mode. Connect directly to the server.');
    }
    const body = options.body ? (typeof options.body === "string" ? JSON.parse(options.body) : options.body) : null;
    const headers = {};
    if (options.headers) {
        const h = options.headers;
        if (typeof h === "object") Object.assign(headers, h);
    }
    const fn = await getApi();
    const result = await fn("plugins/open-notebook/proxy", {
        method: method,
        path: path,
        body: body,
        headers: headers,
    });
    if (result && result._proxy_status !== undefined) {
        if (result._proxy_status >= 400) throw new Error(`HTTP ${result._proxy_status}`);
        return { ok: true, status: result._proxy_status, json: () => Promise.resolve(result.data), data: result.data };
    }
    return { ok: true, status: 200, json: () => Promise.resolve(result), data: result };
}

async function smartFetch(path, options = {}) {
    return proxyFetch(path, options);
}

async function getAudioUrl(path) {
    // For audio, we need to route through the proxy with binary support
    // Use a direct proxy path that streams the audio
    return `/api/plugins/open-notebook/proxy?__audio=1&path=${encodeURIComponent(path)}`;
}

let _notebooksLoaded = false;

// ── Simple Markdown → HTML ────────────────────────────
function md(text) {
    if (!text) return '';
    return text
        .replace(/```([\s\S]*?)```/g, '<pre style="background:var(--color-code-bg,rgba(0,0,0,0.1));padding:8px;border-radius:4px;overflow-x:auto;font-size:0.85em;margin:4px 0"><code>$1</code></pre>')
        .replace(/`([^`]+)`/g, '<code style="background:var(--color-code-bg,rgba(0,0,0,0.1));padding:1px 4px;border-radius:3px;font-size:0.85em">$1</code>')
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.+?)\*/g, '<em>$1</em>')
        .replace(/^### (.+)$/gm, '<h4 style="margin:8px 0 4px;font-size:0.95em">$1</h4>')
        .replace(/^## (.+)$/gm, '<h3 style="margin:8px 0 4px;font-size:1em">$1</h3>')
        .replace(/^# (.+)$/gm, '<h2 style="margin:8px 0 4px;font-size:1.1em">$1</h2>')
        .replace(/^[-*] (.+)$/gm, '<li style="margin-left:16px">$1</li>')
        .replace(/\n\n/g, '</p><p style="margin:4px 0">')
        .replace(/\n/g, '<br>');
}

const model = {
    // ── Helpers ────────────────────────────────────────────
    md(text) { return md(text); },

    // ── State ──────────────────────────────────────────────
    isOpen: false,
    activeTab: 'sources',
    loading: false,
    error: null,

    notebooks: [],
    selectedNotebookId: null,
    selectedNotebook: null,

    sources: [],
    notes: [],
    episodes: [],
    _activeMenuId: null,
    _menuPos: { top: 0, right: 0 },

    // Global search (homepage — searches all notebooks)
    globalSearchText: '',
    globalSearchResult: null,
    globalSearchLoading: false,

    // Chat state (notebook-scoped)
    chatSessionId: null,
    chatMessages: [],
    chatInput: '',
    chatLoading: false,
    chatSessions: [],
    chatContext: null,

    // Source chat
    sourceChatSessionId: null,
    sourceChatMessages: [],
    sourceChatInput: '',
    sourceChatLoading: false,
    activeSourceChatId: null,

    // Related sources
    relatedResults: null,
    relatedLoading: false,
    relatedSourceId: null,

    // Quick-journal state
    newNoteTitle: '',
    newNoteContent: '',
    savingNote: false,

    // Note CRUD form
    showNoteForm: false,
    noteForm: { title: '', content: '' },
    editingNoteId: null,

    // Podcast player
    currentEpisodeId: null,
    isPlaying: false,

    // Podcast generation
    episodeProfiles: [],
    speakerProfiles: [],
    showGenerateForm: false,
    generateForm: {
        episode_name: '',
        episode_profile: '',
        speaker_profile: '',
        content: ''
    },
    generatingJob: null,

    // Source import
    showSourceImport: false,
    sourceImportTab: 'url',
    sourceImportLoading: false,
    sourceImportUrl: '',
    sourceImportTitle: '',
    sourceImportContent: '',

    // Notebook creation form
    showCreateNotebook: false,
    newNotebookName: '',
    newNotebookDesc: '',

    // Source insights
    sourceInsights: [],
    showSourceInsights: false,
    activeInsightSourceId: null,
    _expandedInsights: {},
    transformations: [],
    selectedTransformationId: '',
    // Resize state
    panelWidth: 420,
    isDragging: false,
    _minWidth: 300,
    _maxWidth: 800,

    // ── Computed Getters ───────────────────────────────────
    get statusColor() {
        if (this.error) return 'var(--color-error-text)';
        if (this.selectedNotebook) return 'var(--color-secondary)';
        return 'var(--color-accent)';
    },

    get hasNotebookSelected() {
        return this.selectedNotebookId !== null && this.selectedNotebook !== null;
    },

    get panelStyle() {
        document.documentElement.style.setProperty('--on-panel-width', this.panelWidth + 'px');
        return `width: ${this.panelWidth}px`;
    },

    // ── Panel Actions ──────────────────────────────────────
    togglePanel() {
        if (this.isOpen) {
            this.closePanel();
        } else {
            this.isOpen = true;
            document.body.classList.add('on-panel-active');
            document.documentElement.style.setProperty('--on-panel-width', this.panelWidth + 'px');
            if (!_notebooksLoaded) {
                this.loadNotebooks();
                _notebooksLoaded = true;
            }
            this.loadTransformations();
        }
    },

    closePanel() {
        this.isOpen = false;
        this.error = null;
        document.body.classList.remove('on-panel-active');
        document.documentElement.style.removeProperty('--on-panel-width');
    },

    selectTab(tab) {
        this.activeTab = tab;
        if (!this.selectedNotebookId) return;

        if (tab === 'sources' && this.sources.length === 0) {
            this.loadSources();
        } else if (tab === 'notes' && this.notes.length === 0) {
            this.loadNotes();
        } else if (tab === 'podcasts' && this.episodes.length === 0) {
            this.loadEpisodes();
        } else if (tab === 'chat') {
            this.loadChatSessions();
        }

        if (tab === 'chat') {
            setTimeout(() => {
                const ta = document.querySelector('.on-tab-pane--chat textarea');
                if (ta) ta.focus();
            }, 100);
        }
    },

    goBack() {
        this.selectedNotebookId = null;
        this.selectedNotebook = null;
        this.sources = [];
        this.notes = [];
        this.episodes = [];
        this.error = null;
        this.activeTab = 'sources';
        this.relatedResults = null;
        this.relatedSourceId = null;
        this.resetChat();
        this.showGenerateForm = false;
        this.generatingJob = null;
        this.showSourceImport = false;
        this.sourceImportUrl = '';
        this.sourceImportTitle = '';
        this.sourceImportContent = '';
    },

    // ── Notebook CRUD ──────────────────────────────────────
    async loadNotebooks() {
        this.loading = true;
        this.error = null;
        try {
            const resp = await smartFetch(`/api/notebooks`);
            if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);
            this.notebooks = await resp.json();
        } catch (e) {
            this.error = `Failed to load notebooks: ${e.message}`;
            this.notebooks = [];
        } finally {
            this.loading = false;
        }
    },

    async selectNotebook(id) {
        this.selectedNotebookId = id;
        this.loading = true;
        this.error = null;
        try {
            const resp = await smartFetch(`/api/notebooks/${encodeURIComponent(id)}`);
            if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);
            this.selectedNotebook = await resp.json();
            await this.loadSources();
        } catch (e) {
            this.error = `Failed to load notebook: ${e.message}`;
            this.selectedNotebook = null;
        } finally {
            this.loading = false;
        }
    },

    async deleteNotebook(id) {
        if (!id) return;
        this.loading = true;
        this.error = null;
        try {
            const resp = await smartFetch(`/api/notebooks/${encodeURIComponent(id)}`, {
                method: 'DELETE',
            });
            if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);
            if (this.selectedNotebookId === id) {
                this.goBack();
            }
            await this.loadNotebooks();
        } catch (e) {
            this.error = `Failed to delete notebook: ${e.message}`;
        } finally {
            this.loading = false;
        }
    },
    async createNotebook(name, description) {
        try {
            const resp = await smartFetch('/api/notebooks', {
                method: 'POST',
                body: JSON.stringify({ name: name.trim(), description: description?.trim() || '' })
            });
            if (!resp.ok) throw new Error('Failed to create notebook');
            this.showCreateNotebook = false;
            this.newNotebookName = '';
            this.newNotebookDesc = '';
            await this.loadNotebooks();
        } catch (e) {
            this.error = e.message;
        }
    },

    async renameNotebook(notebookId, name) {
        try {
            const resp = await smartFetch('/api/notebooks/' + notebookId, {
                method: 'PUT',
                body: JSON.stringify({ name: name.trim() })
            });
            if (!resp.ok) throw new Error('Failed to rename notebook');
            await this.loadNotebooks();
            if (this.selectedNotebookId === notebookId && this.selectedNotebook) {
                this.selectedNotebook.name = name.trim();
            }
        } catch (e) {
            this.error = e.message;
        }
    },


    // ── Sources ────────────────────────────────────────────
    async loadSources() {
        if (!this.selectedNotebookId) return;
        this.loading = true;
        this.error = null;
        try {
            const params = new URLSearchParams({
                notebook_id: this.selectedNotebookId
            });
            const resp = await smartFetch(`/api/sources?${params}`);
            if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);
            this.sources = await resp.json();
        } catch (e) {
            this.error = `Failed to load sources: ${e.message}`;
            this.sources = [];
        } finally {
            this.loading = false;
        }
    },

    // ── Source Import ────────────────────────────────────
    toggleSourceImport() {
        this.showSourceImport = !this.showSourceImport;
        if (this.showSourceImport) {
            this.sourceImportTab = 'url';
            this.sourceImportUrl = '';
            this.sourceImportTitle = '';
            this.sourceImportContent = '';
            this.sourceImportLoading = false;
        }
    },

    async addSourceUrl() {
        if (!this.selectedNotebookId || !this.sourceImportUrl?.trim()) return;
        this.sourceImportLoading = true;
        this.error = null;
        try {
            const resp = await smartFetch(`/api/sources/json`, {
                method: 'POST',
                body: JSON.stringify({
                    type: 'link',
                    notebook_id: this.selectedNotebookId,
                    url: this.sourceImportUrl.trim(),
                    title: this.sourceImportTitle?.trim() || undefined,
                    embed: true,
                }),
            });
            if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);
            this.sourceImportUrl = '';
            this.sourceImportTitle = '';
            this.showSourceImport = false;
            await this.loadSources();
        } catch (e) {
            this.error = `Failed to import URL: ${e.message}`;
        } finally {
            this.sourceImportLoading = false;
        }
    },

    async addSourceText() {
        if (!this.selectedNotebookId || !this.sourceImportContent?.trim()) return;
        this.sourceImportLoading = true;
        this.error = null;
        try {
            const resp = await smartFetch(`/api/sources/json`, {
                method: 'POST',
                body: JSON.stringify({
                    type: 'text',
                    notebook_id: this.selectedNotebookId,
                    content: this.sourceImportContent.trim(),
                    title: this.sourceImportTitle?.trim() || undefined,
                    embed: true,
                }),
            });
            if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);
            this.sourceImportTitle = '';
            this.sourceImportContent = '';
            this.showSourceImport = false;
            await this.loadSources();
        } catch (e) {
            this.error = `Failed to import text: ${e.message}`;
        } finally {
            this.sourceImportLoading = false;
        }
    },

    async addSourceFile(file) {
        if (!this.selectedNotebookId || !file) return;
        this.sourceImportLoading = true;
        this.error = null;
        try {
            const formData = new FormData();
            formData.append('type', 'upload');
            formData.append('notebook_id', this.selectedNotebookId);
            formData.append('file', file);
            if (this.sourceImportTitle?.trim()) {
                formData.append('title', this.sourceImportTitle.trim());
            }
            formData.append('embed', 'true');
            const resp = await smartFetch(`/api/sources`, {
                method: 'POST',
                body: formData,
            });
            if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);
            this.sourceImportTitle = '';
            this.showSourceImport = false;
            await this.loadSources();
        } catch (e) {
            this._pendingFile = null;
            this.error = `Failed to upload file: ${e.message}`;
        } finally {
            this.sourceImportLoading = false;
        }
    },

    // ── Related Sources (notebook-scoped) ──────────────────
    async findRelated(source) {
        const query = source.title || source.name || '';
        if (!query) return;
        this.relatedSourceId = source.id;
        this.relatedLoading = true;
        this.relatedResults = null;
        this.error = null;
        try {
            const resp = await smartFetch(`/api/search`, {
                method: 'POST',
                body: JSON.stringify({
                    query: query,
                    type: 'text',
                    notebook_id: this.selectedNotebookId,
                    search_sources: true,
                    search_notes: false,
                    limit: 6,
                }),
            });
            if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);
            const data = await resp.json();
            const results = (data.sources || data.results || (Array.isArray(data) ? data : [])).filter(
                r => r.id !== source.id
            ).slice(0, 5);
            this.relatedResults = results;
        } catch (e) {
            this.error = `Related search failed: ${e.message}`;
            this.relatedResults = [];
        } finally {
            this.relatedLoading = false;
        }
    },

    clearRelated() {
        this.relatedResults = null;
        this.relatedSourceId = null;
        this.relatedLoading = false;
    },
    async deleteSource(sourceId) {
        try {
            const resp = await smartFetch(`/api/sources/${encodeURIComponent(sourceId)}`, {
                method: 'DELETE'
            });
            if (!resp.ok) throw new Error('Failed to delete source');
            this.sources = this.sources.filter(s => s.id !== sourceId);
        } catch (e) {
            this.error = e.message;
        }
    },

    // ── Source Insights ───────────────────────────────────
    async getSourceInsights(sourceId) {
        if (!this.selectedTransformationId) {
            this.error = 'Please select a transformation first.';
            return;
        }
        this.loading = true;
        this.error = null;
        this.activeInsightSourceId = sourceId;
        this.sourceInsights = [];
        try {
            // First, try to get existing insights
            let getResp = await smartFetch('/api/sources/' + sourceId + '/insights');
            if (getResp.ok) {
                const existing = await getResp.json();
                if (Array.isArray(existing) && existing.length > 0) {
                    this.sourceInsights = existing;
                    this.showSourceInsights = true;
                    this.loading = false;
                    return;
                }
            }
            // No existing insights — generate new ones
            const postResp = await smartFetch('/api/sources/' + sourceId + '/insights', {
                method: 'POST',
                body: JSON.stringify({ transformation_id: this.selectedTransformationId })
            });
            if (!postResp.ok) {
                const errText = await postResp.text();
                throw new Error('Failed to generate insights: ' + errText);
            }
            // API returns 202 (async) — poll GET until insights appear
            const maxAttempts = 30;
            const delay = 2000;
            for (let i = 0; i < maxAttempts; i++) {
                await new Promise(r => setTimeout(r, delay));
                const pollResp = await smartFetch('/api/sources/' + sourceId + '/insights');
                if (pollResp.ok) {
                    const data = await pollResp.json();
                    if (Array.isArray(data) && data.length > 0) {
                        this.sourceInsights = data;
                        break;
                    }
                }
            }
            this.showSourceInsights = true;
        } catch (e) {
            this.error = e.message;
            this.sourceInsights = [];
        } finally {
            this.loading = false;
        }
    },

    async saveInsightAsNote(insightId) {
        try {
            const resp = await smartFetch('/api/insights/' + insightId + '/save-as-note', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ notebook_id: this.selectedNotebook?.id || '' }),
            });
            if (!resp.ok) throw new Error('Failed to save insight as note');
            await this.loadNotes();
            this.showSourceInsights = false;
        } catch (e) {
            this.error = e.message;
        }
    },

    async deleteInsight(insightId) {
        try {
            const resp = await smartFetch('/api/insights/' + encodeURIComponent(insightId), {
                method: 'DELETE'
            });
            if (!resp.ok) throw new Error('Failed to delete insight');
            // Remove from local array
            this.sourceInsights = this.sourceInsights.filter(i => i.id !== insightId);
        } catch (e) {
            this.error = e.message;
        }
    },

    async loadTransformations() {
        try {
            const resp = await smartFetch('/api/transformations');
            if (!resp.ok) throw new Error('Failed to load transformations');
            const transforms = await resp.json();
            this.transformations = transforms;
            const defaultTransform = transforms.find(t => t.apply_default);
            if (defaultTransform) this.selectedTransformationId = defaultTransform.id;
            else if (transforms.length) this.selectedTransformationId = transforms[0].id;
        } catch (e) {
            this.error = 'Failed to load transformations: ' + e.message;
            this.transformations = [];
        }
    },

    // ── Source Health (Status + Retry) ──────────────────────
    async getSourceStatus(sourceId) {
        try {
            const resp = await smartFetch('/api/sources/' + sourceId + '/status');
            if (!resp.ok) throw new Error('Failed to get status');
            return await resp.json();
        } catch (e) {
            this.error = e.message;
            return null;
        }
    },

    async retrySource(sourceId) {
        try {
            const resp = await smartFetch('/api/sources/' + sourceId + '/retry', {
                method: 'POST'
            });
            if (!resp.ok) throw new Error('Failed to retry source');
            await this.loadSources();
        } catch (e) {
            this.error = e.message;
        }
    },


    // ── Notebook Chat (session-based) ──────────────────────
    async loadChatSessions() {
        if (!this.selectedNotebookId) return;
        try {
            const resp = await smartFetch(`/api/chat/sessions?notebook_id=${encodeURIComponent(this.selectedNotebookId)}`);
            if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);
            this.chatSessions = await resp.json();
        } catch (e) {
            console.warn('[OpenNotebook] Load chat sessions failed:', e.message);
            this.chatSessions = [];
        }
    },

    async createChatSession() {
        if (!this.selectedNotebookId) return;
        this.chatLoading = true;
        this.error = null;
        try {
            const resp = await smartFetch(`/api/chat/sessions`, {
                method: 'POST',
                body: JSON.stringify({
                    notebook_id: this.selectedNotebookId,
                    title: 'Plugin Chat',
                }),
            });
            if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);
            const session = await resp.json();
            this.chatSessionId = session.id;
            this.chatMessages = [];
            await this.buildChatContext();
            await this.loadChatSessions();
        } catch (e) {
            this.error = `Failed to create chat session: ${e.message}`;
        } finally {
            this.chatLoading = false;
        }
    },

    async buildChatContext() {
        if (!this.selectedNotebookId) return;
        try {
            const resp = await smartFetch(`/api/chat/context`, {
                method: 'POST',
                body: JSON.stringify({
                    notebook_id: this.selectedNotebookId,
                    context_config: {},
                }),
            });
            if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);
            const data = await resp.json();
            this.chatContext = data.context;
        } catch (e) {
            console.warn('[OpenNotebook] Build context failed:', e.message);
            this.chatContext = {};
        }
    },

    async sendChatMessage() {
        if (!this.chatInput?.trim()) return;

        // Auto-create session if none exists
        if (!this.chatSessionId) {
            await this.createChatSession();
            if (!this.chatSessionId) return;
        }

        const userMsg = this.chatInput.trim();
        this.chatInput = '';
        this.chatMessages.push({ type: 'human', content: userMsg });
        this._scrollChatBottom();
        this.chatLoading = true;
        this.error = null;

        try {
            // Build fresh context each message
            await this.buildChatContext();

            const resp = await smartFetch(`/api/chat/execute`, {
                method: 'POST',
                body: JSON.stringify({
                    session_id: this.chatSessionId,
                    message: userMsg,
                    context: this.chatContext || {},
                }),
            });
            if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);
            const data = await resp.json();
            // Update messages from response (includes full history)
            this.chatMessages = data.messages || this.chatMessages;
            this._scrollChatBottom();
        } catch (e) {
            this.error = `Chat failed: ${e.message}`;
        } finally {
            this.chatLoading = false;
        }
    },

    async loadChatSessionMessages(sessionId) {
        this.chatLoading = true;
        this.error = null;
        try {
            const resp = await smartFetch(`/api/chat/sessions/${encodeURIComponent(sessionId)}`);
            if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);
            const data = await resp.json();
            this.chatSessionId = data.id;
            this.chatMessages = data.messages || [];
            this._scrollChatBottom();
            await this.buildChatContext();
        } catch (e) {
            this.error = `Failed to load session: ${e.message}`;
        } finally {
            this.chatLoading = false;
        }
    },
    async renameChatSession(sessionId, newTitle) {
        try {
            const resp = await smartFetch(`/api/chat/sessions/${encodeURIComponent(sessionId)}`, {
                method: 'PUT',
                body: JSON.stringify({ title: newTitle })
            });
            if (!resp.ok) throw new Error('Failed to rename session');
            await this.loadChatSessions();
        } catch (e) {
            this.error = e.message;
        }
    },

    async deleteChatSession(sessionId) {
        try {
            const resp = await smartFetch(`/api/chat/sessions/${encodeURIComponent(sessionId)}`, {
                method: 'DELETE'
            });
            if (!resp.ok) throw new Error('Failed to delete session');
            this.chatSessions = this.chatSessions.filter(s => s.id !== sessionId);
            if (this.chatSessionId === sessionId) {
                this.chatSessionId = null;
                this.chatMessages = [];
            }
        } catch (e) {
            this.error = e.message;
        }
    },


    resetChat() {
        this.chatSessionId = null;
        this.chatMessages = [];
        this.chatInput = '';
        this.chatLoading = false;
        this.chatSessions = [];
        this.chatContext = null;
        this.sourceChatSessionId = null;
        this.sourceChatMessages = [];
        this.sourceChatInput = '';
        this.sourceChatLoading = false;
        this.activeSourceChatId = null;
    },

    newChat() {
        this.chatSessionId = null;
        this.chatMessages = [];
        this.chatInput = '';
        this.chatContext = null;
    },

    // ── Source Chat ────────────────────────────────────────
    async openSourceChat(sourceId) {
        this.activeSourceChatId = sourceId;
        this.sourceChatMessages = [];
        this.sourceChatSessionId = null;
        this.sourceChatInput = '';
        // Load existing messages for this source
        try {
            const resp = await smartFetch(`/api/sources/${encodeURIComponent(sourceId)}/chat/sessions`);
            if (resp.ok) {
                const sessions = await resp.json();
                if (Array.isArray(sessions) && sessions.length > 0) {
                    const latest = sessions[sessions.length - 1];
                    this.sourceChatSessionId = latest.id;
                    const detailResp = await smartFetch(`/api/sources/${encodeURIComponent(sourceId)}/chat/sessions/${encodeURIComponent(latest.id)}`);
                    if (detailResp.ok) {
                        const data = await detailResp.json();
                        this.sourceChatMessages = data.messages || [];
                    }
                }
            }
        } catch (e) { /* no existing sessions, start fresh */ }
    },

    closeSourceChat() {
        this.activeSourceChatId = null;
        this.sourceChatMessages = [];
        this.sourceChatSessionId = null;
        this.sourceChatInput = '';
    },

    async sendSourceChatMessage() {
        if (!this.sourceChatInput?.trim() || !this.activeSourceChatId) return;

        const sourceId = this.activeSourceChatId;
        const userMsg = this.sourceChatInput.trim();
        this.sourceChatInput = '';
        this.sourceChatMessages.push({ type: 'human', content: userMsg });
        this._scrollSourceChatBottom();
        this.sourceChatLoading = true;
        this.error = null;

        try {
            // Create source chat session if needed
            if (!this.sourceChatSessionId) {
                const createResp = await smartFetch(`/api/sources/${encodeURIComponent(sourceId)}/chat/sessions`, {
                    method: 'POST',
                    body: JSON.stringify({ source_id: sourceId, title: 'Plugin Source Chat' }),
                });
                if (!createResp.ok) throw new Error(`HTTP ${createResp.status}: ${createResp.statusText}`);
                const session = await createResp.json();
                this.sourceChatSessionId = session.id;
            }

            // Send user message (returns SSE stream)
            const sendResp = await smartFetch(`/api/sources/${encodeURIComponent(sourceId)}/chat/sessions/${encodeURIComponent(this.sourceChatSessionId)}/messages`, {
                method: 'POST',
                body: JSON.stringify({ message: userMsg }),
            });
            if (!sendResp.ok) throw new Error(`Send failed: HTTP ${sendResp.status}`);

            // Parse SSE response
            const text = await sendResp.text();
            let aiContent = '';
            const messages = [];
            const lines = text.split(String.fromCharCode(10));
            for (const line of lines) {
                if (line.startsWith('data: ')) {
                    try {
                        const evt = JSON.parse(line.slice(6));
                        if (evt.type === 'user_message') {
                            messages.push({ type: 'human', content: evt.content });
                        } else if (evt.type === 'ai_message') {
                            aiContent += evt.content || '';
                        } else if (evt.type === 'complete') {
                            if (aiContent) messages.push({ type: 'ai', content: aiContent });
                        }
                    } catch (e) { /* skip */ }
                }
            }
            if (messages.length > 0) {
                this.sourceChatMessages = messages;
            } else {
                this.error = 'No response received from source chat. Please try again.';
            }
            this._scrollSourceChatBottom();
        } catch (e) {
            this.error = `Source chat failed: ${e.message}`;
        } finally {
            this.sourceChatLoading = false;
        }
    },

    // ── Notes ──────────────────────────────────────────────
    async loadNotes() {
        if (!this.selectedNotebookId) return;
        this.loading = true;
        this.error = null;
        try {
            const params = new URLSearchParams({
                notebook_id: this.selectedNotebookId
            });
            const resp = await smartFetch(`/api/notes?${params}`);
            if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);
            const notesList = await resp.json();
            // Fetch full content for each note (list endpoint omits content)
            this.notes = await Promise.all(notesList.map(async (note) => {
                try {
                    const detailResp = await smartFetch(`/api/notes/${encodeURIComponent(note.id)}`);
                    if (detailResp.ok) return await detailResp.json();
                } catch (e) {
                    console.warn('[OpenNotebook] Failed to load note detail:', note.id, e);
                }
                return note;
            }));
        } catch (e) {
            this.error = `Failed to load notes: ${e.message}`;
            this.notes = [];
        } finally {
            this.loading = false;
        }
    },

    async createNote(title, content) {
        if (!this.selectedNotebookId) {
            this.error = 'Select a notebook first to create a note.';
            return;
        }
        if (!title?.trim()) return;
        this.savingNote = true;
        this.error = null;
        try {
            const body = {
                notebook_id: this.selectedNotebookId,
                content: content?.trim() || '',
                note_type: 'human',
            };
            if (title.trim()) {
                body.title = title.trim();
            }
            console.log('[OpenNotebook] Creating note:', JSON.stringify(body));
            const resp = await smartFetch(`/api/notes`, {
                method: 'POST',
                body: JSON.stringify(body),
            });
            if (!resp.ok) {
                const errText = await resp.text();
                console.error('[OpenNotebook] Note error:', resp.status, errText);
                throw new Error(`HTTP ${resp.status}: ${errText}`);
            }
            this.newNoteTitle = '';
            this.newNoteContent = '';
            await this.loadNotes();
        } catch (e) {
            this.error = `Failed to create note: ${e.message}`;
        } finally {
            this.savingNote = false;
        }
    },
    async updateNote(noteId, updates) {
        try {
            const resp = await smartFetch('/api/notes/' + encodeURIComponent(noteId), {
                method: 'PUT',
                body: JSON.stringify(updates)
            });
            if (!resp.ok) throw new Error('Failed to update note');
            await this.loadNotes();
        } catch (e) {
            this.error = e.message;
        }
    },

    async deleteNote(noteId) {
        try {
            const resp = await smartFetch('/api/notes/' + encodeURIComponent(noteId), {
                method: 'DELETE'
            });
            if (!resp.ok) throw new Error('Failed to delete note');
            this.notes = this.notes.filter(n => n.id !== noteId);
        } catch (e) {
            this.error = e.message;
        }
    },


    // ── Podcasts ───────────────────────────────────────────
    async loadEpisodes() {
        this.loading = true;
        this.error = null;
        try {
            const resp = await smartFetch(`/api/podcasts/episodes`);
            if (!resp.ok) throw new Error(`HTTP ${resp.status}: ${resp.statusText}`);
            this.episodes = await resp.json();
        } catch (e) {
            this.error = `Failed to load episodes: ${e.message}`;
            this.episodes = [];
        } finally {
            this.loading = false;
        }
    },

    // ── Podcast Generation ───────────────────────────────
    async loadPodcastProfiles() {
        this.loading = true;
        this.error = null;
        try {
            const [epResp, spResp] = await Promise.all([
                smartFetch(`/api/episode-profiles`),
                smartFetch(`/api/speaker-profiles`),
            ]);
            if (!epResp.ok) throw new Error(`Episode profiles: HTTP ${epResp.status}`);
            if (!spResp.ok) throw new Error(`Speaker profiles: HTTP ${spResp.status}`);
            const epProfiles = await epResp.json();
            this.episodeProfiles = epProfiles;
            if (epProfiles.length && !this.generateForm.episode_profile) this.generateForm.episode_profile = epProfiles[0].name;
            const spProfiles = (await spResp.json()).filter(p => p.name !== 'solo_expert');
            this.speakerProfiles = spProfiles;
            if (spProfiles.length && !this.generateForm.speaker_profile) this.generateForm.speaker_profile = spProfiles[0].name;
        } catch (e) {
            this.error = `Failed to load podcast profiles: ${e.message}`;
            this.episodeProfiles = [];
            this.speakerProfiles = [];
        } finally {
            this.loading = false;
        }
    },

    async generatePodcast() {
        if (!this.selectedNotebookId) return;
        if (!this.generateForm.episode_name?.trim()) {
            this.error = 'Episode name is required.';
            return;
        }
        if (!this.generateForm.episode_profile) {
            this.error = 'Please select an episode profile.';
            return;
        }
        if (!this.generateForm.speaker_profile) {
            this.error = 'Please select a speaker profile.';
            return;
        }
        this.generatingJob = { status: 'pending' };
        this.error = null;
        try {
            const body = {
                episode_profile: this.generateForm.episode_profile || undefined,
                speaker_profile: this.generateForm.speaker_profile || undefined,
                episode_name: this.generateForm.episode_name.trim(),
                notebook_id: this.selectedNotebookId,
            };
            if (this.generateForm.content?.trim()) {
                body.content = this.generateForm.content.trim();
            }
            console.log('[OpenNotebook] Generating podcast:', JSON.stringify(body));
            const resp = await smartFetch(`/api/podcasts/generate`, {
                method: 'POST',
                body: JSON.stringify(body),
            });
            if (!resp.ok) {
                const errText = await resp.text();
                console.error('[OpenNotebook] Podcast error:', resp.status, errText);
                throw new Error(`HTTP ${resp.status}: ${errText}`);
            }
            const data = await resp.json();
            this.generatingJob = { job_id: data.job_id || data.id, status: data.status || 'running', message: data.message || '' };
            this.showGenerateForm = false;
            this.generateForm = {
                episode_name: '',
                episode_profile: '',
                speaker_profile: '',
                content: ''
            };
            this.pollJobStatus(data.job_id || data.id);
        } catch (e) {
            this.error = `Failed to generate podcast: ${e.message}`;
            this.generatingJob = null;
        }
    },

    async pollJobStatus(jobId) {
        if (!jobId) return;
        const poll = async () => {
            try {
                const resp = await smartFetch(`/api/podcasts/jobs/${encodeURIComponent(jobId)}`);
                if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
                const data = await resp.json();
                this.generatingJob = data;
                if (data.status === 'running' || data.status === 'pending') {
                    setTimeout(poll, 5000);
                } else {
                    // Job completed or failed
                    await this.loadEpisodes();
                    if (data.status === 'completed') {
                        this.generatingJob = null;
                    }
                }
            } catch (e) {
                console.warn('[OpenNotebook] Poll failed:', e.message);
                this.generatingJob = { ...this.generatingJob, status: 'error', message: e.message };
            }
        };
        await poll();
    },

    // ── Send to Agent Zero Chat ────────────────────────────
    sendToChat(text, sources) {
        let msg = text || '';
        if (sources && sources.length > 0) {
            msg += '\n\n**Sources:**';
            for (const s of sources.slice(0, 5)) {
                const title = s.title || s.name || 'Source';
                const score = s.score ? ` (${Math.round(s.score * 100)}%)` : '';
                msg += `\n- ${title}${score}`;
            }
        }
        // For large content, attach as a file instead of pasting into input
        if (msg.length > 2000) {
            this._sendAsFile(msg);
            return;
        }
        // Small content: directly update the DOM textarea
        const inputStore = Alpine.store('inputStore');
        if (inputStore) inputStore.message = msg;
        const chatInput = document.getElementById('chat-input');
        if (chatInput) {
            chatInput.value = msg;
            chatInput.dispatchEvent(new Event('input', { bubbles: true }));
            chatInput.focus();
            chatInput.style.height = 'auto';
            chatInput.style.height = chatInput.scrollHeight + 'px';
        }
    },

    _sendAsFile(content) {
        // Generate filename from first heading or timestamp
        const headingMatch = content.match(/\*\*(.+?)\*\*/);
        const baseName = headingMatch ? headingMatch[1].replace(/[^a-zA-Z0-9_-]/g, '_').substring(0, 40) : 'content';
        const timestamp = new Date().toISOString().slice(0,16).replace(/[:-]/g, '');
        const filename = `${baseName}_${timestamp}.md`;

        // Create a File object from the content
        const blob = new Blob([content], { type: 'text/markdown' });
        const file = new File([blob], filename, { type: 'text/markdown', lastModified: Date.now() });

        // Try to access attachmentsStore
        const attachStore = Alpine.store('chatAttachments');
        if (attachStore && attachStore.addAttachment) {
            attachStore.addAttachment({
                file: file,
                type: 'file',
                name: filename,
                extension: 'md',
                displayInfo: { name: filename, size: file.size }
            });
            this._showToast('📎 Attached as file', filename);
            // Add a prompt message in the chat input
            const chatInput = document.getElementById('chat-input');
            if (chatInput) {
                chatInput.value = 'Review the attached file: ';
                chatInput.dispatchEvent(new Event('input', { bubbles: true }));
                chatInput.focus();
            }
        } else {
            // Fallback: write to uploads dir and put path in chat
            console.warn('[OpenNotebook] chatAttachments store not found, using textarea fallback');
            const chatInput = document.getElementById('chat-input');
            if (chatInput) {
                chatInput.value = content;
                chatInput.dispatchEvent(new Event('input', { bubbles: true }));
                chatInput.focus();
                chatInput.style.height = 'auto';
                chatInput.style.height = chatInput.scrollHeight + 'px';
            }
        }
    },

    _showToast(title, message) {
        const toast = document.getElementById('toast');
        if (toast) {
            const titleEl = toast.querySelector('.toast__title');
            const msgEl = toast.querySelector('.toast__message');
            if (titleEl) titleEl.textContent = title || '';
            if (msgEl) msgEl.textContent = message || '';
            toast.classList.add('show');
            setTimeout(() => toast.classList.remove('show'), 3000);
        }
    },

    // ── Content → Agent Zero Chat ─────────────────────────
    async sendSourceToChat(sourceId) {
        try {
            const resp = await smartFetch(`/api/sources/${sourceId}`);
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const src = await resp.json();
            console.log('SendToChat Source:', src);
            const title = (src.title || 'Untitled Source').replace(/_/g, ' ').replace(/\s+/g, ' ').trim();
            const content = src.full_text || src.content || src.text || '';
            if (!content) { this.error = 'Source has no full_text/content.'; return; }
            this.sendToChat(`**📄 ${title}**\n\n${content}`, []);
            this._showToast('📄 Sent to chat', title);
        } catch (e) {
            this.error = `Failed to load source: ${e.message}`;
        }
    },

    async sendNoteToChat(noteId) {
        try {
            const resp = await smartFetch(`/api/notes/${noteId}`);
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const note = await resp.json();
            console.log('SendToChat Note:', note);
            const title = note.title || 'Untitled Note';
            const content = note.content || note.text || '';
            if (!content) { this.error = 'Note has no content.'; return; }
            this.sendToChat(`**📝 ${title}**\n\n${content}`, []);
            this._showToast('📝 Sent to chat', title);
        } catch (e) {
            this.error = `Failed to load note: ${e.message}`;
        }
    },

    async sendPodcastToChat(episodeId) {
        try {
            const resp = await smartFetch(`/api/podcasts/episodes/${episodeId}`);
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const ep = await resp.json();
            console.log('SendToChat Episode:', ep);
            const name = ep.name || 'Untitled Episode';
            let summary = '', briefing = '', transcript = '';

            // Fetch full generation result from the job endpoint
            const jobId = ep.command ? (typeof ep.command === 'object' ? ep.command.id : ep.command) : null;
            if (jobId) {
                try {
                    const jobResp = await smartFetch(`/api/podcasts/jobs/${jobId}`);
                    if (jobResp.ok) {
                        const job = await jobResp.json();
                        const res = job.result || {};
                        summary = res.summary || '';
                        briefing = res.briefing || '';
                        const rawT = res.transcript;
                        if (typeof rawT === 'string') transcript = rawT;
                        else if (Array.isArray(rawT)) transcript = rawT.map(s => s.text || s.content || '').filter(Boolean).join('\n');
                        else if (rawT?.text) transcript = rawT.text;
                    }
                } catch (e) { console.warn('Job fetch failed:', e); }
            }

            // Fallbacks
            if (!briefing && ep.briefing) briefing = ep.briefing;
            if (!transcript) {
                let rawT = ep.transcript;
                // Unwrap double-nesting: episode.transcript = { "transcript": { ... } }
                if (rawT && typeof rawT === 'object' && rawT.transcript) {
                    rawT = rawT.transcript;
                }
                
                if (typeof rawT === 'string') {
                    transcript = rawT;
                } else if (Array.isArray(rawT)) {
                    // Debug: Show the first segment structure in console
                    if (rawT.length > 0) console.log('Debug Transcript Segment[0]:', rawT[0]);
                    // Aggressively extract text from all segments using common keys
                    transcript = rawT.map(s => s.text || s.content || s.line || s.dialogue || s.sentence || s.transcript || JSON.stringify(s)).filter(Boolean).join('\n');
                } else if (rawT && typeof rawT === 'object') {
                    if (rawT.text) {
                        transcript = rawT.text;
                    } else if (Array.isArray(rawT.segments)) {
                        transcript = rawT.segments.map(s => s.text || s.content || '').filter(Boolean).join('\n');
                    } else {
                        // Last resort: Join all string values in the object
                        transcript = Object.values(rawT).filter(v => typeof v === 'string').join('\n');
                    }
                }
            }

            if (!transcript && !briefing) { this.error = 'No podcast transcript/briefing available.'; return; }

            let msg = `**🎙️ ${name}**\n`;
            if (summary) msg += `\n📝 **Summary:**\n${summary}\n`;
            if (briefing) msg += `\n📋 **Briefing:**\n${briefing}\n`;
            if (transcript) msg += `\n📄 **Transcript:**\n${transcript}`;
            
            this.sendToChat(msg, []);
            this._showToast('🎙️ Sent to chat', name);
        } catch (e) {
            this.error = `Failed to load episode: ${e.message}`;
        }
    },

    sendChatMsgToChat(content) {
        if (!content) return;
        this.sendToChat(content, []);
        this._showToast('💬 Sent to chat', 'AI response');
    },

    async saveChatReplyAsNote(content) {
        if (!this.selectedNotebookId) {
            this.error = 'Select a notebook first to save as note.';
            return;
        }
        if (!content) return;
        try {
            const title = 'Chat Reply ' + new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
            const body = {
                notebook_id: this.selectedNotebookId,
                content: content,
                note_type: 'ai',
                title: title
            };
            console.log('[OpenNotebook] Saving chat reply as note:', title);
            const resp = await smartFetch(`/api/notes`, {
                method: 'POST',
                body: JSON.stringify(body),
            });
            if (!resp.ok) {
                const errText = await resp.text();
                console.error('[OpenNotebook] Save note error:', resp.status, errText);
                throw new Error(`HTTP ${resp.status}: ${errText}`);
            }
            if (this.activeTab === 'notes') await this.loadNotes();
            this._showToast('💾 Saved to notes', title);
        } catch (e) {
            this.error = `Failed to save note: ${e.message}`;
        }
    },

    // ── Audio Player ───────────────────────────────────────
    async playAudio(episodeId) {
        const player = document.getElementById('on-audio-player');
        if (!player) return;

        if (this.currentEpisodeId === episodeId && this.isPlaying) {
            player.pause();
            this.isPlaying = false;
        } else {
            if (this.currentEpisodeId !== episodeId) {
                this.currentEpisodeId = episodeId;
                player.src = await getAudioUrl(`/api/podcasts/episodes/${encodeURIComponent(episodeId)}/audio`);
            }
            player.play().catch((e) => {
                this.error = `Audio playback failed: ${e.message}`;
                this.isPlaying = false;
            });
            this.isPlaying = true;
        }
    },

    async deleteEpisode(episodeId) {
        try {
            const resp = await smartFetch('/api/podcasts/episodes/' + episodeId, {
                method: 'DELETE'
            });
            if (!resp.ok) throw new Error('Failed to delete episode');
            this.episodes = this.episodes.filter(e => e.id !== episodeId);
            if (this.currentEpisodeId === episodeId) {
                this.currentEpisodeId = null;
                this.isPlaying = false;
            }
        } catch (e) {
            this.error = e.message;
        }
    },




    // ── Refresh ────────────────────────────────────────────
    async refreshCurrentTab() {
        if (!this.selectedNotebookId) return;
        const tab = this.activeTab;
        if (tab === 'sources') await this.loadSources();
        else if (tab === 'notes') await this.loadNotes();
        else if (tab === 'podcasts') await this.loadEpisodes();
        else if (tab === 'chat') await this.loadChatSessions();
    },

    // ── Resize ───────────────────────────────────────────
    startDrag(e) {
        this.isDragging = true;
        const startX = e.clientX || e.touches?.[0]?.clientX;
        const startWidth = this.panelWidth;
        const minW = this._minWidth;
        const maxW = this._maxWidth;

        const onMove = (ev) => {
            const clientX = ev.clientX || ev.touches?.[0]?.clientX;
            const delta = startX - clientX;
            const newWidth = Math.min(maxW, Math.max(minW, startWidth + delta));
            this.panelWidth = newWidth;
        };

        const onUp = () => {
            this.isDragging = false;
            document.removeEventListener('mousemove', onMove);
            document.removeEventListener('mouseup', onUp);
            document.removeEventListener('touchmove', onMove);
            document.removeEventListener('touchend', onUp);
            document.body.style.userSelect = '';
            document.body.style.cursor = '';
        };

        document.body.style.userSelect = 'none';
        document.body.style.cursor = 'col-resize';
        document.addEventListener('mousemove', onMove);
        document.addEventListener('mouseup', onUp);
        document.addEventListener('touchmove', onMove, { passive: true });
        document.addEventListener('touchend', onUp);
    },

    resetWidth() {
        this.panelWidth = 420;
    },
    // ── Copy Message to Clipboard ──────────────────────
    async copyMessage(text) {
        try {
            await navigator.clipboard.writeText(text);
        } catch(e) {
            const ta = document.createElement('textarea');
            ta.value = text;
            document.body.appendChild(ta);
            ta.select();
            document.execCommand('copy');
            document.body.removeChild(ta);
        }
    },

    // ── Auto-scroll helpers ──────────────────────────────
    _scrollChatBottom() {
        setTimeout(() => {
            const el = document.querySelector('.on-tab-pane--chat .on-chat-messages');
            if (el) el.scrollTop = el.scrollHeight;
        }, 50);
    },

    _scrollSourceChatBottom() {
        setTimeout(() => {
            const el = document.querySelector('.on-source-chat .on-chat-messages');
            if (el) el.scrollTop = el.scrollHeight;
        }, 50);
    },
    
    // ── Canvas Integration ───────────────────────────────
    _isCanvasHosting: false,
    _canvasStore: null,
    
    get isCanvasHosting() {
        return this._isCanvasHosting;
    },
    
    openViaCanvas() {
        // Get canvas store directly at call time (avoids timing issues)
        const canvas = window.Alpine?.store?.('rightCanvas');
        if (canvas && canvas.open) {
            canvas.open('open-notebook');
        }
    },
    
    closeViaCanvas() {
        // Get canvas store directly at call time (avoids timing issues)
        const canvas = window.Alpine?.store?.('rightCanvas');
        if (canvas && canvas.close) {
            canvas.close();
        }
    }
};

console.log('[OpenNotebook] Creating store...');
export const store = createStore('openNotebookStore', model);
console.log('[OpenNotebook] Store registered:', !!globalThis.Alpine?.store('openNotebookStore'));

document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
        const s = globalThis.Alpine?.store('openNotebookStore');
        if (s && s.isOpen) s.closePanel();
    }
});
