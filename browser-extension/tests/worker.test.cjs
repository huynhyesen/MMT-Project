const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const folder = path.join(__dirname, "..");
const source = readFileSync(path.join(folder, "worker.js"), "utf8");
const adultRules = JSON.parse(readFileSync(path.join(folder, "adult-rules.json"), "utf8"));
const origin = "http://127.0.0.1:8008";
const extensionOrigin = "chrome-extension://fixture/";
const token = "ab123456-cd12-34ef-5678-abcdefabcdef.1680000000." + "a".repeat(64);

function fakeBrowser(policy) {
    const handlers = {};
    const writes = [];
    const storage = {};
    const reports = [];
    const alerts = [];
    const event = name => ({ addListener(callback) { handlers[name] = callback; } });
    let installed = [];
    let now = 1000;
    let page = { id: 4, url: origin + "/child/" };
    let activity = "active";
    let focused = true;

    const chrome = {
        runtime: {
            getURL: file => extensionOrigin + file,
            onMessage: event("message"), onInstalled: event("installed"), onStartup: event("startup"),
        },
        alarms: { get: async () => null, create: async () => {}, onAlarm: event("alarm") },
        windows: { getLastFocused: async () => ({ focused, id: 1 }), onFocusChanged: event("focus") },
        idle: { queryState: async () => activity, setDetectionInterval() {}, onStateChanged: event("idle") },
        storage: { session: {
            get: async key => ({ [key]: structuredClone(storage[key]) }),
            set: async value => { Object.assign(storage, structuredClone(value)); },
            remove: async key => { delete storage[key]; },
        }},
        tabs: {
            query: async () => [page], get: async () => page,
            update: async (id, { url }) => { writes.push(url); page = { id, url }; },
            onActivated: event("activated"), onUpdated: event("updated"), onRemoved: event("removed"),
        },
        declarativeNetRequest: {
            getDynamicRules: async () => structuredClone(installed),
            updateDynamicRules: async ({ removeRuleIds, addRules }) => {
                installed = installed.filter(rule => !removeRuleIds.includes(rule.id)).concat(structuredClone(addRules));
            },
        },
    };
    const context = vm.createContext({
        chrome, URL, AbortSignal, console, Date: { now: () => now },
        fetch: async (url, options) => {
            if (url === extensionOrigin + "adult-rules.json") return { json: async () => adultRules };
            assert.equal(options.headers.Authorization, "Bearer " + token);
            if (url === origin + "/web-tracking/policy") {
                return { ok: true, json: async () => structuredClone(policy) };
            }
            const payload = JSON.parse(options.body);
            if (url === origin + "/web-tracking/alert") {
                alerts.push(payload);
                return { ok: true };
            }
            assert.equal(url, origin + "/web-tracking/usage");
            reports.push(payload);
            if (policy.remaining?.[payload.host] != null) {
                const left = Math.max(0, policy.remaining[payload.host] - payload.duration_seconds);
                policy.remaining[payload.host] = left;
                if (!left) {
                    policy.expired.push(payload.host);
                    policy.expired_usage = { [payload.host]: 1800 };
                }
                return { ok: true, json: async () => ({ remaining_seconds: left }) };
            }
            return { ok: true, json: async () => ({}) };
        },
    });
    vm.runInContext(source, context);
    return {
        handlers, writes, reports, alerts,
        rules: () => installed,
        navigate: (url, audible = false) => { page = { id: 4, url, audible }; },
        setActivity: state => { activity = state; },
        setFocus: active => { focused = active; },
        advance: ms => { now += ms; },
        settle: () => vm.runInContext("work", context),
        message: (value, sender) => new Promise(resolve => handlers.message(value, sender, resolve)),
        connect: () => new Promise(resolve => handlers.message({
            type: "connect", origin, token
        }, { url: origin + "/child/#device=fixture" }, resolve)),
    };
}

