// Signal active browsing without inspecting page content or sending its address.
setInterval(() => {
    if (!document.hidden) chrome.runtime.sendMessage({ type: "pulse" }).catch(() => {});
}, 4000);
