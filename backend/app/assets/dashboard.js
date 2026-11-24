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

function usageCategories(data) {
    return [
        { tag: "LEARNING", label: "Học tập", color: "#10b981", seconds: data.learning_seconds ?? (data.learning_minutes || 0) * 60 },
        { tag: "ENTERTAINMENT", label: "Giải trí", color: "#f43f5e", seconds: data.entertainment_seconds ?? (data.entertainment_minutes || 0) * 60 },
        { tag: "SOCIAL", label: "Mạng xã hội", color: "#3b82f6", seconds: data.social_seconds ?? (data.social_minutes || 0) * 60 },
        { tag: "UTILITY", label: "Tiện ích", color: "#d97706", seconds: data.utilities_seconds ?? (data.utilities_minutes || 0) * 60 },
        { tag: "OTHER", label: "Chưa phân loại", color: "#64748b", seconds: data.unclassified_seconds ?? 0 },
        { tag: "ADULT", label: "Nội dung 18+", color: "#9f1239", seconds: data.adult_seconds ?? 0 },
    ].filter(category => category.seconds > 0);
}

function formatUsageBreakdown(categories) {
    return categories.map(({ label, seconds }) => `${label} ${formatUsageSeconds(seconds)}`).join(" · ");
}
