function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, character => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
    })[character]);
}

function formatUsageSeconds(seconds) {
    const minutes = Math.floor(seconds / 60);
    const remainder = seconds % 60;
    if (!minutes && remainder) return `${remainder} giây`;
    return remainder ? `${minutes} phút ${remainder} giây` : `${minutes} phút`;
}
