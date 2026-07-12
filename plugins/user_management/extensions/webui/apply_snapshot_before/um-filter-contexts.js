/**
 * Before each snapshot is applied, filter contexts by ownership.
 *
 * IMPORTANT: If the um-store has not yet finished initializing,
 * we hide ALL contexts to prevent non-admin users from briefly
 * seeing other users' chats. Once init completes,
 * _reapplyContextFilter() in um-store.js will show the correct ones.
 */
export default function umFilterContextsBeforeSnapshot(ctx) {
    const store = globalThis.Alpine?.store?.("umUser");
    if (!store) return;

    const snapshot = ctx?.snapshot;
    if (!snapshot || !Array.isArray(snapshot.contexts)) return;

    // If store has not finished initializing yet, hide all contexts.
    // This prevents the flash of all chats before ownership is known.
    // The correct contexts will appear after init + _reapplyContextFilter.
    if (!store._initialized) {
        snapshot.contexts = [];
        return;
    }

    // Not logged in via plugin (shouldn't happen with unified login)
    if (!store.isLoggedIn) return;

    // Admins see everything
    if (store.currentUser && store.currentUser.role === "admin") return;

    // Non-admin: filter to only owned contexts
    if (store.ownedContextIds instanceof Set) {
        const chatsStore = globalThis.Alpine?.store?.("chats");
        const selectedId = chatsStore?.selected;

        snapshot.contexts = snapshot.contexts.filter(
            (ctx) =>
                store.ownedContextIds.has(ctx.id) ||
                (selectedId && ctx.id === selectedId)
        );
    }
}
