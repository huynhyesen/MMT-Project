const ALARM = "mmt-web-usage";
const HOST_CAPTURE = "^https?://([a-z0-9.-]+)(?::[0-9]+)?(?:[/?#].*)?$";
const MAX_SAMPLE_MS = 35_000;
let work = Promise.resolve();
let adultRules;

function enqueue(task) {
    work = work.then(task).catch(error => console.warn("MMT web policy", error));
    return work;
}

function hostname(value) {
    try {
        const url = new URL(value);
        if (!["http:", "https:"].includes(url.protocol)) return "";
        const host = url.hostname.replace(/\.$/, "").replace(/^www\.(?=[^.]+\.)/, "");
        return /^[a-z0-9-]+(\.[a-z0-9-]+)+$/.test(host) ? host : "";
    } catch {
        return "";
    }
}

function domains(values) {
    return [...new Set(Array.isArray(values) ? values : [])].filter(
        value => typeof value === "string" && hostname("https://" + value) === value
    ).sort();
}

async function packagedAdultRules() {
    adultRules ??= await (await fetch(chrome.runtime.getURL("adult-rules.json"))).json();
    return adultRules;
}

function redirectRule(id, priority, kind, condition) {
    return {
        id, priority, condition: { ...condition, resourceTypes: ["main_frame"] },
        action: {
            type: "redirect",
            redirect: { regexSubstitution: chrome.runtime.getURL("blocked.html") + "?kind=" + kind + "&host=\\1" }
        }
    };
}

async function browserRules(policy, origin) {
    const result = [];
    for (const [index, rule] of (await packagedAdultRules()).entries()) {
        const { requestDomains, regexFilter } = rule.condition;
        // The first group contains just the domain, and the rest of the URL is discarded.
        const capture = regexFilter
            ? "^https?://(" + regexFilter.slice("^https?://".length, -"[:/]".length) + ")(?::[0-9]+)?(?:[/?#].*)?$"
            : HOST_CAPTURE;
        result.push(redirectRule(100 + index, 5, "adult", requestDomains
            ? { regexFilter: capture, requestDomains }
            : { regexFilter: capture }));
    }
    const adult = domains(policy.adult);
    for (let start = 0; start < adult.length; start += 350) {
        result.push(redirectRule(200 + start / 350, 5, "adult", {
            regexFilter: HOST_CAPTURE, requestDomains: adult.slice(start, start + 350)
        }));
    }

    if (!origin) return result;
    const serverHost = new URL(origin).hostname;
    const exclusions = serverHost.startsWith("[") ? {} : { excludedRequestDomains: [serverHost] };
    const blocked = domains(policy.blocked);
    if (blocked.length) result.push(redirectRule(1000, 4, "blocked", {
        regexFilter: HOST_CAPTURE, requestDomains: blocked, ...exclusions
    }));
    if (["curfew", "daily"].includes(policy.restriction)) {
        result.push(redirectRule(1001, 3, policy.restriction, { regexFilter: HOST_CAPTURE, ...exclusions }));
    }
    for (const [kind, id] of [["ask", 2000], ["expired", 3000]]) {
        const hosts = domains(policy[kind]);
        for (let start = 0; start < hosts.length; start += 5) {
            const alternatives = hosts.slice(start, start + 5).map(host => host.replaceAll(".", "\\."));
            const regexFilter = "^https?://((?:www\\.)?(?:" + alternatives.join("|") +
                ")\\.?)(?::[0-9]+)?(?:[/?#].*)?$";
            result.push(redirectRule(id + start / 5, 2, kind, { regexFilter, ...exclusions }));
        }
    }
    return result;
}

async function installPolicy(policy, origin) {
    const rules = await browserRules(policy, origin);
    const desired = JSON.stringify(rules);
    const { installedRules } = await chrome.storage.session.get("installedRules");
    if (desired === installedRules) return;
    const previous = await chrome.declarativeNetRequest.getDynamicRules();
    const owned = previous.filter(rule => rule.id >= 100 && rule.id < 4000 || rule.id === 10001);
    // On browser restart retain the last downloaded restrictions until a fresh PIN session connects.
    const removeRuleIds = owned.filter(rule => origin || (rule.id < 200)).map(rule => rule.id);
    await chrome.declarativeNetRequest.updateDynamicRules({ removeRuleIds, addRules: rules });
    await chrome.storage.session.set({ installedRules: desired });
}

