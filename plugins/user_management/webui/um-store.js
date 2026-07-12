import { createStore } from "/js/AlpineStore.js";
import { callJsonApi } from "/js/api.js";
import {
    toastFrontendError,
    toastFrontendSuccess,
} from "/components/notifications/notification-store.js";

const model = {
    currentUser: null,
    isLoggedIn: false,
    ownedContextIds: null, // null = not loaded, Set = loaded
    _initialized: false,
    _patched: false,
    _chatHooked: false,

    async init() {
        if (this._initialized) return;
        this._initialized = true;
        await this.checkLoginStatus();
        if (this.isLoggedIn) {
            await this.loadOwnedContexts();
            this._patchApplyContexts();
            this._hookNewChat();
            // Force re-apply of current snapshot so filter catches existing contexts
            this._reapplyContextFilter();
        }
    },

    async checkLoginStatus() {
        try {
            const res = await callJsonApi("/plugins/user_management/login", {
                action: "status",
            });
            if (res.ok && res.logged_in) {
                this.currentUser = res.user;
                this.isLoggedIn = true;
            } else {
                this.currentUser = null;
                this.isLoggedIn = false;
            }
        } catch (e) {
            // Plugin may not be active or DB not connected
            console.debug("[user_management] status check:", e);
        }
    },

    async login(username, password) {
        try {
            const res = await callJsonApi("/plugins/user_management/login", {
                action: "login",
                username,
                password,
            });
            if (res.ok) {
                this.currentUser = res.user;
                this.isLoggedIn = true;
                toastFrontendSuccess(`Logged in as ${res.user.username}`);
                await this.loadOwnedContexts();
                this._patchApplyContexts();
                this._hookNewChat();
                this._reapplyContextFilter();
                return true;
            }
        } catch (e) {
            toastFrontendError("Login failed: " + (e.message || "Invalid credentials"));
        }
        return false;
    },

    async logout() {
        // Only admins can logout via the UI
        if (!this.isAdmin()) {
            toastFrontendError("Logout is restricted to administrators.");
            return;
        }
        try {
            await callJsonApi("/plugins/user_management/login", {
                action: "logout",
            });
        } catch (e) {
            // ignore
        }
        this.currentUser = null;
        this.isLoggedIn = false;
        this.ownedContextIds = null;
        // Reload page to clear all chat data and show login overlay
        window.location.reload();
    },

    async loadOwnedContexts() {
        // Load the context IDs this user owns for filtering
        try {
            const res = await callJsonApi("/plugins/user_management/login", {
                action: "owned_contexts",
            });
            if (res.ok) {
                if (res.is_admin) {
                    // Admins see everything
                    this.ownedContextIds = null;
                } else if (Array.isArray(res.context_ids)) {
                    this.ownedContextIds = new Set(res.context_ids);
                }
            }
        } catch (e) {
            console.debug("[user_management] failed to load owned contexts:", e);
            this.ownedContextIds = null;
        }
    },

    /**
     * Force re-apply context filtering on already-loaded chat list.
     * Fixes timing issue where first snapshot arrives before init() completes.
     */
    _reapplyContextFilter() {
        if (this.isAdmin()) return; // Admins see everything
        if (!(this.ownedContextIds instanceof Set)) return;

        const chatsStore = globalThis.Alpine?.store?.("chats");
        if (!chatsStore || !chatsStore.contexts) return;

        const selectedId = chatsStore.selected;
        const filtered = chatsStore.contexts.filter(
            (ctx) =>
                this.ownedContextIds.has(ctx.id) ||
                (selectedId && ctx.id === selectedId)
        );
        chatsStore.contexts = filtered;
    },

    // Patch the chats store to filter contexts by ownership
    _patchApplyContexts() {
        if (this._patched) return;
        const chatsStore = globalThis.Alpine?.store?.("chats");
        if (!chatsStore) return;

        const original = chatsStore.applyContexts.bind(chatsStore);
        const self = this;

        chatsStore.applyContexts = function (contextsList) {
            let filtered = contextsList;
            if (self.isLoggedIn && self.currentUser && self.currentUser.role !== "admin") {
                if (self.ownedContextIds instanceof Set) {
                    // Always allow the currently selected context through
                    // so newly created chats remain visible immediately
                    const selectedId = chatsStore.selected;
                    filtered = contextsList.filter(
                        (ctx) =>
                            self.ownedContextIds.has(ctx.id) ||
                            (selectedId && ctx.id === selectedId)
                    );
                }
            }
            original(filtered);
        };

        this._patched = true;
    },

    /**
     * Register a newly created context ID so the ownership Set is
     * immediately up-to-date without waiting for a full DB refresh.
     */
    registerOwnedContext(contextId) {
        if (this.ownedContextIds instanceof Set && contextId) {
            this.ownedContextIds.add(contextId);
        }
    },

    /**
     * Hook into the chats store newChat method to auto-register
     * ownership of chats created while logged in.
     */
    _hookNewChat() {
        if (this._chatHooked) return;
        const chatsStore = globalThis.Alpine?.store?.("chats");
        if (!chatsStore) return;

        const originalNewChat = chatsStore.newChat.bind(chatsStore);
        const self = this;

        chatsStore.newChat = async function () {
            await originalNewChat();
            // After newChat completes, the chats store selected ID
            // is already set to the new context — register it
            const newId = chatsStore.selected;
            if (newId) {
                self.registerOwnedContext(newId);
            }
        };

        this._chatHooked = true;
    },

    isAdmin() {
        return this.currentUser && this.currentUser.role === "admin";
    },
};

export const store = createStore("umUser", model);
