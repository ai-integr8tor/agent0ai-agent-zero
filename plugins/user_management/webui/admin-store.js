import { createStore } from "/js/AlpineStore.js";
import { callJsonApi } from "/js/api.js";
import {
    toastFrontendError,
    toastFrontendSuccess,
} from "/components/notifications/notification-store.js";

const model = {
    // State
    users: [],
    usageData: [],
    usageSummary: [],
    currentUser: null,
    isLoading: false,
    activeTab: "users",

    // Filters
    filterUserId: null,
    filterGroupBy: "day",
    filterFromDate: "",
    filterToDate: "",

    // New user form
    newUsername: "",
    newPassword: "",
    newRole: "user",

    async init() {
        await this.checkStatus();
        await this.loadUsers();
    },

    async checkStatus() {
        try {
            const res = await callJsonApi("/plugins/user_management/login", {
                action: "status",
            });
            if (res.ok && res.logged_in) {
                this.currentUser = res.user;
            }
        } catch (e) {
            console.error("[user_management] status check failed:", e);
        }
    },

    async loadUsers() {
        if (!this.currentUser || this.currentUser.role !== "admin") return;
        try {
            this.isLoading = true;
            const res = await callJsonApi("/plugins/user_management/users", {
                action: "list",
            });
            if (res.ok) {
                this.users = res.users;
            }
        } catch (e) {
            toastFrontendError("Failed to load users");
        } finally {
            this.isLoading = false;
        }
    },

    async createUser() {
        if (!this.newUsername || !this.newPassword) {
            toastFrontendError("Username and password are required");
            return;
        }
        try {
            this.isLoading = true;
            const res = await callJsonApi("/plugins/user_management/users", {
                action: "create",
                username: this.newUsername,
                password: this.newPassword,
                role: this.newRole,
            });
            if (res.ok) {
                toastFrontendSuccess(`User "${this.newUsername}" created`);
                this.newUsername = "";
                this.newPassword = "";
                this.newRole = "user";
                await this.loadUsers();
            }
        } catch (e) {
            toastFrontendError("Failed to create user: " + (e.message || e));
        } finally {
            this.isLoading = false;
        }
    },

    async deleteUser(userId, username) {
        if (!confirm(`Delete user "${username}"? This cannot be undone.`)) return;
        try {
            this.isLoading = true;
            const res = await callJsonApi("/plugins/user_management/users", {
                action: "delete",
                user_id: userId,
            });
            if (res.ok) {
                toastFrontendSuccess(`User "${username}" deleted`);
                await this.loadUsers();
            }
        } catch (e) {
            toastFrontendError("Failed to delete user: " + (e.message || e));
        } finally {
            this.isLoading = false;
        }
    },

    async loadUsage() {
        try {
            this.isLoading = true;
            const params = {
                action: "query",
                limit: 500,
            };
            if (this.filterUserId) params.user_id = this.filterUserId;
            if (this.filterFromDate) params.from_date = this.filterFromDate;
            if (this.filterToDate) params.to_date = this.filterToDate;

            const res = await callJsonApi("/plugins/user_management/usage", params);
            if (res.ok) {
                this.usageData = res.data;
            }
        } catch (e) {
            toastFrontendError("Failed to load usage data");
        } finally {
            this.isLoading = false;
        }
    },

    async loadUsageSummary() {
        try {
            this.isLoading = true;
            const params = {
                action: "summary",
                group_by: this.filterGroupBy,
            };
            if (this.filterUserId) params.user_id = this.filterUserId;
            if (this.filterFromDate) params.from_date = this.filterFromDate;
            if (this.filterToDate) params.to_date = this.filterToDate;

            const res = await callJsonApi("/plugins/user_management/usage", params);
            if (res.ok) {
                this.usageSummary = res.data;
            }
        } catch (e) {
            toastFrontendError("Failed to load usage summary");
        } finally {
            this.isLoading = false;
        }
    },

    async exportExcel() {
        try {
            const params = new URLSearchParams({ action: "export" });
            if (this.filterUserId) params.append("user_id", this.filterUserId);
            if (this.filterFromDate) params.append("from_date", this.filterFromDate);
            if (this.filterToDate) params.append("to_date", this.filterToDate);

            const resp = await fetch("/api/plugins/user_management/usage", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    action: "export",
                    user_id: this.filterUserId || undefined,
                    from_date: this.filterFromDate || undefined,
                    to_date: this.filterToDate || undefined,
                }),
            });

            if (!resp.ok) throw new Error("Export failed");

            const blob = await resp.blob();
            const url = URL.createObjectURL(blob);
            const a = document.createElement("a");
            a.href = url;
            a.download = "token_usage.xlsx";
            a.click();
            URL.revokeObjectURL(url);
            toastFrontendSuccess("Excel exported");
        } catch (e) {
            toastFrontendError("Export failed: " + (e.message || e));
        }
    },

    formatNumber(n) {
        return (n || 0).toLocaleString();
    },
};

export const store = createStore("umAdmin", model);
