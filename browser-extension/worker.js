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

async function activeHost() {
    const activity = await chrome.idle.queryState(60);
    if (activity === "locked") return "";
    const window = await chrome.windows.getLastFocused();
    if (!window.focused) return "";
    const [tab] = await chrome.tabs.query({ active: true, windowId: window.id });
    // A foreground tab can be in use while a video plays without mouse or keyboard input.
    if (activity === "idle" && (!tab?.audible || tab.mutedInfo?.muted)) return "";
    return hostname(tab?.url);
}

function backendRequest(tracking, path, options = {}) {
    return fetch(tracking.origin + path, {
        credentials: "omit",
        redirect: "error",
        signal: AbortSignal.timeout(5000),
        ...options,
        headers: {
            ...options.headers,
            "Authorization": "Bearer " + tracking.token
        }
    });
}

async function refreshTargets(tracking) {
    try {
        const response = await backendRequest(tracking, "/web-tracking/policy");
        if (response.ok) {
            const { targets } = await response.json();
            if (Array.isArray(targets)) tracking.targets = targets;
        }
    } catch {
        // Keep the known policy during a connection interruption.
    }
}

async function track(send = false, refreshPolicy = false) {
    const { tracking } = await chrome.storage.session.get("tracking");
    if (!tracking) return;

    const now = Date.now();
    if (tracking.active) {
        const elapsed = Math.min(MAX_SAMPLE_MS, Math.max(0, now - tracking.since));
        tracking.pending[tracking.active] = (tracking.pending[tracking.active] || 0) + elapsed;
    }
    const observedHost = await activeHost();
    if (refreshPolicy || (observedHost && observedHost !== tracking.observedHost &&
        !tracking.targets.includes(observedHost) && observedHost !== hostname(tracking.origin))) {
        await refreshTargets(tracking);
    }
    tracking.since = now;
    tracking.observedHost = observedHost;
    tracking.active = tracking.targets.includes(observedHost) ? observedHost : "";
    await chrome.storage.session.set({ tracking });
    if (!send) return;

    for (const [host, milliseconds] of Object.entries(tracking.pending)) {
        const duration_seconds = Math.min(MAX_BATCH_SECONDS, Math.floor(milliseconds / 1000));
        if (!duration_seconds) continue;
        try {
            const response = await backendRequest(tracking, "/web-tracking/usage", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ host, duration_seconds })
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
        const observedHost = await activeHost();
        await chrome.storage.session.set({ tracking: {
            origin: message.origin,
            token: message.token,
            targets,
            observedHost,
            active: targets.includes(observedHost) ? observedHost : "",
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
    if (changes.url || changes.audible !== undefined) schedule(() => track(true));
});
chrome.tabs.onRemoved.addListener(() => schedule(() => track(true)));
chrome.windows.onFocusChanged.addListener(() => schedule(() => track(true)));
chrome.idle.onStateChanged.addListener(() => schedule(() => track(true)));
chrome.idle.setDetectionInterval(60);
chrome.alarms.onAlarm.addListener(alarm => {
    if (alarm.name === ALARM) schedule(() => track(true, true));
});
