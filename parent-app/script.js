let selectedChildId = null;
function consoleFetch(url, options = {}) {
    const headers = new Headers(options.headers);
    headers.set("X-MMT-Console", "parent");
    return fetch(url, { ...options, headers });
}

const API_BASE = location.origin;
const WS_URL = API_BASE.replace(/^http/, "ws") + "/ws/agent/parent_dashboard";

        let ws = null;
        let cachedUsageItems = [];
        let currentUsageTag = "ALL";
        let usageRequestId = 0;
        let currentActiveTab = 'overview';

        // --- HỆ THỐNG ÂM THANH THÔNG BÁO "TING" & DESKTOP NOTIFICATION ---
        let soundEnabled = localStorage.getItem("mmt_parent_sound") !== "false";

        function updateSoundUI() {
            const btn = document.getElementById("btn-sound-toggle");
            const icon = document.getElementById("sound-icon");
            const text = document.getElementById("sound-text");
            if (!btn || !icon || !text) return;

            if (soundEnabled) {
                icon.textContent = "🔔";
                text.textContent = "Chuông: Bật";
                btn.className = "px-3 py-1.5 rounded-xl text-xs font-semibold border transition flex items-center gap-1.5 bg-blue-50 border-blue-200 text-blue-700 hover:bg-blue-100";
            } else {
                icon.textContent = "🔕";
                text.textContent = "Chuông: Tắt";
                btn.className = "px-3 py-1.5 rounded-xl text-xs font-semibold border transition flex items-center gap-1.5 bg-slate-50 border-slate-200 text-slate-500 hover:bg-slate-100";
            }
        }

        function toggleSound() {
            soundEnabled = !soundEnabled;
            localStorage.setItem("mmt_parent_sound", soundEnabled ? "true" : "false");
            updateSoundUI();
            if (soundEnabled) {
                playNotificationSound('ting');
                showToast("🔔 Đã bật âm thanh thông báo và hiện thông báo trên màn hình máy tính!", "success");
                requestDesktopNotificationPermission();
            } else {
                showToast("🔕 Đã tắt âm thanh thông báo.", "info");
            }
        }

        function requestDesktopNotificationPermission() {
            if ("Notification" in window && Notification.permission === "default") {
                Notification.requestPermission();
            }
        }

        function playNotificationSound(type = 'ting') {
            if (!soundEnabled) return;
            try {
                const AudioCtx = window.AudioContext || window.webkitAudioContext;
                if (!AudioCtx) return;
                const ctx = new AudioCtx();
                if (ctx.state === 'suspended') ctx.resume();
                const now = ctx.currentTime;

                if (type === 'ting') {
                    // Âm thanh "Ting" thánh thót (A5 880Hz + hài âm E6 1320Hz mềm)
                    const osc1 = ctx.createOscillator();
                    const osc2 = ctx.createOscillator();
                    const gain = ctx.createGain();

                    osc1.type = 'sine';
                    osc1.frequency.setValueAtTime(880, now);
                    osc1.frequency.exponentialRampToValueAtTime(1760, now + 0.04);
                    osc1.frequency.exponentialRampToValueAtTime(880, now + 0.12);

                    osc2.type = 'triangle';
                    osc2.frequency.setValueAtTime(1320, now);

                    gain.gain.setValueAtTime(0.35, now);
                    gain.gain.exponentialRampToValueAtTime(0.0001, now + 0.75);

                    osc1.connect(gain);
                    osc2.connect(gain);
                    gain.connect(ctx.destination);

                    osc1.start(now);
                    osc2.start(now);
                    osc1.stop(now + 0.75);
                    osc2.stop(now + 0.75);
                } else if (type === 'alert') {
                    // Âm thanh cảnh báo nhẹ nhàng
                    [392, 330].forEach((freq, idx) => {
                        const noteTime = now + idx * 0.15;
                        const osc = ctx.createOscillator();
                        const gain = ctx.createGain();
                        osc.type = 'sine';
                        osc.frequency.setValueAtTime(freq, noteTime);
                        gain.gain.setValueAtTime(0.25, noteTime);
                        gain.gain.exponentialRampToValueAtTime(0.001, noteTime + 0.35);
                        osc.connect(gain);
                        gain.connect(ctx.destination);
                        osc.start(noteTime);
                        osc.stop(noteTime + 0.35);
                    });
                }
            } catch (e) {
                console.warn("Lỗi phát âm thanh:", e);
            }
        }

        function showDesktopNotification(title, body) {
            if (!("Notification" in window)) return;
            if (Notification.permission === "granted") {
                try {
                    new Notification(title, { body: body });
                } catch (e) {}
            }
        }

        const tabMeta = {
            'overview': { title: '🏠 Tổng Quan Điều Khiển', desc: 'Trang chủ quản trị & theo dõi hoạt động của con' },
            'children': { title: '👨‍👩‍👧‍👦 Hồ Sơ Con Cái', desc: 'Tạo tài khoản riêng cho từng bé, cài mã PIN và chuyển đổi tài khoản sử dụng' },
            'control': { title: '⚡ Điều Khiển Khẩn Cấp', desc: 'Khóa / Mở máy tính từ xa và gửi lời nhắn trực tiếp tức thì' },
            'requests': { title: '📩 Yêu Cầu Xin Phép', desc: 'Phê duyệt hoặc từ chối khi con xin phép mở Web / Ứng dụng mới hoặc xin thêm giờ' },
            'stats': { title: '📊 Thống Kê & Giới Hạn', desc: 'Thống kê các app/web thực sự sử dụng với nhãn AI và tự điền giới hạn' },
            'rules': { title: '🛡️ Quản Lý Quy Tắc Web / App', desc: 'Danh sách các trang web / phần mềm đang được Cho phép hoặc Chặn' },
            'curfew': { title: '🌙 Khung Giờ Giới Nghiêm', desc: 'Tự động vô hiệu hóa máy ban đêm và mở lại vào sáng hôm sau' },
            'alerts': { title: '🚨 Nhật Ký Cảnh Báo & Lọc AI', desc: 'Phát hiện nội dung không phù hợp qua AI và cảnh báo can thiệp Anti-Tamper' },
            'reset': { title: '🔄 Cài Đặt & Đặt Lại Hệ Thống', desc: 'Đặt lại thời gian về 0, làm sạch hộp thư hoặc khôi phục cài đặt gốc' }
        };

        function switchParentTab(tabName) {
            currentActiveTab = tabName;

            document.querySelectorAll('.tab-pane').forEach(el => el.classList.add('hidden'));
            const targetPane = document.getElementById(`tab-${tabName}`);
            if (targetPane) targetPane.classList.remove('hidden');

            document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
            const activeBtn = document.getElementById(`nav-${tabName}`);
            if (activeBtn) activeBtn.classList.add('active');

            if (tabMeta[tabName]) {
                document.getElementById('current-tab-title').innerHTML = tabMeta[tabName].title;
                document.getElementById('current-tab-desc').textContent = tabMeta[tabName].desc;
            }

            const mobileNav = document.getElementById('sidebar-nav');
            if (window.innerWidth < 768 && mobileNav && !mobileNav.classList.contains('hidden')) {
                mobileNav.classList.add('hidden');
            }
            refreshVisibleUsageStats();
        }

        function toggleMobileMenu() {
            const nav = document.getElementById('sidebar-nav');
            if (nav) nav.classList.toggle('hidden');
        }

        function showServerNotice(show) {
            const banner = document.getElementById("server-offline-banner");
            if (banner) {
                if (show) banner.classList.remove("hidden");
                else banner.classList.add("hidden");
            }

        }

        function initWebSocket() {
            const wsBadge = document.getElementById("ws-badge");
            try {
                ws = new WebSocket(WS_URL);

                ws.onopen = () => {
                    wsBadge.className = "inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold bg-emerald-900/60 text-emerald-300 border border-emerald-500/40";
                    wsBadge.innerHTML = `<span class="w-1.5 h-1.5 mr-1 rounded-full bg-emerald-400"></span>Đã kết nối 🟢`;
                    showServerNotice(false);
                };

                ws.onmessage = (event) => {
                    try {
                        const data = JSON.parse(event.data);
                        if (data.type === "NEW_REQUEST") {
                            playNotificationSound('ting');
                            showDesktopNotification("📩 Yêu cầu mới từ con!", `Bé vừa xin: "${data.data?.target_detail || ''}"\nLý do: ${data.data?.reason_from_child || ''}`);
                            showToast(`🔔 Bé vừa xin phép: "${data.data.target_detail}" - Lý do: ${data.data.reason_from_child}`, "info");
                            fetchRequests();
                        } else if (data.type === "ADULT_WEBSITE_BLOCKED") {
                            if (data.first_attempt) {
                                const text = `${data.child_name || "Máy con"} · Đã chặn ${data.domain}`;
                                playNotificationSound("alert");
                                showDesktopNotification("Cảnh báo 18+", text);
                                showToast(text, "danger");
                            }
                            fetchAlerts();
                        } else if (data.type === "UNAPPROVED_ATTEMPT") {
                            playNotificationSound('alert');
                            showDesktopNotification("🚨 Cảnh báo từ máy con!", `Con vừa cố mở: "${data.app_name}"`);
                            const banner = document.getElementById("alert-banner");
                            document.getElementById("alert-title").innerText = `⚠️ Cảnh báo: Con vừa cố mở "${data.app_name}"!`;
                            document.getElementById("alert-desc").innerText = data.message || "Ứng dụng chưa được phép và đã bị chặn lại.";
                            banner.classList.remove("hidden");
                            showToast(`⚠️ Con vừa cố mở web/app lạ chưa xin phép: "${data.app_name}"`, "danger");
                            fetchAlerts();
                        } else if (data.type === "AI_CONTENT_VIOLATION") {
                            playNotificationSound('alert');
                            showDesktopNotification("🤖 AI Content Filter!", `Đã chặn nội dung: "${data.source}" (${data.reason})`);
                            showToast(`🚨 [AI Filter] Đã chặn nội dung không phù hợp: "${data.source}" (${data.reason})`, "danger");
                            fetchAlerts();
                        } else if (data.type === "DEVICE_CREATED" || data.type === "DEVICE_PAIRED" || data.type === "DEVICE_CONNECTED_WAN" || data.type === "DEVICE_DISCONNECTED_WAN") {
                            if (data.type === "DEVICE_PAIRED") {
                                playNotificationSound('ting');
                                showToast(`🎉 Thiết bị "${data.device_name}" đã ghép nối thành công!`, "success");
                            }
                            fetchChildren();
                        } else if (data.type === "PROFILES_UPDATED" || data.type === "CHILD_SWITCHED") {
                            fetchChildren();
                            fetchUsageStats();
                            fetchChildren();
                        } else if (data.type === "CURFEW_UPDATED") {
                            fetchCurfew();
                        } else if (data.type === "RULES_UPDATED") {
                            fetchRules();
                            fetchUsageStats();
                        } else if (data.type === "REQUEST_DECIDED") {
                            fetchRequests();
                            fetchRules();
                            fetchUsageStats();
                        } else if (data.type === "USAGE_RESET") {
                            fetchUsageStats();
                            fetchRules();
                        } else if (data.type === "DAILY_RESET_TRIGGERED" || data.type === "DAILY_RESET") {
                            fetchUsageStats();
                            fetchRules();
                            fetchRequests();
                            showToast("🌅 Bắt đầu ngày mới: Thời gian sử dụng đã được làm mới tự động!", "success");
                        }
                    } catch (e) {
                        console.log("Raw WS message:", event.data);
                    }
                };

                ws.onclose = () => {
                    wsBadge.className = "inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-semibold bg-rose-900/60 text-rose-300 border border-rose-500/40";
                    wsBadge.innerHTML = `<span class="w-1.5 h-1.5 mr-1 rounded-full bg-rose-400 animate-pulse"></span>Mất kết nối`;
                    showServerNotice(true);
                    setTimeout(initWebSocket, 3000);
                };

                ws.onerror = () => {
                    showServerNotice(true);
                    ws.close();
                };
            } catch (err) {
                showServerNotice(true);
                setTimeout(initWebSocket, 3000);
            }
        }

        function showToast(message, type = "info") {
            const container = document.getElementById("toast-container");
            const toast = document.createElement("div");
            let bg = "bg-blue-600";
            if (type === "success") bg = "bg-emerald-600";
            if (type === "danger") bg = "bg-rose-600";

            toast.className = `toast ${bg} text-white px-4 py-3 rounded-xl shadow-lg flex justify-between items-center text-xs md:text-sm`;
            toast.innerHTML = `<span>${escapeHtml(message)}</span><button onclick="this.parentElement.remove()" class="text-white hover:text-slate-200 ml-4 font-bold text-base">&times;</button>`;
            container.appendChild(toast);
            setTimeout(() => toast.remove(), 8000);
        }

        function selectedMachine() {
            return currentChildren.find(child => child.id === selectedChildId)?.device?.device_hwid;
        }

        function sendLockCommand() {
            return sendRemoteDeviceCommand(selectedMachine(), "LOCK_MACHINE");
        }

        function sendUnlockCommand() {
            return sendRemoteDeviceCommand(selectedMachine(), "UNLOCK_MACHINE");
        }

        async function sendMessageFrom(inputId) {
            const input = document.getElementById(inputId);
            const message = input.value.trim();
            if (!message) return;
            if (await sendRemoteDeviceCommand(selectedMachine(), "MESSAGE", { message })) input.value = "";
        }

        function sendMessageToChild() {
            return sendMessageFrom("parent-message-input");
        }

        function sendQuickMessage() {
            return sendMessageFrom("parent-quick-msg");
        }

        async function fetchRequests() {
            const container = document.getElementById("requests-container");
            const navBadge = document.getElementById("nav-pending-badge");
            const overviewPendingReq = document.getElementById("overview-pending-req");

            try {
                const response = await consoleFetch(`${API_BASE}/requests/`);
                if (!response.ok) throw new Error("HTTP error " + response.status);
                const data = await response.json();
                container.innerHTML = "";

                const pendingCount = data.filter(r => r.status === "PENDING").length;
                if (navBadge) {
                    if (pendingCount > 0) {
                        navBadge.textContent = pendingCount;
                        navBadge.classList.remove("hidden");
                    } else {
                        navBadge.classList.add("hidden");
                    }
                }
                if (overviewPendingReq) {
                    overviewPendingReq.textContent = `${pendingCount} yêu cầu`;
                }

                if (data.length === 0) {
                    container.innerHTML = "<p class='text-slate-400 text-xs italic py-4 text-center'>Hiện chưa có yêu cầu nào từ máy con.</p>";
                    return;
                }

                data.forEach(req => {
                    const card = document.createElement("div");
                    card.className = "p-4 border rounded-xl transition bg-slate-50/50 hover:bg-slate-50 border-slate-200";

                    let statusBadge = "";
                    if (req.status === "PENDING") {
                        statusBadge = `<span class="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-amber-100 text-amber-800">🟡 Đang chờ duyệt</span>`;
                    } else if (req.status === "APPROVED") {
                        statusBadge = `<span class="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-100 text-emerald-800">🟢 Đã cho phép</span>`;
                    } else {
                        statusBadge = `<span class="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-rose-100 text-rose-800">🔴 Đã từ chối</span>`;
                    }

                    let typeLabel = "📩 Yêu cầu";
                    if (req.request_type.includes("TIME")) typeLabel = "⏳ Xin thêm giờ";
                    else if (req.request_type.includes("WEB")) typeLabel = "🌐 Xin phép mở Website";
                    else if (req.request_type.includes("APP")) typeLabel = "📱 Xin phép mở Phần mềm";

                    let actionHtml = "";
                    if (req.status === "PENDING") {
                        actionHtml = `
                            <div class="mt-3 pt-3 border-t border-slate-200">
                                <div class="flex flex-col sm:flex-row gap-2">
                                    <input type="text" id="feedback-${req.id}" placeholder="Lời dặn dò cho con..." class="flex-1 text-xs border border-slate-300 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-500">
                                    <div class="flex gap-2">
                                        <button onclick="handleDecision(${req.id}, 'APPROVED')" class="bg-emerald-600 hover:bg-emerald-700 text-white font-semibold px-3 py-1.5 rounded-lg text-xs shadow-sm transition">
                                            ✅ Cho phép
                                        </button>
                                        <button onclick="handleDecision(${req.id}, 'REJECTED')" class="bg-rose-600 hover:bg-rose-700 text-white font-semibold px-3 py-1.5 rounded-lg text-xs shadow-sm transition">
                                            ❌ Từ chối
                                        </button>
                                    </div>
                                </div>
                            </div>
                        `;
                    } else if (req.parent_feedback) {
                        actionHtml = `
                            <div class="mt-2 text-xs text-slate-600 bg-white p-2 rounded-lg border border-slate-200">
                                <span class="font-semibold text-slate-700">Lời nhắn từ Phụ huynh:</span> "${escapeHtml(req.parent_feedback)}"
                            </div>
                        `;
                    }

                    card.innerHTML = `
                        <div class="flex items-start justify-between gap-2">
                            <div>
                                <span class="text-[11px] font-semibold uppercase tracking-wider text-slate-500">${typeLabel} · ${escapeHtml(req.child_name || "Hồ sơ cũ")}</span>
                                <h4 class="font-bold text-slate-800 text-sm mt-0.5">${escapeHtml(req.target_detail)}</h4>
                            </div>
                            <div>${statusBadge}</div>
                        </div>
                        <p class="text-xs text-slate-600 mt-2 bg-white p-2.5 rounded-lg border border-slate-100">
                            <span class="font-semibold text-slate-700">Lý do của con:</span> ${escapeHtml(req.reason_from_child)}
                        </p>
                        ${actionHtml}
                    `;
                    container.appendChild(card);
                });
            } catch (error) {
                container.innerHTML = `<p class="text-rose-500 text-xs py-4 text-center">Lỗi khi tải dữ liệu: ${escapeHtml(error.message)}</p>`;
            }
        }

        async function handleDecision(requestId, status) {
            const feedbackInput = document.getElementById(`feedback-${requestId}`);
            const feedback = feedbackInput ? feedbackInput.value.trim() : "";

            try {
                const response = await consoleFetch(`${API_BASE}/requests/${requestId}`, {
                    method: "PATCH",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        status: status,
                        parent_feedback: feedback || (status === "APPROVED" ? "Cha mẹ đã đồng ý!" : "Cha mẹ chưa thể cho phép lúc này.")
                    })
                });

                if (response.ok) {
                    showToast(`Đã ${status === "APPROVED" ? "cho phép" : "từ chối"} yêu cầu #${requestId}!`, "success");
                    fetchRequests();
                    fetchRules();
                    fetchUsageStats();
                }
            } catch (error) {
                alert("Lỗi kết nối tới máy chủ: " + error.message);
            }
        }

        let parentChart = null;

        function updateParentChart(learning, entertainment, social, unclassified) {
            const ctx = document.getElementById("parentUsageChart");
            if (!ctx) return;
            const total = (learning || 0) + (entertainment || 0) + (social || 0) + (unclassified || 0);
            const legendText = document.getElementById("chart-legend-text");
            if (legendText) {
                if (total === 0) {
                    legendText.innerText = "Chưa có hoạt động hôm nay";
                } else {
                    legendText.innerHTML = `📚 <b>${formatUsageSeconds(learning)}</b> • 🎮 <b>${formatUsageSeconds(entertainment)}</b> • 💬 <b>${formatUsageSeconds(social)}</b> • Chưa phân loại <b>${formatUsageSeconds(unclassified)}</b>`;
                }
            }

            const dataValues = total === 0 ? [1] : [learning || 0, entertainment || 0, social || 0, unclassified || 0];
            const bgColors = total === 0 ? ['#e2e8f0'] : ['#10b981', '#f43f5e', '#3b82f6', '#64748b'];
            const labels = total === 0 ? ['Chưa dùng'] : ['Học tập', 'Giải trí', 'Mạng xã hội', 'Chưa phân loại'];

            if (parentChart) {
                parentChart.data.datasets[0].data = dataValues;
                parentChart.data.datasets[0].backgroundColor = bgColors;
                parentChart.data.labels = labels;
                parentChart.update();
            } else if (typeof Chart !== "undefined") {
                parentChart = new Chart(ctx, {
                    type: 'doughnut',
                    data: {
                        labels: labels,
                        datasets: [{
                            data: dataValues,
                            backgroundColor: bgColors,
                            borderWidth: 2,
                            borderColor: '#ffffff',
                            hoverOffset: 4
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: true,
                        cutout: '70%',
                        plugins: {
                            legend: { display: false },
                            tooltip: {
                                callbacks: {
                                    label: function(context) {
                                        if (context.label === "Chưa dùng") return "Chưa có dữ liệu";
                                        return ` ${context.label}: ${formatUsageSeconds(context.raw)}`;
                                    }
                                }
                            }
                        }
                    }
                });
            }
        }

        function refreshVisibleUsageStats() {
            if (!document.hidden && ["overview", "stats"].includes(currentActiveTab)) {
                fetchUsageStats();
            }
        }

        async function fetchUsageStats() {
            const listEl = document.getElementById("usage-list");
            const requestId = ++usageRequestId;
            const childId = selectedChildId;
            try {
                const response = await consoleFetch(`${API_BASE}/usage-stats/${childId ? "?child_id=" + childId : ""}`);
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                const data = await response.json();
                if (requestId !== usageRequestId || childId !== selectedChildId) return;

                document.getElementById("stat-total-time").innerText = data.total_formatted;
                document.getElementById("stat-learning-time").innerText = data.learning_formatted || "0 phút";
                document.getElementById("stat-entertainment-time").innerText = data.entertainment_formatted;

                const overviewUsed = document.getElementById("overview-used-time");
                if (overviewUsed) overviewUsed.textContent = data.total_formatted;

                updateParentChart(
                    data.learning_seconds ?? (data.learning_minutes || 0) * 60,
                    data.entertainment_seconds ?? (data.entertainment_minutes || 0) * 60,
                    data.social_seconds ?? (data.social_minutes || 0) * 60,
                    data.unclassified_seconds ?? 0
                );

                cachedUsageItems = data.items || [];
                renderFilteredUsage();
            } catch (error) {
                if (requestId !== usageRequestId || childId !== selectedChildId) return;
                if (listEl) listEl.innerHTML = `<p class="text-rose-500 text-xs py-2 text-center">Lỗi khi tải báo cáo: ${escapeHtml(error.message)}</p>`;
            }
        }

        function filterUsage(tag, btn) {
            document.querySelectorAll(".usage-filter-btn").forEach(b => {
                b.className = "usage-filter-btn px-3 py-1 rounded-full text-xs font-semibold bg-slate-100 text-slate-600 hover:bg-slate-200";
            });
            btn.className = "usage-filter-btn px-3 py-1 rounded-full text-xs font-semibold bg-emerald-600 text-white";

            currentUsageTag = tag;
            renderFilteredUsage();
        }

        function renderFilteredUsage() {
            const items = currentUsageTag === "ALL"
                ? cachedUsageItems
                : cachedUsageItems.filter(item => item.tag === currentUsageTag);
            renderUsageList(items);
        }

        function renderUsageList(items) {
            const listEl = document.getElementById("usage-list");
            if (!listEl) return;
            listEl.innerHTML = "";

            if (!items || items.length === 0) {
                listEl.innerHTML = `<p class="text-slate-400 text-xs italic py-4 text-center">Chưa có ứng dụng hoặc trang web nào được sử dụng hôm nay.</p>`;
                return;
            }

            items.forEach(item => {
                const row = document.createElement("div");
                
                let remColor = "text-emerald-700 bg-emerald-50 border-emerald-200";
                let barColor = "bg-emerald-600";
                if (item.is_expired) {
                    remColor = "text-rose-700 bg-rose-50 border-rose-300 font-bold";
                    barColor = "bg-rose-500";
                } else if (item.remaining_minutes <= 15 && item.time_limit_minutes > 0) {
                    remColor = "text-amber-700 bg-amber-50 border-amber-300 font-bold";
                    barColor = "bg-amber-500";
                }

                row.className = `p-3.5 rounded-xl border flex flex-col gap-2 ${item.is_expired ? 'bg-rose-50/40 border-rose-200' : 'bg-slate-50 border-slate-200'}`;
                row.innerHTML = `
                    <div class="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                        <div class="flex items-center gap-2">
                            <span class="text-lg">${item.icon}</span>
                            <span class="font-bold text-slate-800 text-xs md:text-sm">${escapeHtml(item.app_name)}</span>
                            <span class="text-[10px] font-semibold px-2 py-0.5 rounded-full border ${item.badge_color}">${item.category}</span>
                        </div>
                        <div class="flex flex-wrap items-center gap-2 text-xs">
                            <span class="text-slate-500">Đã dùng: <strong>${item.duration_formatted}</strong></span>
                            <span>•</span>
                            <span class="text-[11px] px-2.5 py-0.5 rounded-full border ${remColor}">
                                ${item.is_expired ? '🛑 Đã hết giờ (0p)' : '⏳ ' + item.remaining_formatted}
                            </span>
                            <button data-argument="${escapeHtml(item.app_name)}" onclick="openLimitModal(this.dataset.argument, ${item.time_limit_minutes})" class="text-blue-600 hover:text-blue-800 text-xs font-semibold px-2 py-1 bg-white border border-blue-200 rounded-lg shadow-xs">
                                ⚙️ Đặt hạn mức
                            </button>
                        </div>
                    </div>
                    
                    <div class="flex flex-wrap items-center justify-between gap-2 pt-1.5 border-t border-slate-200/50">
                        <div class="flex items-center gap-1 text-[11px] text-slate-500">
                            <span>⚡ Tự điền nhanh:</span>
                            <button data-argument="${escapeHtml(item.app_name)}" onclick="setQuickLimit(this.dataset.argument, 30)" class="px-2 py-0.5 bg-white hover:bg-blue-50 hover:text-blue-600 border border-slate-200 rounded text-[10px] font-semibold">30p</button>
                            <button data-argument="${escapeHtml(item.app_name)}" onclick="setQuickLimit(this.dataset.argument, 45)" class="px-2 py-0.5 bg-white hover:bg-blue-50 hover:text-blue-600 border border-slate-200 rounded text-[10px] font-semibold">45p</button>
                            <button data-argument="${escapeHtml(item.app_name)}" onclick="setQuickLimit(this.dataset.argument, 60)" class="px-2 py-0.5 bg-white hover:bg-blue-50 hover:text-blue-600 border border-slate-200 rounded text-[10px] font-semibold">60p</button>
                            <button data-argument="${escapeHtml(item.app_name)}" onclick="setQuickLimit(this.dataset.argument, 90)" class="px-2 py-0.5 bg-white hover:bg-blue-50 hover:text-blue-600 border border-slate-200 rounded text-[10px] font-semibold">90p</button>
                            <button data-argument="${escapeHtml(item.app_name)}" onclick="setQuickLimit(this.dataset.argument, 120)" class="px-2 py-0.5 bg-white hover:bg-blue-50 hover:text-blue-600 border border-slate-200 rounded text-[10px] font-semibold">120p</button>
                            <button data-argument="${escapeHtml(item.app_name)}" onclick="setQuickLimit(this.dataset.argument, 0)" class="px-2 py-0.5 bg-white hover:bg-slate-100 border border-slate-200 rounded text-[10px] font-semibold text-slate-500">Không GH</button>
                        </div>
                        <div class="flex items-center gap-2 flex-1 max-w-xs">
                            <div class="w-full bg-slate-200 h-1.5 rounded-full overflow-hidden flex-1">
                                <div class="${barColor} h-full rounded-full transition-all" style="width: ${item.percentage}%"></div>
                            </div>
                            <span class="text-[10px] text-slate-400 w-8 text-right">${item.percentage}%</span>
                        </div>
                    </div>
                `;
                listEl.appendChild(row);
            });
        }

        async function setQuickLimit(targetName, mins) {
            try {
                const res = await consoleFetch(`${API_BASE}/rules/`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        rule_type: targetName.includes(".") ? "WEBSITE" : "APP",
                        target_value: targetName,
                        action: "ALLOW",
                        time_limit_minutes: mins
                    })
                });
                if (res.ok) {
                    showToast(`⏱️ Đã đặt hạn mức cho "${targetName}": ${mins > 0 ? mins + ' phút' : 'Không giới hạn'}!`, "success");
                    fetchUsageStats();
                    fetchRules();
                }
            } catch (err) {
                alert("Lỗi cài đặt giới hạn: " + err.message);
            }
        }

        function openLimitModal(targetName, currentLimit) {
            document.getElementById("limitModalTarget").value = targetName;
            document.getElementById("limitModalMinutes").value = currentLimit || 60;
            document.getElementById("limit-modal-target-title").innerText = `Cài đặt giới hạn cho: "${targetName}"`;
            document.getElementById("limit-modal").classList.remove("hidden");
        }

        function closeLimitModal() {
            document.getElementById("limit-modal").classList.add("hidden");
        }

        function fillLimitPreset(mins) {
            document.getElementById("limitModalMinutes").value = mins;
        }

        async function submitCustomLimit(e) {
            e.preventDefault();
            const target = document.getElementById("limitModalTarget").value;
            const mins = parseInt(document.getElementById("limitModalMinutes").value, 10);
            closeLimitModal();
            await setQuickLimit(target, mins);
        }

        async function fetchCurfew() {
            try {
                const res = await consoleFetch(`${API_BASE}/curfew/`);
                if (res.ok) {
                    const data = await res.json();
                    document.getElementById("curfew-bedtime-input").value = data.bedtime;
                    document.getElementById("curfew-wakeup-input").value = data.wakeup_time;
                    document.getElementById("curfew-timezone-input").value =
                        data.timezone || Intl.DateTimeFormat().resolvedOptions().timeZone || "";
                    document.getElementById("curfew-server-time").textContent =
                        `Giờ app kiểm tra lúc tải: ${data.current_time} (${data.timezone || "giờ máy chủ"})`;
                    
                    const badge = document.getElementById("curfew-status-badge");
                    const overviewCurfewText = document.getElementById("overview-curfew-text");
                    const overviewCurfewStatus = document.getElementById("overview-curfew-status");
                    
                    if (overviewCurfewText) {
                        overviewCurfewText.textContent = `${data.bedtime} → ${data.wakeup_time}`;
                    }

                    if (data.is_within_curfew) {
                        if (badge) {
                            badge.className = "inline-flex items-center px-3 py-1 rounded-full text-xs font-semibold bg-rose-100 text-rose-800 border border-rose-300 animate-pulse";
                            badge.textContent = "🌙 Đang trong giờ giới nghiêm";
                        }
                        if (overviewCurfewStatus) {
                            overviewCurfewStatus.className = "text-[10px] text-rose-600 font-bold animate-pulse";
                            overviewCurfewStatus.textContent = "🌙 Đang giới nghiêm";
                        }
                    } else {
                        if (badge) {
                            badge.className = "inline-flex items-center px-3 py-1 rounded-full text-xs font-semibold bg-emerald-100 text-emerald-800 border border-emerald-300";
                            badge.textContent = "🟢 Ngoài giờ giới nghiêm";
                        }
                        if (overviewCurfewStatus) {
                            overviewCurfewStatus.className = "text-[10px] text-emerald-600 font-semibold";
                            overviewCurfewStatus.textContent = "🟢 Bình thường";
                        }
                    }
                }
            } catch (e) {}
        }

        function setCurfewPreset(bedtime, wakeup) {
            document.getElementById("curfew-bedtime-input").value = bedtime;
            document.getElementById("curfew-wakeup-input").value = wakeup;
        }

        async function saveCurfewSettings() {
            const bedtime = document.getElementById("curfew-bedtime-input").value;
            const wakeup = document.getElementById("curfew-wakeup-input").value;
            const timezone = document.getElementById("curfew-timezone-input").value.trim();
            if (!bedtime || !wakeup || !timezone) {
                showToast("Nhập giờ bắt đầu, giờ kết thúc và múi giờ.", "danger");
                return;
            }
            try {
                const res = await consoleFetch(`${API_BASE}/curfew/`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ bedtime, wakeup_time: wakeup, timezone })
                });
                if (!res.ok) {
                    const data = await res.json();
                    const message = typeof data.detail === "string"
                        ? data.detail
                        : "Kiểm tra giờ và múi giờ, ví dụ Asia/Ho_Chi_Minh.";
                    throw new Error(message);
                }
                showToast(`Đã lưu giờ giới nghiêm ${bedtime}–${wakeup} (${timezone}).`, "success");
                await fetchCurfew();
            } catch (error) {
                showToast("Không lưu được giờ giới nghiêm. " + error.message, "danger");
            }
        }

        let currentChildren = [];

        async function fetchChildren() {
            const container = document.getElementById("children-profiles-container");
            const headerActive = document.getElementById("header-active-child-name");
            const overviewChild = document.getElementById("overview-child-name");

            try {
                const res = await consoleFetch(`${API_BASE}/children/`);
                if (!res.ok) return;
                currentChildren = await res.json();

                const overviewStatus = document.getElementById("overview-child-status");
                const active = currentChildren.find(c => c.id === selectedChildId) || currentChildren[0];
                selectedChildId = active?.id ?? null;
                if (active) {
                    if (headerActive) headerActive.textContent = `${active.avatar || '🧒'} ${active.name}`;
                    if (overviewChild) overviewChild.textContent = `${active.avatar || '🧒'} ${active.name}`;
                    if (overviewStatus) {
                        overviewStatus.textContent = active.device?.is_paired ? "Đã ghép nối" : "Chờ ghép nối";
                        overviewStatus.className = "text-[10px] text-emerald-600 font-semibold";
                    }
                } else {
                    if (headerActive) headerActive.textContent = `Chưa có hồ sơ`;
                    if (overviewChild) overviewChild.textContent = `Chưa có hồ sơ`;
                    if (overviewStatus) {
                        overviewStatus.textContent = "Bấm để thêm hồ sơ";
                        overviewStatus.className = "text-[10px] text-slate-400 font-semibold";
                    }
                }

                if (currentChildren.length === 0) {
                    container.innerHTML = `
                        <div class="p-8 text-center text-slate-500 bg-slate-50 border-2 border-dashed border-slate-200 rounded-2xl col-span-full flex flex-col items-center justify-center gap-2">
                            <span class="text-4xl block">🧒</span>
                            <div class="font-bold text-xs text-slate-700">Chưa có hồ sơ của con</div>
                            <p class="text-[11px] text-slate-400 max-w-sm">Phụ huynh hãy tạo hồ sơ ban đầu cho bé để cài đặt tên, mã PIN và giới hạn thời gian.</p>
                            <button onclick="openChildProfileModal()" class="mt-2 px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white rounded-xl text-xs font-bold transition shadow-xs flex items-center gap-1.5">
                                <span>+ Thêm Hồ Sơ Cho Bé</span>
                            </button>
                        </div>
                    `;
                    return;
                }

                container.innerHTML = currentChildren.map(c => {
                    const d = c.device;
                    const paired = d?.is_paired;
                    const selected = c.id === selectedChildId;
                    return `
                        <article class="p-4 rounded-2xl border border-slate-200 bg-slate-50 space-y-3">
                            <div class="flex items-center gap-3">
                                <span class="text-3xl">${escapeHtml(c.avatar || "🧒")}</span>
                                <div>
                                    <h3 class="font-bold text-sm">${escapeHtml(c.name)}</h3>
                                    <p class="text-xs text-slate-600">${c.age} tuổi · ${c.daily_limit_minutes} phút/ngày</p>
                                </div>
                            </div>
                            <p class="text-xs">${escapeHtml(d?.device_name || "Chưa có thiết bị")} · ${paired ? "Đã ghép nối" : "Chờ ghép nối"}</p>
                            <div class="flex flex-wrap gap-2">
                                <button onclick="selectChild(${c.id})" class="px-3 py-1.5 rounded-lg bg-blue-50 text-blue-700 text-xs">${selected ? "Đang xem báo cáo" : "Xem báo cáo"}</button>
                                <button onclick="showChildPairing(${c.id})" class="px-3 py-1.5 rounded-lg bg-slate-200 text-slate-800 text-xs">${paired ? "Đổi máy" : "Mã ghép nối"}</button>
                                ${paired ? `
                                    <button data-hwid="${escapeHtml(d.device_hwid)}" onclick="sendRemoteDeviceCommand(this.dataset.hwid, 'LOCK_MACHINE')" class="px-3 py-1.5 rounded-lg bg-amber-100 text-amber-900 text-xs">Khóa</button>
                                    <button data-hwid="${escapeHtml(d.device_hwid)}" onclick="sendRemoteDeviceCommand(this.dataset.hwid, 'UNLOCK_MACHINE')" class="px-3 py-1.5 rounded-lg bg-emerald-100 text-emerald-900 text-xs">Mở khóa</button>
                                    <button data-hwid="${escapeHtml(d.device_hwid)}" onclick="promptSendMessage(this.dataset.hwid)" class="px-3 py-1.5 rounded-lg bg-blue-50 text-blue-700 text-xs">Nhắn</button>
                                ` : ""}
                                <button onclick="deleteChild(${c.id})" class="px-3 py-1.5 rounded-lg bg-rose-50 text-rose-700 text-xs">Xóa hồ sơ</button>
                            </div>
                        </article>`;
                }).join("");
            } catch (e) {
                if (container) container.innerHTML = `<p class="text-rose-500 text-xs py-2 text-center col-span-full">Lỗi nạp hồ sơ: ${escapeHtml(e.message)}</p>`;
            }
        }

        function openChildProfileModal() {
            document.getElementById("child-profile-modal").classList.remove("hidden");
        }

        function closeChildProfileModal() {
            document.getElementById("child-profile-modal").classList.add("hidden");
        }

        function selectAvatar(emoji, btn) {
            document.getElementById("cpAvatar").value = emoji;
            document.querySelectorAll(".avatar-opt").forEach(b => {
                b.className = "avatar-opt text-2xl p-2 rounded-xl border border-slate-200 hover:bg-slate-50";
            });
            btn.className = "avatar-opt text-2xl p-2 rounded-xl border-2 border-blue-500 bg-blue-50";
        }

        async function saveChildProfile(e) {
            e.preventDefault();
            const name = document.getElementById("cpName").value.trim();
            const age = parseInt(document.getElementById("cpAge").value, 10) || 10;
            const pin = document.getElementById("cpPin").value;
            const deviceName = document.getElementById("cpDevice").value.trim();
            const avatar = document.getElementById("cpAvatar").value || "🧒";
            const limit = parseInt(document.getElementById("cpLimit").value, 10) || 120;

            try {
                const res = await consoleFetch(`${API_BASE}/children/`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        name: name,
                        avatar: avatar,
                        age: age,
                        pin: pin,
                        device_name: deviceName || null,
                        daily_limit_minutes: limit
                    })
                });
                const data = await res.json();
                if (!res.ok) throw new Error(typeof data.detail === "string" ? data.detail : "Kiểm tra lại tên và mã PIN 4 số.");
                e.target.reset();
                closeChildProfileModal();
                showPairingCode(data.device);
                await fetchChildren();
                fetchUsageStats();
            } catch (err) {
                alert("Lỗi lưu hồ sơ: " + err.message);
            }
        }

        function showPairingCode(device) {
            document.getElementById("generated-pairing-code").textContent = device.pairing_code;
            const hostname = new URL(API_BASE).hostname;
            document.getElementById("pairing-server").textContent =
                ["localhost", "127.0.0.1", "[::1]"].includes(hostname)
                    ? "Dùng địa chỉ IP mạng LAN của máy phụ huynh khi ghép nối từ máy khác."
                    : API_BASE;
            document.getElementById("pairing-dialog").showModal();
        }

        async function showChildPairing(childId) {
            const device = currentChildren.find(c => c.id === childId)?.device;
            if (device?.is_paired && !confirm("Đổi máy sẽ ngắt kết nối máy hiện tại. Tiếp tục?")) return;
            if (device?.pairing_code && Date.parse(device.pairing_expires_at + "Z") > Date.now()) {
                showPairingCode(device);
                return;
            }
            try {
                const response = await consoleFetch(`${API_BASE}/children/${childId}/pairing`, { method: "POST" });
                const data = await response.json();
                if (!response.ok) throw new Error(data.detail);
                showPairingCode(data);
                fetchChildren();
            } catch (error) {
                alert("Không thể tạo mã ghép nối: " + error.message);
            }
        }

        async function selectChild(childId) {
            selectedChildId = childId;
            await fetchChildren();
            switchParentTab("stats");
        }

        async function deleteChild(childId) {
            if (!confirm("Bạn có chắc chắn muốn xóa hồ sơ của bé này?")) return;
            try {
                const res = await consoleFetch(`${API_BASE}/children/${childId}`, { method: "DELETE" });
                if (res.ok) {
                    showToast("🗑️ Đã xóa hồ sơ trẻ thành công!", "info");
                    await fetchChildren();
                    fetchUsageStats();
                }
            } catch (err) {
                alert("Lỗi xóa hồ sơ: " + err.message);
            }
        }

        async function fetchAlerts() {
            const container = document.getElementById("alerts-list-container");
            const countBadge = document.getElementById("alerts-count-badge");
            const navAlertsBadge = document.getElementById("nav-alerts-badge");

            try {
                const res = await consoleFetch(`${API_BASE}/alerts/`);
                if (!res.ok) return;
                const alerts = await res.json();

                if (countBadge) countBadge.innerText = alerts.length;
                if (navAlertsBadge) {
                    if (alerts.length > 0) {
                        navAlertsBadge.textContent = alerts.length;
                        navAlertsBadge.classList.remove("hidden");
                    } else {
                        navAlertsBadge.classList.add("hidden");
                    }
                }

                if (!container) return;

                if (alerts.length === 0) {
                    container.innerHTML = `<p class="text-slate-400 text-xs italic py-4 text-center">Chưa có cảnh báo vi phạm nào. </p>`;
                    return;
                }

                container.innerHTML = alerts.map(a => {
                    const timeStr = new Date(a.timestamp.endsWith("Z") || /[+-][0-9]{2}:[0-9]{2}$/.test(a.timestamp)
                        ? a.timestamp : a.timestamp + "Z").toLocaleString("vi-VN");
                    
                    let catBadge = `<span class="text-[9px] bg-blue-100 text-blue-800 border border-blue-200 font-bold px-1.5 py-0.5 rounded">⚠️ Web Lạ Chưa Phép</span>`;
                    if (a.category === "ADULT_WEBSITE") {
                        catBadge = '<span class="text-[10px] bg-rose-600 text-white font-bold px-1.5 py-0.5 rounded">18+</span>';
                    } else if (a.category === "AI_CONTENT_TEXT") {
                        catBadge = `<span class="text-[9px] bg-rose-600 text-white font-bold px-1.5 py-0.5 rounded shadow-xs">🤖 Lọc AI Văn Bản</span>`;
                    } else if (a.category === "AI_CONTENT_IMAGE") {
                        catBadge = `<span class="text-[9px] bg-purple-600 text-white font-bold px-1.5 py-0.5 rounded shadow-xs">🖼️ Lọc AI Màn Hình</span>`;
                    } else if (a.category === "ANTI_TAMPER_ATTEMPT") {
                        catBadge = `<span class="text-[9px] bg-amber-500 text-white font-bold px-1.5 py-0.5 rounded shadow-xs">🔒 Chống Tắt Ngầm</span>`;
                    } else if (a.category === "BLOCKED_APP") {
                        catBadge = `<span class="text-[9px] bg-rose-100 text-rose-800 border border-rose-300 font-bold px-1.5 py-0.5 rounded">🛑 Ứng Dụng Cấm</span>`;
                    }

                    return `
                        <div class="p-3.5 bg-rose-50/70 border border-rose-200 rounded-xl flex flex-col sm:flex-row sm:items-center justify-between gap-2.5">
                            <div class="flex items-center gap-2.5">
                                <span class="text-xl">🛑</span>
                                <div>
                                    <div class="flex items-center gap-2">
                                        <span class="font-bold text-rose-900 text-xs">${escapeHtml(a.target_value)}</span>
                                        ${catBadge}
                                        <span class="text-[10px] bg-rose-200 text-rose-800 px-1.5 py-0.5 rounded font-mono">${timeStr}</span>
                                    </div>
                                    <p class="text-[11px] text-rose-700 mt-0.5">${escapeHtml(a.reason)}${a.child_name ? " · " + escapeHtml(a.child_name) : ""}${a.attempt_count > 1 ? " · " + a.attempt_count + " lần" : ""}</p>
                                </div>
                            </div>
                            <div class="flex items-center gap-1.5 self-end sm:self-auto">
                                ${a.category !== "ADULT_WEBSITE" ? `<button data-argument="${escapeHtml(a.target_value)}" onclick="quickAllowAlert(this.dataset.argument)" class="px-2.5 py-1 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg text-xs font-semibold shadow-xs transition">
                                    ✅ Cho phép
                                </button>
                                <button data-argument="${escapeHtml(a.target_value)}" onclick="quickBlockAlert(this.dataset.argument)" class="px-2.5 py-1 bg-slate-800 hover:bg-slate-900 text-white rounded-lg text-xs font-semibold shadow-xs transition">
                                    ⛔ Chặn
                                </button>
                                ` : ""}
                                <button onclick="deleteAlert(${a.id})" class="p-1 text-slate-400 hover:text-rose-600 transition" title="Xóa cảnh báo">
                                    &times;
                                </button>
                            </div>
                        </div>
                    `;
                }).join("");
            } catch (e) {}
        }

        async function clearAllAlerts() {
            try {
                await consoleFetch(`${API_BASE}/alerts/`, { method: "DELETE" });
                showToast("🧹 Đã làm sạch toàn bộ cảnh báo!", "info");
                fetchAlerts();
            } catch (e) {}
        }

        async function deleteAlert(id) {
            try {
                await consoleFetch(`${API_BASE}/alerts/${id}`, { method: "DELETE" });
                fetchAlerts();
            } catch (e) {}
        }

        async function quickAllowAlert(target) {
            await setQuickLimit(target, 45);
            fetchAlerts();
        }

        async function quickBlockAlert(target) {
            try {
                await consoleFetch(`${API_BASE}/rules/`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        rule_type: target.includes(".") ? "WEBSITE" : "APP",
                        target_value: target,
                        action: "BLOCK"
                    })
                });
                showToast(`⛔ Đã đưa "${target}" vào danh sách chặn!`, "info");
                fetchAlerts();
                fetchRules();
            } catch (e) {}
        }

        async function sendRemoteDeviceCommand(hwid, action, data = {}) {
            if (!hwid) {
                showToast("Hãy chọn hồ sơ đã ghép nối trong mục Hồ sơ trẻ.", "danger");
                return false;
            }
            try {
                const res = await consoleFetch(`${API_BASE}/relay/command`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ target_hwid: hwid, action, data })
                });
                if (!res.ok) {
                    const result = await res.json();
                    throw new Error(typeof result.detail === "string" ? result.detail : "Máy chưa nhận được lệnh.");
                }
                showToast("Đã gửi lệnh tới máy đã chọn.", "success");
                return true;
            } catch (error) {
                showToast(error.message, "danger");
                return false;
            }
        }

        function promptSendMessage(hwid) {
            const message = prompt("Nhập lời nhắn gửi tới máy con:")?.trim();
            if (message) sendRemoteDeviceCommand(hwid, "MESSAGE", { message });
        }

        async function fetchRules() {
            const listEl = document.getElementById("rules-list");
            if (!listEl) return;
            try {
                const res = await consoleFetch(`${API_BASE}/rules/`);
                const rules = await res.json();
                listEl.innerHTML = "";

                if (rules.length === 0) {
                    listEl.innerHTML = `<p class="text-slate-400 text-xs italic col-span-full py-4 text-center">Chưa có quy tắc nào.</p>`;
                    return;
                }

                rules.forEach(r => {
                    const card = document.createElement("div");
                    const isAllow = r.action === "ALLOW";
                    const badgeBg = isAllow ? "bg-emerald-100 text-emerald-800 border-emerald-300"
                        : r.action === "ASK" ? "bg-amber-100 text-amber-800 border-amber-300" : "bg-rose-100 text-rose-800 border-rose-300";
                    const badgeText = isAllow ? "Cho mở" : r.action === "ASK" ? "Cần xin phép" : "Chặn";
                    const icon = r.rule_type === "WEBSITE" ? "🌐" : "📱";

                    let remText = r.time_limit_minutes > 0 ? `${r.remaining_formatted}` : "Vô hạn";

                    card.className = "p-3.5 bg-slate-50 border border-slate-200 rounded-xl flex items-center justify-between text-xs";
                    card.innerHTML = `
                        <div class="flex items-center gap-2 overflow-hidden">
                            <span>${icon}</span>
                            <div>
                                <span class="font-bold text-slate-700 block truncate">${escapeHtml(r.target_value)}</span>
                                <span class="text-[10px] text-slate-500">Giới hạn: ${r.time_limit_minutes > 0 ? r.time_limit_minutes + 'p' : 'Vô hạn'} (${remText})</span>
                            </div>
                        </div>
                        <div class="flex items-center gap-2">
                            <span class="text-[10px] font-semibold px-2 py-0.5 rounded-full border ${badgeBg}">${badgeText}</span>
                            <button data-argument="${escapeHtml(r.id)}" onclick="deleteRule(this.dataset.argument)" class="text-slate-400 hover:text-rose-600 text-xs font-semibold px-1">
                                Xóa
                            </button>
                        </div>
                    `;
                    listEl.appendChild(card);
                });
            } catch (e) {
                listEl.innerHTML = `<p class="text-rose-500 text-xs col-span-full">Lỗi tải quy tắc: ${escapeHtml(e.message)}</p>`;
            }
        }

        async function addRule(e) {
            e.preventDefault();
            const type = document.getElementById("newRuleType").value;
            const target = document.getElementById("newRuleValue").value.trim();
            const action = document.getElementById("newRuleAction").value;
            const limit = parseInt(document.getElementById("newRuleLimit").value, 10);

            if (!target) return;

            try {
                const res = await consoleFetch(`${API_BASE}/rules/`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        rule_type: type,
                        target_value: target,
                        action: action,
                        time_limit_minutes: limit
                    })
                });

                if (!res.ok) {
                    const error = await res.json();
                    throw new Error(typeof error.detail === "string" ? error.detail : "Kiểm tra thông tin quy tắc.");
                }
                showToast(`Đã thêm quy tắc cho "${target}"!`, "success");
                document.getElementById("newRuleValue").value = "";
                fetchRules();
                fetchUsageStats();
            } catch (err) {
                alert("Lỗi thêm quy tắc: " + err.message);
            }
        }

        async function deleteRule(ruleId) {
            if (!confirm("Bạn có chắc muốn xóa quy tắc này?")) return;
            try {
                const res = await consoleFetch(`${API_BASE}/rules/${ruleId}`, { method: "DELETE" });
                if (res.ok) {
                    showToast("Đã xóa quy tắc thành công!", "info");
                    fetchRules();
                    fetchUsageStats();
                }
            } catch (err) {
                alert("Lỗi xóa quy tắc: " + err.message);
            }
        }

        async function handleReset(type) {
            let confirmMsg = "";
            let endpoint = "";

            if (type === "usage") {
                confirmMsg = "Bạn có chắc muốn đặt lại toàn bộ thời gian sử dụng hôm nay về 0?";
                endpoint = "/reset/usage";
            } else if (type === "rules") {
                confirmMsg = "Bạn có chắc muốn đặt lại tất cả quy tắc Web & App về mặc định?";
                endpoint = "/reset/rules";
            } else if (type === "requests") {
                confirmMsg = "Bạn có chắc muốn làm sạch toàn bộ lịch sử yêu cầu?";
                endpoint = "/reset/requests";
            } else if (type === "all") {
                confirmMsg = "CẢNH BÁO: Thao tác này sẽ khôi phục cài đặt gốc toàn bộ hệ thống. Bạn có muốn tiếp tục?";
                endpoint = "/reset/all";
            }

            if (!confirm(confirmMsg)) return;

            try {
                const res = await consoleFetch(`${API_BASE}${endpoint}`, { method: "POST" });
                const result = await res.json();
                if (res.ok) {
                    showToast(result.message || "Thao tác reset thành công!", "success");
                    fetchUsageStats();
                    fetchRules();
                    fetchRequests();
                }
            } catch (err) {
                alert("Lỗi kết nối máy chủ: " + err.message);
            }
        }

        window.addEventListener("DOMContentLoaded", async () => {
            const ruleType = document.getElementById("newRuleType");
            const ruleAction = document.getElementById("newRuleAction");
            ruleType.addEventListener("change", () => {
                const app = ruleType.value === "APP";
                ruleAction.querySelector('option[value="ASK"]').disabled = app;
                if (app && ruleAction.value === "ASK") ruleAction.value = "ALLOW";
            });
            updateSoundUI();
            initWebSocket();
            fetchRequests();
            fetchRules();
            fetchCurfew();
            await fetchChildren();
            fetchAlerts();

            switchParentTab('overview');
            document.addEventListener("visibilitychange", refreshVisibleUsageStats);
            setInterval(refreshVisibleUsageStats, 10000);
        });
