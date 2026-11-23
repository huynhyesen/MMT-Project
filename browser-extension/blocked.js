const reasons = {
    adult: ["Trang 18+ đã bị chặn", "Tên miền này thuộc bộ lọc 18+ của MMT."],
    blocked: ["Trang web đang bị chặn", "Phụ huynh đã chặn tên miền này."],
    ask: ["Trang này cần xin phép", "Gửi yêu cầu để phụ huynh xem và quyết định.", "Xin phép"],
    expired: ["Trang web đã hết giờ", "Bạn có thể xin thêm thời gian cho trang này.", "Xin thêm giờ"],
    daily: ["Đã hết giờ sử dụng hôm nay", "Bạn có thể xin thêm thời gian dùng máy.", "Xin thêm giờ"],
    curfew: ["Đang trong giờ giới nghiêm", "Bạn có thể mở lại trang khi giờ giới nghiêm kết thúc."]
};
const params = new URLSearchParams(location.search);
const kind = Object.hasOwn(reasons, params.get("kind")) ? params.get("kind") : "blocked";
const hostValue = params.get("host")?.toLowerCase().replace(/\.$/, "") || "";
const host = /^[a-z0-9.-]{1,253}$/.test(hostValue) ? hostValue : "";
const [heading, explanation, action] = reasons[kind];
document.title = "MMT · " + heading;
document.getElementById("heading").textContent = heading;
document.getElementById("explanation").textContent = explanation;
if (host) {
    const domain = document.getElementById("domain");
    domain.textContent = host;
    domain.hidden = false;
}

let dashboard;
document.getElementById("back").addEventListener("click", () => {
    if (history.length > 1) history.back();
    else location.replace(dashboard || "about:blank");
});

chrome.runtime.sendMessage({ type: "blocked-page", kind, host }).then(context => {
    if (!context?.origin) return;
    dashboard = new URL("/child/", context.origin).href;
    if (context.used_seconds != null && ["expired", "daily"].includes(kind)) {
        const used = document.getElementById("used");
        const minutes = Math.floor(context.used_seconds / 60);
        const seconds = context.used_seconds % 60;
        used.textContent = `Đã dùng ${minutes} phút${seconds ? " " + seconds + " giây" : ""}.`;
        used.hidden = false;
    }
    if (action && (kind === "daily" || host)) {
        const request = document.getElementById("request");
        const url = new URL(dashboard);
        url.searchParams.set("web_request", kind);
        if (kind !== "daily") url.searchParams.set("host", host);
        request.href = url.href;
        request.textContent = action;
        request.hidden = false;
    }
}).catch(() => {});
