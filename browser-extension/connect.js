// Run only on the child dashboard. The page performs its own authenticated token refresh.
window.addEventListener("mmt-web-connect", async event => {
    if (document.documentElement.dataset.mmtDashboard !== "child") return;
    try {
        const response = await chrome.runtime.sendMessage({
            type: "connect",
            origin: location.origin,
            token: event.detail.token,
            targets: event.detail.targets,
            blocked: event.detail.blocked
        });
        if (response?.connected) document.documentElement.dataset.mmtWebTracking = "connected";
        else delete document.documentElement.dataset.mmtWebTracking;
    } catch (error) {
        delete document.documentElement.dataset.mmtWebTracking;
    }
});