async function activePage() {
    const activity = await chrome.idle.queryState(60);
    if (activity === "locked") return null;
    const window = await chrome.windows.getLastFocused();
    if (!window.focused) return null;
    const [tab] = await chrome.tabs.query({ active: true, windowId: window.id });
    const host = hostname(tab?.url);
    if (!host) return null;
    return {
        id: tab.id, host, url: tab.url,
        used: activity !== "idle" || (tab.audible && !tab.mutedInfo?.muted)
    };
}

function backendRequest(tracking, path, options = {}) {
    return fetch(tracking.origin + path, {
        credentials: "omit", redirect: "error", signal: AbortSignal.timeout(5000), ...options,
        headers: { ...options.headers, Authorization: "Bearer " + tracking.token }
    });
}

function accessKind(host, policy) {
    if ((policy.blocked || []).some(domain => host === domain || host.endsWith("." + domain))) return "blocked";
    if (policy.restriction) return policy.restriction;
    if (policy.ask?.includes(host)) return "ask";
    if (policy.expired?.includes(host)) return "expired";
    return "";
}

async function enforceActivePage(page, tracking) {
    if (!page || new URL(page.url).origin === tracking.origin) return;
    const kind = accessKind(page.host, tracking.policy);
    if (!kind) return;
    const tab = await chrome.tabs.get(page.id).catch(() => null);
    if (tab && hostname(tab.url) === page.host) {
        await chrome.tabs.update(tab.id, {
            url: chrome.runtime.getURL("blocked.html") + "?kind=" + kind + "&host=" + encodeURIComponent(page.host)
        });
    }
}

async function refreshPolicy(tracking) {
    try {
        const response = await backendRequest(tracking, "/web-tracking/policy");
        if (response.ok) {
            tracking.policy = await response.json();
            await installPolicy(tracking.policy, tracking.origin);
        }
    } catch (error) {
        console.warn("MMT policy refresh", error);
    }
}

async function sendPendingUsage(tracking) {
    for (const [host, ms] of Object.entries(tracking.pending)) {
        const duration_seconds = Math.min(120, Math.floor(ms / 1000));
        if (!duration_seconds) continue;
        try {
            const response = await backendRequest(tracking, "/web-tracking/usage", {
                method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ host, duration_seconds })
            });
            if (response.status === 401) {
                await chrome.storage.session.remove("tracking");
                return false;
            }
            if (response.ok) {
                const result = await response.json();
                tracking.pending[host] = ms - duration_seconds * 1000;
                if (tracking.pending[host] === 0) delete tracking.pending[host];
                if (result.remaining_seconds === 0 || result.daily_remaining === 0) {
                    delete tracking.pending[host];
                    if (result.remaining_seconds === 0) {
                        tracking.policy.expired = [...new Set([...(tracking.policy.expired || []), host])];
                        tracking.policy.expired_usage ??= {};
                        tracking.policy.expired_usage[host] = result.used_seconds;
                    }
                    if (result.daily_remaining === 0) {
                        tracking.policy.restriction = "daily";
                        tracking.policy.daily_used_seconds = result.daily_used_seconds;
                    }
                    await installPolicy(tracking.policy, tracking.origin);
                    await refreshPolicy(tracking);
                } else {
                    if (Number.isFinite(result.remaining_seconds)) {
                        tracking.policy.remaining ??= {};
                        tracking.policy.remaining[host] = result.remaining_seconds;
                    }
                    if (Number.isFinite(result.daily_remaining)) tracking.policy.daily_remaining = result.daily_remaining;
                }
            } else if (response.status === 403 || response.status === 422) {
                delete tracking.pending[host];
                await refreshPolicy(tracking);
            }
        } catch {
            // Try again on the next event.
        }
    }
    return true;
}

