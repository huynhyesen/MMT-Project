const ALARM = "mmt-web-usage";
const MAX_SAMPLE_MS = 35_000;
const MAX_BATCH_SECONDS = 120;
let pendingTask = Promise.resolve();

function schedule(task) {
    pendingTask = pendingTask.then(task).catch(error => console.warn("MMT web usage", error));
    return pendingTask;
}

function hostname(url) {
    try {
        const parsed = new URL(url);
        if (!["http:", "https:"].includes(parsed.protocol)) return "";
        return parsed.hostname.replace(/\.$/, "").replace(/^www\.(?=[^.]+\.)/, "");
    } catch {
        return "";
    }
}

async function activeHost(targets) {
    if (await chrome.idle.queryState(60) !== "active") return "";
    const window = await chrome.windows.getLastFocused();
    if (!window.focused) return "";
    const [tab] = await chrome.tabs.query({ active: true, windowId: window.id });
    const host = hostname(tab?.url);
    return targets.includes(host) ? host : "";
}

async function track(send = false) {
    const { tracking } = await chrome.storage.session.get("tracking");
    if (!tracking) return;

    const now = Date.now();
    if (tracking.active) {
        const elapsed = Math.min(MAX_SAMPLE_MS, Math.max(0, now - tracking.since));
        tracking.pending[tracking.active] = (tracking.pending[tracking.active] || 0) + elapsed;
    }
    tracking.since = now;
    tracking.active = await activeHost(tracking.targets);
    await chrome.storage.session.set({ tracking });
    if (!send) return;

    for (const [host, milliseconds] of Object.entries(tracking.pending)) {
        const duration_seconds = Math.min(MAX_BATCH_SECONDS, Math.floor(milliseconds / 1000));
        if (!duration_seconds) continue;
        try {
            const response = await fetch(tracking.origin + "/web-tracking/usage", {
                method: "POST",
                credentials: "omit",
                redirect: "error",
                headers: {
                    "Authorization": "Bearer " + tracking.token,
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({ host, duration_seconds }),
                signal: AbortSignal.timeout(5000)
            });

            if (response.status === 401) {
                await chrome.storage.session.remove("tracking");
                return;
            }
            if (response.ok || response.status === 403) {
                const remaining = milliseconds - duration_seconds * 1000;
                if (remaining) tracking.pending[host] = remaining;
                else delete tracking.pending[host];
                await chrome.storage.session.set({ tracking });
            }
        } catch {
            // Retain unreported time for the next alarm when the server is reachable.
        }
    }
}

chrome.runtime.onMessage.addListener((message, sender, respond) => {
    if (message.type !== "connect" || !sender.url || !Array.isArray(message.targets)
        || !/^[0-9a-f-]{36}\.[0-9]{1,12}\.[0-9a-f]{64}$/.test(message.token)) return;
    const page = new URL(sender.url);
    if (page.origin !== message.origin || !["/child/", "/child/index.html"].includes(page.pathname)) return;
    schedule(async () => {
        const { tracking: old } = await chrome.storage.session.get("tracking");
        if (old && old.origin !== message.origin) {
            respond({ connected: false });
            return;
        }
        const sameProfile = old?.token.split(".")[0] === message.token.split(".")[0];
        if (sameProfile) await track();
        const { tracking } = await chrome.storage.session.get("tracking");
        const targets = [...new Set(message.targets)].filter(host =>
            typeof host === "string" && /^[a-z0-9-]+(\.[a-z0-9-]+)+$/.test(host));
        await chrome.storage.session.set({ tracking: {
            origin: message.origin,
            token: message.token,
            targets,
            active: await activeHost(targets),
            since: Date.now(),
            pending: sameProfile ? tracking.pending : {}
        } });
        if (!(await chrome.alarms.get(ALARM))) await chrome.alarms.create(ALARM, { periodInMinutes: 0.5 });
        respond({ connected: true });
    });
    return true;
});

chrome.tabs.onActivated.addListener(() => schedule(() => track(true)));
chrome.tabs.onUpdated.addListener((_tab, changes) => {
    if (changes.url) schedule(() => track());
});
chrome.tabs.onRemoved.addListener(() => schedule(() => track()));
chrome.windows.onFocusChanged.addListener(() => schedule(() => track(true)));
chrome.idle.onStateChanged.addListener(() => schedule(() => track(true)));
chrome.idle.setDetectionInterval(60);
chrome.alarms.onAlarm.addListener(alarm => {
    if (alarm.name === ALARM) schedule(() => track(true));
});
