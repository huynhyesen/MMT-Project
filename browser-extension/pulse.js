const adultContent = /(?<![\p{L}\p{N}])(?:phim\s*(?:18\+|người lớn|cấp 3)|video\s*khiêu dâm|sex videos?|porn(?:ographic)? videos?|hardcore porn)(?![\p{L}\p{N}])/iu;
const reportedLocation = location.hostname;
const publicHostname = reportedLocation.includes(".") && !/^[\d.]+$|\.(?:local|localhost|internal|lan|home\.arpa)$/i.test(reportedLocation);
let warningSent = false;
let warningPending = false;

setInterval(async () => {
    if (document.hidden) return;
    chrome.runtime.sendMessage({ type: "pulse" }).catch(() => {});
    if (!publicHostname || warningSent || warningPending) return;

    const title = document.title.slice(0, 512);
    const description = document.head?.querySelector(
        'meta[name="description"], meta[property="og:description"]'
    )?.content.slice(0, 1024) || "";
    if (![title, description].some(value => adultContent.test(value.normalize("NFC")))) return;

    warningPending = true;
    try {
        const result = await chrome.runtime.sendMessage({ type: "suspected-adult-content" });
        warningSent = result?.handled === true;
    } catch {
        // A later pulse can retry when the extension or tracking session reconnects.
    } finally {
        warningPending = false;
    }
}, 4000);