async function track({ flush = false, refresh = false } = {}) {
    const { tracking } = await chrome.storage.session.get("tracking");
    if (!tracking) return;
    const now = Date.now();
    if (tracking.active) {
        const elapsed = Math.min(MAX_SAMPLE_MS, Math.max(0, now - tracking.since));
        tracking.pending[tracking.active] = (tracking.pending[tracking.active] || 0) + elapsed;
    }
    tracking.since = now;
    const page = await activePage();
    if (refresh || page && tracking.observedHost !== page.host) await refreshPolicy(tracking);
    const policy = tracking.policy;
    const pendingTotal = Object.values(tracking.pending).reduce((total, ms) => total + ms, 0);
    const nowAtLimit = Object.entries(tracking.pending).some(([host, ms]) =>
        ms >= (policy.remaining?.[host] ?? Infinity) * 1000
    ) || pendingTotal >= (policy.daily_remaining ?? Infinity) * 1000;
    if ((flush || pendingTotal >= 30_000 || nowAtLimit) && !await sendPendingUsage(tracking)) return;
    const host = page?.host || "";
    const eligible = page?.used && new URL(page.url).origin !== tracking.origin && !accessKind(host, tracking.policy);
    tracking.active = eligible && (tracking.policy.track_unrestricted || tracking.policy.targets?.includes(host)) ? host : "";
    tracking.observedHost = host;
    await chrome.storage.session.set({ tracking });
    await enforceActivePage(page, tracking);
}

async function reportBlockedAdultHost(tracking, host) {
    try {
        await backendRequest(tracking, "/web-tracking/alert", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ host })
        });
    } catch (error) {
        console.warn("MMT alert delivery", error);
    }
}

async function connect(message, sender) {
    const page = new URL(sender.url);
    if (page.origin !== message.origin || !["/child/", "/child/index.html"].includes(page.pathname)) return false;
    if (!/^[0-9a-f-]{36}\.[0-9]{1,12}\.[0-9a-f]{64}$/.test(message.token)) return false;
    const { tracking: old } = await chrome.storage.session.get("tracking");
    if (old && old.origin !== message.origin) return false;
    const sameProfile = old?.token.split(".")[0] === message.token.split(".")[0];
    if (sameProfile) await track();
    const { tracking: previous } = await chrome.storage.session.get("tracking");
    const tracking = {
        origin: message.origin, token: message.token,
        since: Date.now(), pending: sameProfile && previous ? previous.pending : {}
    };
    const policyResponse = await backendRequest(tracking, "/web-tracking/policy");
    if (!policyResponse.ok) return false;
    tracking.policy = await policyResponse.json();
    if (!Array.isArray(tracking.policy.targets)) return false;
    await installPolicy(tracking.policy, tracking.origin);
    await chrome.storage.session.set({ tracking });
    if (!(await chrome.alarms.get(ALARM))) await chrome.alarms.create(ALARM, { periodInMinutes: 0.5 });
    await track();
    return true;
}

chrome.runtime.onMessage.addListener((message, sender, respond) => {
    if (message.type === "pulse" && sender.tab?.active) {
        enqueue(() => track());
        return;
    }
    if (message.type === "connect" && sender.url) {
        enqueue(() => connect(message, sender)).then(connected => respond({ connected: connected === true }));
        return true;
    }
    if (message.type === "blocked-page" && sender.url?.startsWith(chrome.runtime.getURL("blocked.html") + "?")) {
        enqueue(async () => {
            const { tracking } = await chrome.storage.session.get("tracking");
            const host = hostname("https://" + message.host);
            if (tracking && message.kind === "adult" && host) await reportBlockedAdultHost(tracking, host);
            if (!tracking) return null;
            return {
                origin: tracking.origin,
                used_seconds: message.kind === "daily"
                    ? tracking.policy.daily_used_seconds : tracking.policy.expired_usage?.[host]
            };
        }).then(respond);
        return true;
    }
});

chrome.runtime.onInstalled.addListener(() => enqueue(() => installPolicy({}, null)));
chrome.runtime.onStartup.addListener(() => enqueue(() => installPolicy({}, null)));
chrome.tabs.onActivated.addListener(() => enqueue(() => track({ flush: true })));
chrome.tabs.onUpdated.addListener((_tab, changes) => {
    if (changes.url || changes.audible !== undefined) enqueue(() => track({ flush: true }));
});
chrome.tabs.onRemoved.addListener(() => enqueue(() => track({ flush: true })));
chrome.windows.onFocusChanged.addListener(() => enqueue(() => track({ flush: true })));
chrome.idle.onStateChanged.addListener(() => enqueue(() => track({ flush: true })));
chrome.idle.setDetectionInterval(60);
chrome.alarms.onAlarm.addListener(alarm => {
    if (alarm.name === ALARM) enqueue(() => track({ flush: true, refresh: true }));
});
