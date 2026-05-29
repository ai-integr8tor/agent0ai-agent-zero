// Open Notebook Canvas Surface Registration
export default async function registerOpenNotebookSurface(canvas) {
    // Helper to get store (may not exist yet at registration time)
    function getStore() {
        return window.Alpine.store('openNotebookStore');
    }

    // Try to save canvas reference immediately, or poll until store is ready
    function saveCanvasRef() {
        const s = getStore();
        if (s) {
            s._canvasStore = canvas;
            return true;
        }
        return false;
    }

    // Try immediately
    if (!saveCanvasRef()) {
        // Store not ready yet - poll for it
        const interval = setInterval(() => {
            if (saveCanvasRef()) {
                clearInterval(interval);
            }
        }, 100);
        // Safety: stop polling after 10s
        setTimeout(() => clearInterval(interval), 10000);
    }

    canvas.registerSurface({
        id: 'open-notebook',
        title: 'Open Notebook',
        icon: 'menu_book',
        order: 50,
        modalPath: '/plugins/open-notebook/webui/canvas-panel.html?v=20260529',
        async open(payload = {}) {
            const s = getStore();
            if (s) {
                s._canvasStore = canvas;
                s.isOpen = true;
                s._isCanvasHosting = true;
                if (!s.notebooks || s.notebooks.length === 0) {
                    await s.loadNotebooks();
                }
                s.loadTransformations();
            }
        },
        async close(payload = {}) {
            const s = getStore();
            if (s) {
                s.isOpen = false;
                s.error = null;
            }
        },
        actionOnly: false,
    });
    console.log('[Open Notebook] Registered as Canvas surface');
}