test("the manifest exposes the notice page and attaches only the bridge to dashboard pages", () => {
    const manifest = JSON.parse(readFileSync(path.join(folder, "manifest.json"), "utf8"));
    assert.deepEqual(manifest.content_scripts[0].matches, ["http://*/child/*", "https://*/child/*"]);
    assert.equal(manifest.content_scripts[0].run_at, "document_start");
    assert.deepEqual(manifest.web_accessible_resources[0].resources, ["blocked.html"]);
});

test("the browser redirects adult and restricted sites, passing only the domain", async () => {
    const policy = { targets: [], ask: ["lesson.example"], blocked: ["blocked.example"], adult: ["extra.example"] };
    const browser = fakeBrowser(policy);
    assert.equal((await browser.connect()).connected, true);
    const match = browser.rules().find(rule =>
        rule.action.redirect.regexSubstitution.includes("kind=adult") &&
        new RegExp(rule.condition.regexFilter).test("https://test-p0rn.example/path?private=1") &&
        !rule.condition.requestDomains
    );
    assert(match);
    assert.equal(new RegExp(match.condition.regexFilter).exec("https://test-p0rn.example/path?private=1")[1], "test-p0rn.example");
    assert(browser.rules().some(rule => rule.condition.requestDomains?.includes("extra.example")));
    const ask = browser.rules().find(rule => rule.action.redirect.regexSubstitution.includes("kind=ask"));
    assert(new RegExp(ask.condition.regexFilter).test("https://www.lesson.example/"));
    assert(!new RegExp(ask.condition.regexFilter).test("https://other.example/"));
    assert(ask.condition.excludedRequestDomains.includes("127.0.0.1"));

    const context = await browser.message({ type: "blocked-page", kind: "adult", host: "test-p0rn.example" }, {
        url: extensionOrigin + "blocked.html?kind=adult&host=test-p0rn.example"
    });
    assert.equal(context.origin, origin);
    assert.deepEqual(browser.alerts, [{ host: "test-p0rn.example" }]);
});

test("the worker records ordinary websites and redirects the active tab when its limit expires", async () => {
    const policy = {
        targets: ["lesson.example"], expired: [], remaining: { "lesson.example": 3 }, track_unrestricted: true
    };
    const browser = fakeBrowser(policy);
    assert.equal((await browser.connect()).connected, true);

    browser.navigate("https://ordinary.example/");
    browser.handlers.updated(4, { url: "https://ordinary.example/" });
    await browser.settle();
    browser.advance(6000);
    browser.navigate("https://www.lesson.example/watch?private=test", true);
    browser.handlers.activated();
    await browser.settle();
    assert.deepEqual(browser.reports[0], { host: "ordinary.example", duration_seconds: 6 });

    browser.setActivity("idle");
    browser.advance(4000);
    browser.handlers.message({ type: "pulse" }, { tab: { active: true } });
    await browser.settle();
    assert.deepEqual(browser.reports[1], { host: "lesson.example", duration_seconds: 4 });
    assert.deepEqual(browser.writes, [extensionOrigin + "blocked.html?kind=expired&host=lesson.example"]);
});


test("only the foreground tab is counted across connection renewals, blur and lock", async () => {
    const browser = fakeBrowser({ targets: [], track_unrestricted: true });
    browser.navigate("https://ordinary.example/");
    await browser.connect();
    browser.advance(2000);
    await browser.connect();
    browser.advance(3000);

    browser.setFocus(false);
    browser.handlers.focus(-1);
    await browser.settle();
    assert.deepEqual(browser.reports, [{ host: "ordinary.example", duration_seconds: 5 }]);

    browser.advance(15000);
    browser.setFocus(true);
    browser.setActivity("locked");
    browser.handlers.idle("locked");
    await browser.settle();
    browser.advance(20000);
    browser.handlers.alarm({ name: "mmt-web-usage" });
    await browser.settle();
    assert.equal(browser.reports.length, 1);
});
