const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const extension = path.join(__dirname, "..");
const origin = "http://127.0.0.1:8008";
const dashboard = origin + "/child/#device=test-enrollment";
const host = "lesson.example";
const token = "ab123456-cd12-34ef-5678-abcdefabcdef.1680000000." + "a".repeat(64);

test("content script starts on the dashboard including links with enrollment fragments", () => {
    const manifest = JSON.parse(readFileSync(path.join(extension, "manifest.json"), "utf8"));
    const [script] = manifest.content_scripts;
    assert.deepEqual(script.matches, ["http://*/child/*", "https://*/child/*"]);
    assert.equal(script.include_globs, undefined);
    assert.equal(script.run_at, "document_start");
});

test("a newly approved site is counted on another tab after the dashboard closes", async () => {
    const handlers = {};
    const reports = [];
    const event = name => ({ addListener(handler) { handlers[name] = handler; } });
    let policy = [];
    let storedTracking;
    let now = 100000;
    let activeTab = { url: dashboard };
    let alarmName;
    const chrome = {
        runtime: { onMessage: event("message") },
        tabs: {
            query: async () => [activeTab],
            onActivated: event("activated"),
            onUpdated: event("updated"),
            onRemoved: event("removed")
        },
        windows: {
            getLastFocused: async () => ({ id: 1, focused: true }),
            onFocusChanged: event("focus")
        },
        idle: { queryState: async () => "active", setDetectionInterval() {}, onStateChanged: event("idle") },
        alarms: {
            get: async () => alarmName,
            create: async name => { alarmName = name; },
            onAlarm: event("alarm")
        },
        storage: { session: {
            get: async () => ({ tracking: structuredClone(storedTracking) }),
            set: async ({ tracking }) => { storedTracking = structuredClone(tracking); }
        } }
    };
    const context = vm.createContext({
        chrome, URL, AbortSignal, console, Date: { now: () => now },
        fetch: async (url, options) => {
            assert.equal(options.headers.Authorization, "Bearer " + token);
            if (url === origin + "/web-tracking/policy") {
                return { ok: true, json: async () => ({ targets: policy }) };
            }
            assert.equal(url, origin + "/web-tracking/usage");
            reports.push(JSON.parse(options.body));
            return { ok: true };
        }
    });
    vm.runInContext(readFileSync(path.join(extension, "worker.js"), "utf8"), context);
    const settle = () => vm.runInContext("pendingTask", context);
    const connected = await new Promise(resolve => {
        handlers.message({ type: "connect", origin, token, targets: [] }, { url: dashboard }, resolve);
    });
    assert.equal(connected.connected, true);

    activeTab = { url: "about:blank" };
    handlers.removed(1);
    await settle();
    policy = [host];
    activeTab = { url: "https://www.lesson.example/chapter?topic=math" };
    handlers.updated(2, { url: activeTab.url });
    await settle();

    now += 5500;
    activeTab = { url: "https://unapproved.example/" };
    handlers.activated({ tabId: 3, windowId: 1 });
    await settle();
    assert.deepEqual(reports, [{ host, duration_seconds: 5 }]);

    now += 10000;
    handlers.alarm({ name: alarmName });
    await settle();
    assert.equal(reports.length, 1);
});
