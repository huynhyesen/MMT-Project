const enrollment = new URLSearchParams(location.hash.slice(1)).get("device");
if (enrollment) {
    sessionStorage.setItem("mmtEnrollment", enrollment);
    history.replaceState(null, "", location.pathname + location.search);
}
function enrollmentHeaders() {
    return { Authorization: "Bearer " + (sessionStorage.getItem("mmtEnrollment") || "") };
}
let socketRetry;

const API_BASE = location.origin;
let clockTimezone = "Asia/Ho_Chi_Minh";
let clockFormatter = createClockFormatter(clockTimezone);
const WS_BASE = API_BASE.replace(/^http/, "ws");

        let ws = null;
        let countdownSeconds = -1;
        let usageRequestId = 0;
        let selectedMinutes = 15;
        let alert15Shown = false;
        let alert5Shown = false;
        let currentActiveTab = "overview";

        // --- HỆ THỐNG ÂM THANH THÔNG BÁO "TING" & DESKTOP NOTIFICATION ---
        let soundEnabled = localStorage.getItem("mmt_child_sound") !== "false";

        function updateSoundUI() {
            const btn = document.getElementById("btn-sound-toggle");
            const icon = document.getElementById("sound-icon");
            const text = document.getElementById("sound-text");
            if (!btn || !icon || !text) return;

            if (soundEnabled) {
                icon.textContent = "🔔";
                text.textContent = "Chuông: Bật";
                btn.className = "px-2.5 py-1.5 rounded-xl text-xs font-semibold border transition flex items-center gap-1.5 bg-blue-50 border-blue-200 text-blue-700 hover:bg-blue-100";
            } else {
                icon.textContent = "🔕";
                text.textContent = "Chuông: Tắt";
                btn.className = "px-2.5 py-1.5 rounded-xl text-xs font-semibold border transition flex items-center gap-1.5 bg-slate-50 border-slate-200 text-slate-500 hover:bg-slate-100";
            }
        }

        function toggleSound() {
            soundEnabled = !soundEnabled;
            localStorage.setItem("mmt_child_sound", soundEnabled ? "true" : "false");
            updateSoundUI();
            if (soundEnabled) {
                playNotificationSound('success');
                showToast("🔔 Đã bật âm thanh & Thông báo!", "emerald");
                requestDesktopNotificationPermission();
            } else {
                showToast("🔕 Đã tắt âm thanh thông báo.", "rose");
            }
        }

        function requestDesktopNotificationPermission() {
            if ("Notification" in window && Notification.permission === "default") {
                Notification.requestPermission();
            }
        }

        function playNotificationSound(type = 'success') {
            if (!soundEnabled) return;
            try {
                const AudioCtx = window.AudioContext || window.webkitAudioContext;
                if (!AudioCtx) return;
                const ctx = new AudioCtx();
                if (ctx.state === 'suspended') ctx.resume();
                const now = ctx.currentTime;

                if (type === 'success') {
                    // Âm thanh "Ting-Ting" vui tươi (3 nốt arpeggio vút lên: C5 ~523Hz -> E5 ~659Hz -> G5 ~784Hz)
                    [523.25, 659.25, 783.99].forEach((freq, idx) => {
                        const noteTime = now + idx * 0.12;
                        const osc = ctx.createOscillator();
                        const gain = ctx.createGain();

                        osc.type = 'sine';
                        osc.frequency.setValueAtTime(freq, noteTime);

                        gain.gain.setValueAtTime(0.3, noteTime);
                        gain.gain.exponentialRampToValueAtTime(0.001, noteTime + 0.45);

                        osc.connect(gain);
                        gain.connect(ctx.destination);

                        osc.start(noteTime);
                        osc.stop(noteTime + 0.45);
                    });
                } else if (type === 'ting') {
                    // Âm thanh "Ting" nhẹ khi có lời nhắn từ cha mẹ (880Hz)
                    const osc = ctx.createOscillator();
                    const gain = ctx.createGain();
                    osc.type = 'sine';
                    osc.frequency.setValueAtTime(880, now);
                    osc.frequency.exponentialRampToValueAtTime(1760, now + 0.05);
                    osc.frequency.exponentialRampToValueAtTime(880, now + 0.12);

                    gain.gain.setValueAtTime(0.3, now);
                    gain.gain.exponentialRampToValueAtTime(0.001, now + 0.7);

                    osc.connect(gain);
                    gain.connect(ctx.destination);

                    osc.start(now);
                    osc.stop(now + 0.7);
                } else if (type === 'alert') {
                    // Âm thanh cảnh báo sắp hết giờ (F4 ~349Hz -> D4 ~293Hz)
                    [349.23, 293.66].forEach((freq, idx) => {
                        const noteTime = now + idx * 0.16;
                        const osc = ctx.createOscillator();
                        const gain = ctx.createGain();
                        osc.type = 'sawtooth';
                        osc.frequency.setValueAtTime(freq, noteTime);
                        gain.gain.setValueAtTime(0.2, noteTime);
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

        // Tab meta information
        const tabMeta = {
            overview: { title: "Tổng Quan & Đếm Ngược", desc: "Tự giác cân đối giữa Học tập 📚 và Giải trí 🎮" },
            allowed: { title: "Web & App Được Phép", desc: "Danh sách website và ứng dụng con được phép sử dụng tự do" },
            stats: { title: "Thống Kê Chi Tiết Thời Gian", desc: "Biểu đồ phân loại theo Học tập, Giải trí và Mạng xã hội" },
            request: { title: "Gửi Yêu Cầu Xin Phép", desc: "Xin thêm giờ sử dụng hoặc xin mở web/ứng dụng mới" },
            history: { title: "Hộp Thư & Lịch Sử", desc: "Theo dõi phản hồi và dặn dò từ cha mẹ" }
        };

        // --- CHUYỂN ĐỔI TAB SIDEBAR ---
        function switchChildTab(tabName) {
            currentActiveTab = tabName;

            document.querySelectorAll('.tab-pane').forEach(el => el.classList.add('hidden'));
            const targetPane = document.getElementById(`tab-${tabName}`);
            if (targetPane) targetPane.classList.remove('hidden');

            document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
            const activeBtn = document.getElementById(`nav-${tabName}`);
            if (activeBtn) activeBtn.classList.add('active');

            if (tabMeta[tabName]) {
                document.getElementById('current-tab-title').textContent = tabMeta[tabName].title;
                document.getElementById('current-tab-desc').textContent = tabMeta[tabName].desc;
            }

            const mobileNav = document.getElementById('sidebar-nav');
            if (window.innerWidth < 768 && mobileNav && !mobileNav.classList.contains('hidden')) {
                mobileNav.classList.add('hidden');
            }
        }

        function toggleMobileMenu() {
            const nav = document.getElementById('sidebar-nav');
            nav.classList.toggle('hidden');
        }

        // --- ĐỒNG HỒ THỜI GIAN THỰC ---
        function createClockFormatter(timeZone) {
            return new Intl.DateTimeFormat("vi-VN", {
                timeZone, hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23",
            });
        }

        function updateClock() {
            const clockEl = document.getElementById("realtime-clock");
            if (clockEl) {
                clockEl.textContent = clockFormatter.format(new Date());
                clockEl.title = clockTimezone === "Asia/Ho_Chi_Minh" ? "Giờ Việt Nam (UTC+7)" : clockTimezone;
            }
        }
        setInterval(updateClock, 1000);
        updateClock();

        function showBackendAddress() {
            const port = location.port || (location.protocol === "https:" ? "443" : "80");
            const portElement = document.getElementById("sidebar-port");
            if (portElement) portElement.textContent = port;
            const status = document.getElementById("sidebar-backend-status");
            if (status) status.textContent = `Máy chủ ${location.host}`;
        }

        // --- KHỞI TẠO WEBSOCKET ĐỂ NHẬN LỆNH THỜI GIAN THỰC ---
        function initWebSocket() {
            clearTimeout(socketRetry);
            if (!currentChild) return;
            const wsBadge = document.getElementById("ws-badge");
            try {
                if (ws) {
                    ws.onclose = null;
                    ws.close();
                }
                ws = new WebSocket(`${WS_BASE}/ws/agent/child_pc_01`);

                ws.onopen = () => {
                    wsBadge.className = "inline-flex items-center px-3 py-1 rounded-full text-xs font-semibold bg-emerald-100 text-emerald-800";
                    wsBadge.innerHTML = '<span class="w-2 h-2 mr-1.5 rounded-full bg-emerald-500"></span> Trực tuyến';
                };

                ws.onmessage = (event) => {
                    try {
                        const data = JSON.parse(event.data);
                        handleWebSocketMessage(data);
                    } catch (e) {}
                };

                ws.onclose = () => {
                    wsBadge.className = "inline-flex items-center px-3 py-1 rounded-full text-xs font-semibold bg-slate-100 text-slate-600";
                    wsBadge.innerHTML = '<span class="w-2 h-2 mr-1.5 rounded-full bg-slate-400"></span> Mất kết nối';
                    socketRetry = setTimeout(initWebSocket, 4000);
                };

                ws.onerror = () => {
                    wsBadge.className = "inline-flex items-center px-3 py-1 rounded-full text-xs font-semibold bg-rose-100 text-rose-800";
                    wsBadge.innerHTML = '<span class="w-2 h-2 mr-1.5 rounded-full bg-rose-500"></span> Lỗi mạng';
                };
            } catch (err) {
                socketRetry = setTimeout(initWebSocket, 4000);
            }
        }

        function handleWebSocketMessage(data) {
            const type = data.type || "";
            if (type === "LOCK_MACHINE") {
                playNotificationSound('alert');
                showDesktopNotification("🔒 Thông báo từ Cha Mẹ", "Máy tính đã được tạm khóa!");
                document.getElementById("emergency-lock-overlay").classList.remove("hidden");
                showToast("🔒 Cha Mẹ đã tạm khóa máy tính!", "rose");
            } else if (type === "UNLOCK_MACHINE") {
                playNotificationSound('success');
                showDesktopNotification("🔓 Thông báo từ Cha Mẹ", "Máy tính đã được mở khóa!");
                document.getElementById("emergency-lock-overlay").classList.add("hidden");
                showToast("🔓 Cha Mẹ đã mở khóa máy tính!", "emerald");
            } else if (type === "PARENT_MESSAGE" || type === "MESSAGE") {
                const message = data.message || data.data?.message || "";
                playNotificationSound('ting');
                showDesktopNotification("💬 Lời nhắn từ Cha Mẹ", message || "Cha Mẹ vừa gửi một lời nhắn cho con!");
                const banner = document.getElementById("parent-message-banner");
                document.getElementById("parent-message-text").innerText = message;
                banner.classList.remove("hidden");
                showToast("💬 Cha Mẹ vừa gửi một lời nhắn cho con!", "indigo");
            } else if (type === "REQUEST_DECIDED") {
                const req = data.data;
                const isApproved = req.status === "APPROVED";
                const statusTxt = isApproved ? "✅ ĐÃ ĐỒNG Ý" : "❌ CHƯA ĐỒNG Ý";
                if (isApproved) {
                    playNotificationSound('success');
                    showDesktopNotification("🎉 Cha Mẹ ĐÃ ĐỒNG Ý!", `Yêu cầu "${req.target_detail}" đã được phê duyệt!`);
                } else {
                    playNotificationSound('alert');
                    showDesktopNotification("❌ Cha Mẹ CHƯA ĐỒNG Ý", `Yêu cầu "${req.target_detail}" chưa được chấp thuận.`);
                }
                showToast(`Cha Mẹ ${statusTxt} yêu cầu: ${req.target_detail}`, isApproved ? "emerald" : "rose");
                if (isApproved && req.request_type && req.request_type.includes("TIME")) {
                    alert15Shown = false;
                    alert5Shown = false;
                    const alert15 = document.getElementById("graceful-alert-15m");
                    const alert5 = document.getElementById("graceful-alert-5m");
                    const alertExp = document.getElementById("graceful-alert-expired");
                    if (alert15) alert15.classList.add("hidden");
                    if (alert5) alert5.classList.add("hidden");
                    if (alertExp) alertExp.classList.add("hidden");
                }
                connectWebTracking();
                fetchChildRequests();
                fetchAllowedRules();
                fetchUsageStats();
            } else if (type === "AI_CONTENT_VIOLATION") {
                playNotificationSound('alert');
                showDesktopNotification("Cảnh báo nội dung", data.source || "Cảnh báo từ Agent");
                const alertEl = document.getElementById("ai-content-alert");
                if (alertEl) {
                    document.getElementById("ai-alert-title").innerText = `Cảnh báo nội dung · ${data.source || 'Cửa sổ'}`;
                    document.getElementById("ai-alert-desc").innerText = data.reason || "Agent đã gửi cảnh báo nội dung.";
                    alertEl.classList.remove("hidden");
                }
                showToast(`Cảnh báo nội dung: ${data.source || 'nội dung vi phạm'}`, "rose");
            } else if (type === "CHILD_SWITCHED" || type === "PROFILES_UPDATED") {
                countdownSeconds = -1;
                fetchActiveChild();
                fetchUsageStats();
            } else if (type === "CURFEW_UPDATED") {
                fetchUsageStats();
            } else if (type === "DAILY_RESET_TRIGGERED" || type === "DAILY_RESET") {
                showToast("🌅 Chào ngày mới! Thời gian đã được làm mới tự động.", "emerald");
                countdownSeconds = -1;
                fetchAllowedRules();
                fetchUsageStats();
                fetchChildRequests();
            } else if (type === "USAGE_RESET" || type === "RULES_RESET" || type === "FULL_RESET" || type === "LIMIT_UPDATED") {
                showToast("⚙️ Dữ liệu hệ thống vừa được cập nhật!", "blue");
                countdownSeconds = -1;
                fetchAllowedRules();
                fetchUsageStats();
                fetchChildRequests();
            }
        }

        // --- TOAST NOTIFICATIONS ---
        function showToast(message, color = "blue") {
            const container = document.getElementById("toast-container");
            const toast = document.createElement("div");
            
            const colorClasses = {
                emerald: "bg-emerald-600 text-white",
                rose: "bg-rose-600 text-white",
                amber: "bg-amber-600 text-white",
                indigo: "bg-indigo-600 text-white",
                blue: "bg-blue-600 text-white"
            };

            toast.className = `toast p-3 rounded-xl text-xs font-semibold shadow-md flex items-center justify-between ${colorClasses[color] || colorClasses.blue}`;
            toast.innerHTML = `
                <span>${escapeHtml(message)}</span>
                <button onclick="this.parentElement.remove()" class="ml-2 font-bold opacity-80 hover:opacity-100">&times;</button>
            `;
            container.appendChild(toast);
            setTimeout(() => {
                if (toast.parentElement) toast.remove();
            }, 6000);
        }

        // --- SUB-TABS TRONG FORM XIN PHÉP ---
        let webRequestKind = null;

        function openBrowserRequest() {
            const url = new URL(location.href);
            const kind = url.searchParams.get("web_request");
            if (!["ask", "expired", "daily"].includes(kind)) return;
            const host = url.searchParams.get("host") || "";
            if (kind !== "daily" && !/^[a-z0-9.-]{1,253}$/.test(host)) return;

            url.searchParams.delete("web_request");
            url.searchParams.delete("host");
            history.replaceState(null, "", url);
            switchChildTab("request");
            switchFormTab(kind === "daily" ? "time" : "unlock");
            if (kind !== "daily") {
                webRequestKind = kind;
                document.getElementById("unlock-target").value = host;
                document.getElementById("unlock-type").value = "WEBSITE";
                document.getElementById("unlock-submit-label").textContent =
                    kind === "expired" ? "Xin thêm giờ cho trang này" : "Gửi yêu cầu xin mở trang";
            }
        }

        function switchFormTab(tab) {
            const btnTime = document.getElementById("tab-btn-time");
            const btnUnlock = document.getElementById("tab-btn-unlock");
            const contentTime = document.getElementById("tab-content-time");
            const contentUnlock = document.getElementById("tab-content-unlock");

            if (tab === "time") {
                btnTime.className = "pb-2.5 px-4 text-blue-600 border-b-2 border-blue-600 transition font-bold";
                btnUnlock.className = "pb-2.5 px-4 text-slate-400 hover:text-slate-600 transition";
                contentTime.classList.remove("hidden");
                contentUnlock.classList.add("hidden");
            } else {
                btnUnlock.className = "pb-2.5 px-4 text-emerald-600 border-b-2 border-emerald-600 transition font-bold";
                btnTime.className = "pb-2.5 px-4 text-slate-400 hover:text-slate-600 transition";
                contentUnlock.classList.remove("hidden");
                contentTime.classList.add("hidden");
            }
        }

        function selectTimeOption(mins) {
            selectedMinutes = mins;
            [15, 30, 60].forEach(m => {
                const el = document.getElementById(`time-opt-${m}`);
                if (m === mins) {
                    el.className = "py-2.5 px-3 rounded-xl border border-blue-500 bg-blue-50 text-blue-700 font-bold text-xs text-center transition";
                } else {
                    el.className = "py-2.5 px-3 rounded-xl border border-slate-200 bg-white text-slate-700 font-semibold text-xs text-center hover:bg-slate-50 transition";
                }
            });
        }

        // --- GỬI YÊU CẦU XIN THÊM GIỜ & MỞ KHÓA ---
        async function submitTimeRequest() {
            const reason = document.getElementById("time-reason").value.trim();
            const category = document.getElementById("time-category").value;

            if (!reason) {
                alert("Vui lòng nhập lý do xin thêm giờ để cha mẹ hiểu nhé!");
                return;
            }

            const payload = {
                request_type: "TIME_EXTENSION",
                target_detail: `Xin thêm ${selectedMinutes} phút (${category})`,
                category: category,
                requested_minutes: selectedMinutes,
                reason_from_child: reason
            };

            try {
                const res = await fetch(`${API_BASE}/requests/`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload)
                });
                if (res.ok) {
                    showToast(`Đã gửi yêu cầu xin thêm ${selectedMinutes} phút tới Cha Mẹ! 🚀`, "blue");
                    document.getElementById("time-reason").value = "";
                    fetchChildRequests();
                    switchChildTab('history');
                } else {
                    alert("Không thể gửi yêu cầu, vui lòng thử lại!");
                }
            } catch (err) {
                alert("Lỗi kết nối tới máy chủ Backend!");
            }
        }

        async function submitUnlockRequest() {
            const targetType = document.getElementById("unlock-type").value;
            const target = document.getElementById("unlock-target").value.trim();
            const category = document.getElementById("unlock-category").value;
            const minutes = parseInt(document.getElementById("unlock-minutes").value) || 30;
            const reason = document.getElementById("unlock-reason").value.trim();

            if (!target || !reason) {
                alert("Vui lòng nhập tên Web/Phần mềm và lý do xin mở!");
                return;
            }

            const payload = {
                request_type: webRequestKind === "expired" ? "WEB_TIME_EXTENSION" : `PERMISSION_${targetType}`,
                target_detail: target,
                category: category,
                requested_minutes: minutes,
                reason_from_child: reason
            };

            try {
                const res = await fetch(`${API_BASE}/requests/`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify(payload)
                });
                if (res.ok) {
                    showToast(`Đã gửi yêu cầu xin mở "${target}" tới Cha Mẹ! 📨`, "emerald");
                    document.getElementById("unlock-target").value = "";
                    webRequestKind = null;
                    document.getElementById("unlock-submit-label").textContent = "Gửi yêu cầu xin mở trang";
                    document.getElementById("unlock-reason").value = "";
                    fetchChildRequests();
                    switchChildTab('history');
                } else {
                    const data = await res.json();
                    alert(typeof data.detail === "string" ? data.detail : "Không thể gửi yêu cầu.");
                }
            } catch (err) {
                alert("Lỗi kết nối tới máy chủ Backend!");
            }
        }

        // --- TẢI DANH SÁCH QUY TẮC ĐƯỢC PHÉP (ALLOWED RULES) ---

        async function fetchAllowedRules() {
            try {
                const res = await fetch(`${API_BASE}/rules/`);
                if (!res.ok) return;
                const rules = await res.json();
                const container = document.getElementById("allowed-list");

                const allowed = rules.filter(r => r.action === "ALLOW");

                if (allowed.length === 0) {
                    container.innerHTML = `<div class="p-8 text-center text-slate-400 text-xs col-span-2">Chưa có trang web hoặc ứng dụng nào được mở khóa. Hãy gửi yêu cầu xin phép ở mục Xin Phép!</div>`;
                    return;
                }

                container.innerHTML = allowed.map(r => {
                    const isWeb = r.rule_type === "WEBSITE";
                    const icon = isWeb ? "🌐" : "💻";
                    const remBadgeClass = r.is_expired ? "bg-rose-100 text-rose-800" : (r.remaining_minutes <= 15 ? "bg-amber-100 text-amber-800" : "bg-emerald-100 text-emerald-800");

                    return `
                        <div class="p-3.5 bg-slate-50 border border-slate-200 rounded-2xl flex items-center justify-between hover:bg-slate-100/70 transition">
                            <div class="flex items-center gap-3">
                                <div class="w-10 h-10 rounded-xl bg-white border border-slate-200 flex items-center justify-center text-lg shadow-xs">
                                    ${icon}
                                </div>
                                <div>
                                    <div class="font-bold text-xs text-slate-800 flex items-center gap-1.5">
                                        <span>${escapeHtml(r.target_value)}</span>
                                        <span class="text-[10px] px-1.5 py-0.2 rounded font-semibold ${remBadgeClass}">
                                            ${r.remaining_formatted}
                                        </span>
                                    </div>
                                    <div class="text-[11px] text-slate-400 mt-0.5">
                                        Đã dùng: ${Math.floor(r.used_seconds / 60)}p ${r.used_seconds % 60}s / Giới hạn: ${r.time_limit_minutes > 0 ? r.time_limit_minutes + 'p' : 'Không GH'}
                                    </div>
                                </div>
                            </div>

                            <div>
                                ${isWeb ? `
                                    <button data-target="${escapeHtml(r.target_value)}" onclick="openWebsite(this.dataset.target)" class="inline-flex items-center gap-1 px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white rounded-xl text-xs font-semibold shadow-xs transition">
                                        <span>Mở trang web</span> ↗
                                    </button>
                                ` : `
                                    <button data-target="${escapeHtml(r.target_value)}" onclick="startApprovedAppSession(this.dataset.target)" class="inline-flex items-center gap-1 px-3 py-1.5 bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl text-xs font-semibold shadow-xs transition">
                                        Kiểm tra quyền mở
                                    </button>
                                `}
                            </div>
                        </div>
                    `;
                }).join("");

            } catch (err) {
                console.error("Lỗi nạp rules:", err);
            }
        }

        async function connectWebTracking() {
            const status = document.getElementById("web-tracking-status");
            try {
                const response = await fetch(`${API_BASE}/web-tracking/session`);
                if (!response.ok) {
                    status.textContent = "Chưa kết nối được tiện ích. Mở lại Góc Của Con từ Agent và đăng nhập PIN.";
                    status.classList.remove("hidden");
                    return;
                }
                window.dispatchEvent(new CustomEvent("mmt-web-connect", { detail: await response.json() }));
                setTimeout(() => {
                    status.textContent = document.documentElement.dataset.mmtWebTracking === "connected"
                        ? "Tiện ích MMT đang lọc web và đếm giờ trong hồ sơ trình duyệt này."
                        : "Cài tiện ích MMT cho Chrome hoặc Edge để đếm thời gian và chặn trang 18+ trong trình duyệt.";
                    status.classList.remove("hidden");
                }, 800);
            } catch {
                status.textContent = "Chưa kết nối được bộ theo dõi web.";
                status.classList.remove("hidden");
            }
        }

        async function openWebsite(target) {
            let address;
            try {
                const value = target.trim();
                address = new URL(value.includes("://") ? value : `https://${value}`);
                if (!["http:", "https:"].includes(address.protocol) || address.username || address.password) throw new Error();
            } catch {
                showToast("Nhập địa chỉ web hợp lệ.", "rose");
                return;
            }
            // Open from the click before the permission request so popup blockers allow it.
            const tab = window.open("about:blank", "_blank");
            if (!tab) {
                showToast("Trình duyệt đã chặn tab mới. Hãy cho phép mở tab cho dashboard.", "rose");
                return;
            }
            tab.opener = null;
            try {
                const response = await fetch(`${API_BASE}/check-permission/`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ target: address.hostname, rule_type: "WEBSITE" })
                });
                if (!response.ok) throw new Error("Không thể kiểm tra quyền truy cập.");
                const result = await response.json();
                if (!result.allowed) {
                    const kind = result.requires_permission ? "ask" : result.is_expired
                        ? (result.time_limit_minutes != null ? "expired" : "daily") : "";
                    if (!kind) throw new Error(result.reason);
                    const request = new URL("/child/", API_BASE);
                    request.searchParams.set("web_request", kind);
                    if (kind !== "daily") request.searchParams.set("host", result.target);
                    tab.location.replace(request.href);
                    return;
                }
                tab.location.replace(address.href);
            } catch (error) {
                tab.close();
                showToast(error.message, "rose");
            }
        }

        async function startApprovedAppSession(target) {
            try {
                const response = await fetch(`${API_BASE}/check-permission/`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ target, rule_type: "APP" })
                });
                if (!response.ok) throw new Error("Không thể kiểm tra quyền truy cập.");
                const result = await response.json();
                if (!result.allowed) throw new Error(result.reason);
                showToast(`Bạn có thể mở ${target} trên máy. Agent sẽ ghi nhận khi bạn sử dụng ứng dụng.`, "blue");
            } catch (error) {
                showToast(error.message, "rose");
            }
        }

        // --- QUẢN LÝ HỒ SƠ CON CÁI & ĐĂNG NHẬP MÁY ---
        let currentChild = null;
        let pendingLoginChildId = null;

        async function fetchActiveChild() {
            try {
                const res = await fetch(`${API_BASE}/children/active`);
                if (res.ok) {
                    currentChild = await res.json();
                    if (currentChild && currentChild.name) {
                        document.getElementById("child-avatar").textContent = currentChild.avatar || "🧒";
                        document.getElementById("child-name").textContent = currentChild.name;
                    } else {
                        document.getElementById("child-avatar").textContent = "🧒";
                        document.getElementById("child-name").textContent = "Chưa có hồ sơ";
                    }
                }
            } catch (e) {}
        }

        async function openChildLoginModal() {
            const list = document.getElementById("child-login-list");
            const box = document.getElementById("pin-login-box");
            box.classList.add("hidden");
            pendingLoginChildId = null;
            document.getElementById("childPinInput").value = "";
            document.getElementById("child-login-modal").classList.remove("hidden");
            list.textContent = "Đang tải hồ sơ…";
            try {
                const res = await fetch(`${API_BASE}/children/assigned`, { headers: enrollmentHeaders() });
                if (!res.ok) {
                    list.textContent = "Hãy mở Góc Của Con từ Agent trên máy đã ghép nối.";
                    return;
                }
                const child = await res.json();
                pendingLoginChildId = child.id;
                list.textContent = `${child.avatar} ${child.name}`;
                document.getElementById("pin-prompt-text").textContent = "Nhập mã PIN để đăng nhập";
                box.classList.remove("hidden");
                document.getElementById("childPinInput").focus();
            } catch (error) {
                list.textContent = "Không thể kết nối máy chủ.";
            }
        }

        function closeChildLoginModal() {
            document.getElementById("child-login-modal").classList.add("hidden");
        }

        async function submitChildPinLogin() {
            if (!pendingLoginChildId) return;
            const pin = document.getElementById("childPinInput").value.trim();
            await doChildLogin(pendingLoginChildId, pin);
        }

        async function doChildLogin(childId, pin) {
            try {
                const res = await fetch(`${API_BASE}/children/login`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json", ...enrollmentHeaders() },
                    body: JSON.stringify({ child_id: childId, pin: pin })
                });
                if (res.ok) {
                    const data = await res.json();
                    closeChildLoginModal();
                    showToast(`🎉 ${data.message}`, "emerald");
                    countdownSeconds = -1;
                    await fetchActiveChild();
                    openBrowserRequest();
                    initWebSocket();
                    connectWebTracking();
                    fetchAllowedRules();
                    fetchChildRequests();
                    fetchUsageStats();
                } else {
                    const err = await res.json();
                    alert(err.detail || "Mã PIN không chính xác!");
                }
            } catch (e) {
                alert("Lỗi đăng nhập: " + e.message);
            }
        }

        // --- BIỂU ĐỒ THÂN THIỆN CHO TRẺ ---
        let childChart = null;

        function updateChildChart(learning, entertainment, social, unclassified) {
            const ctx = document.getElementById("childUsageChart");
            if (!ctx) return;
            const total = (learning || 0) + (entertainment || 0) + (social || 0) + (unclassified || 0);
            const legendEl = document.getElementById("child-chart-legend");
            if (legendEl) {
                if (total === 0) {
                    legendEl.textContent = "Chưa có hoạt động hôm nay";
                } else {
                    legendEl.innerHTML = `📚 <b>${formatUsageSeconds(learning)}</b> • 🎮 <b>${formatUsageSeconds(entertainment)}</b> • 💬 <b>${formatUsageSeconds(social)}</b> • Chưa phân loại <b>${formatUsageSeconds(unclassified)}</b>`;
                }
            }

            const dataValues = total === 0 ? [1] : [learning || 0, entertainment || 0, social || 0, unclassified || 0];
            const bgColors = total === 0 ? ['#e2e8f0'] : ['#10b981', '#f43f5e', '#3b82f6', '#64748b'];
            const labels = total === 0 ? ['Chưa dùng'] : ['Học tập', 'Giải trí', 'Mạng xã hội', 'Chưa phân loại'];

            if (childChart) {
                childChart.data.datasets[0].data = dataValues;
                childChart.data.datasets[0].backgroundColor = bgColors;
                childChart.data.labels = labels;
                childChart.update();
            } else if (typeof Chart !== "undefined") {
                childChart = new Chart(ctx, {
                    type: 'doughnut',
                    data: {
                        labels: labels,
                        datasets: [{
                            data: dataValues,
                            backgroundColor: bgColors,
                            borderWidth: 2,
                            borderColor: '#ffffff',
                            hoverOffset: 3
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: true,
                        cutout: '65%',
                        plugins: {
                            legend: { display: false },
                            tooltip: {
                                callbacks: {
                                    label: function(context) {
                                        if (context.label === "Chưa dùng") return "Chưa dùng";
                                        return ` ${context.label}: ${formatUsageSeconds(context.raw)}`;
                                    }
                                }
                            }
                        }
                    }
                });
            }
        }

        // --- ĐỒNG HỒ ĐẾM NGƯỢC TICKING & CẢNH BÁO (COUNTDOWN TIMER) ---
        function renderCountdownDisplay() {
            const displayEl = document.getElementById("countdown-display");
            const statusEl = document.getElementById("countdown-status");
            const alertExp = document.getElementById("graceful-alert-expired");
            if (!displayEl) return;

            if (countdownSeconds < 0) {
                displayEl.textContent = "--:--:--";
                return;
            }

            // Kẹp ở 0 nếu hết giờ
            if (countdownSeconds <= 0) {
                countdownSeconds = 0;
                displayEl.textContent = "00:00:00";
                if (statusEl) {
                    statusEl.className = "mt-1 text-xs font-semibold px-2.5 py-0.5 rounded-full inline-block bg-rose-500 text-white animate-pulse";
                    statusEl.textContent = "🔴 Đã hết thời gian!";
                }
                if (alertExp && alertExp.classList.contains("hidden")) {
                    alertExp.classList.remove("hidden");
                    playNotificationSound('alert');
                    showDesktopNotification("⏰ Đã hết thời gian!", "Thời gian dùng máy tính hôm nay của con đã hết.");
                }
                return;
            }

            // Nếu còn thời gian thì ẩn thông báo hết giờ
            if (alertExp && !alertExp.classList.contains("hidden")) {
                alertExp.classList.add("hidden");
            }

            const hours = Math.floor(countdownSeconds / 3600);
            const minutes = Math.floor((countdownSeconds % 3600) / 60);
            const seconds = countdownSeconds % 60;

            const formatted = `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
            displayEl.textContent = formatted;

            if (statusEl) {
                if (countdownSeconds <= 5 * 60) {
                    statusEl.className = "mt-1 text-xs font-semibold px-2.5 py-0.5 rounded-full inline-block bg-rose-500/30 text-rose-200 animate-pulse";
                    statusEl.textContent = "⚠️ Sắp hết giờ (Còn dưới 5 phút!)";
                    if (!alert5Shown) {
                        document.getElementById("graceful-alert-5m").classList.remove("hidden");
                        alert5Shown = true;
                        playNotificationSound('alert');
                        showDesktopNotification("⚠️ Sắp hết giờ!", "Chỉ còn dưới 5 phút, con hãy lưu bài lại nhé!");
                    }
                } else if (countdownSeconds <= 15 * 60) {
                    statusEl.className = "mt-1 text-xs font-semibold px-2.5 py-0.5 rounded-full inline-block bg-amber-500/30 text-amber-200";
                    statusEl.textContent = "🟡 Chuẩn bị hết giờ (Còn dưới 15 phút)";
                    if (!alert15Shown) {
                        document.getElementById("graceful-alert-15m").classList.remove("hidden");
                        alert15Shown = true;
                        playNotificationSound('alert');
                        showDesktopNotification("🟡 Chuẩn bị hết giờ", "Thời gian dùng máy tính hôm nay chỉ còn dưới 15 phút!");
                    }
                } else {
                    statusEl.className = "mt-1 text-xs font-semibold px-2.5 py-0.5 rounded-full inline-block bg-emerald-500/30 text-emerald-200";
                    statusEl.textContent = "🟢 Thời gian an toàn";
                }
            }
        }

        // --- TẢI DỮ LIỆU THỐNG KÊ SỬ DỤNG (USAGE STATS) ---
        async function fetchUsageStats() {
            const requestId = ++usageRequestId;
            try {
                const res = await fetch(`${API_BASE}/usage-stats/`);
                if (!res.ok) return;
                const data = await res.json();
                if (requestId !== usageRequestId) return;
                if (data.timezone && data.timezone !== clockTimezone) {
                    clockFormatter = createClockFormatter(data.timezone);
                    clockTimezone = data.timezone;
                    updateClock();
                }

                // Thống kê nhanh theo danh mục
                const learnStr = data.learning_formatted || "0 phút";
                const entStr = data.entertainment_formatted || "0 phút";
                const socStr = data.social_formatted || "0 phút";

                document.getElementById("stat-learning-time").textContent = learnStr;
                document.getElementById("stat-entertainment-time").textContent = entStr;
                document.getElementById("stat-social-time").textContent = socStr;

                document.getElementById("quick-learn-time").textContent = learnStr;
                document.getElementById("quick-ent-time").textContent = entStr;
                document.getElementById("quick-soc-time").textContent = socStr;

                updateChildChart(
                    data.learning_seconds ?? (data.learning_minutes || 0) * 60,
                    data.entertainment_seconds ?? (data.entertainment_minutes || 0) * 60,
                    data.social_seconds ?? (data.social_minutes || 0) * 60,
                    data.unclassified_seconds ?? 0
                );

                const totalMins = data.total_minutes || 0;
                document.getElementById("summary-used-time").textContent = data.total_formatted || "0 phút";

                // Hạn mức và thời gian còn lại của con
                const dailyLimit = data.daily_limit_minutes || 120;
                const serverRemainingSec = data.remaining_seconds !== undefined ? data.remaining_seconds : (data.remaining_minutes !== undefined ? data.remaining_minutes * 60 : Math.max(0, (dailyLimit - totalMins) * 60));

                document.getElementById("summary-limit-time").textContent = `${dailyLimit} phút`;

                // Hiển thị nhãn khi vừa được thêm giờ (extension_label)
                const extBadge = document.getElementById("extension-badge");
                if (data.extension_label) {
                    extBadge.textContent = `🏷️ Vừa được thêm: ${data.extension_label}`;
                    extBadge.classList.remove("hidden");
                } else {
                    extBadge.classList.add("hidden");
                }

                const totalSeconds = data.total_seconds ?? totalMins * 60;
                const pct = dailyLimit > 0 ? Math.min(100, Math.round(totalSeconds / (dailyLimit * 60) * 100)) : 0;
                document.getElementById("summary-percentage-text").textContent =
                    `${pct}% · Đã dùng ${formatUsageSeconds(totalSeconds)} / ${dailyLimit} phút`;

                const pBar = document.getElementById("summary-progress-bar");
                pBar.style.width = `${pct}%`;
                pBar.className = pct >= 90 ? "bg-rose-400 h-3 rounded-full transition-all duration-500" : (pct >= 60 ? "bg-amber-400 h-3 rounded-full transition-all duration-500" : "bg-emerald-400 h-3 rounded-full transition-all duration-500");

                countdownSeconds = Math.max(0, serverRemainingSec);
                if (countdownSeconds > 300) {
                    alert5Shown = false;
                    document.getElementById("graceful-alert-5m").classList.add("hidden");
                }
                if (countdownSeconds > 900) {
                    alert15Shown = false;
                    document.getElementById("graceful-alert-15m").classList.add("hidden");
                }
                renderCountdownDisplay();

                // Giờ giới nghiêm Bedtime
                const bedtimeBanner = document.getElementById("bedtime-banner");
                const bHour = data.bedtime_hour || "22:00";
                const wHour = data.wakeup_hour || "06:00";
                const bHourEl = document.getElementById("bedtime-hour-text");
                const wHourEl = document.getElementById("wakeup-hour-text");
                const badgeEl = document.getElementById("bedtime-badge-text");
                if (bHourEl) bHourEl.textContent = bHour;
                if (wHourEl) wHourEl.textContent = wHour;
                if (badgeEl) badgeEl.textContent = `Khóa: ${bHour} → Mở: ${wHour}`;

                if (data.is_bedtime) {
                    bedtimeBanner.classList.remove("hidden");
                    const cdStatus = document.getElementById("countdown-status");
                    if (cdStatus) {
                        cdStatus.textContent = `🌙 Giới nghiêm (Mở lại lúc ${wHour})`;
                        cdStatus.className = "mt-1 text-xs font-semibold px-2.5 py-0.5 rounded-full inline-block bg-indigo-900/60 text-amber-300 border border-amber-300/40";
                    }
                } else {
                    bedtimeBanner.classList.add("hidden");
                }

                // Bảng chi tiết
                const tbody = document.getElementById("usage-table-body");
                if (!data.items || data.items.length === 0) {
                    tbody.innerHTML = `<tr><td colspan="5" class="py-6 text-center text-slate-400">Chưa có ứng dụng hoặc web nào được sử dụng hôm nay.</td></tr>`;
                    return;
                }

                tbody.innerHTML = data.items.map(item => `
                    <tr class="hover:bg-slate-50">
                        <td class="py-2.5 font-semibold text-slate-800 flex items-center gap-2">
                            <span>${item.icon || '📱'}</span>
                            <span>${escapeHtml(item.app_name)}</span>
                        </td>
                        <td class="py-2.5">
                            <span class="px-2 py-0.5 rounded text-[10px] font-bold border ${item.badge_color}">
                                ${item.category}
                            </span>
                        </td>
                        <td class="py-2.5 font-medium text-slate-600">${item.duration_formatted}</td>
                        <td class="py-2.5 text-slate-500">${item.time_limit_minutes > 0 ? item.time_limit_minutes + ' phút' : 'Không GH'}</td>
                        <td class="py-2.5 font-bold ${item.is_expired ? 'text-rose-600' : (item.remaining_minutes <= 15 ? 'text-amber-600' : 'text-emerald-600')}">
                            ${item.remaining_formatted}
                        </td>
                    </tr>
                `).join("");

            } catch (err) {
                console.error("Lỗi nạp usage stats:", err);
            }
        }

        // --- TẢI LỊCH SỬ YÊU CẦU & PHẢN HỒI ---
        async function fetchChildRequests() {
            try {
                const res = await fetch(`${API_BASE}/requests/`);
                if (!res.ok) return;
                const requests = await res.json();
                const container = document.getElementById("requests-history-list");
                const navBadge = document.getElementById("nav-pending-badge");

                if (navBadge) {
                    const pendingCount = requests.filter(r => r.status === "PENDING").length;
                    if (pendingCount > 0) {
                        navBadge.textContent = pendingCount;
                        navBadge.classList.remove("hidden");
                    } else {
                        navBadge.classList.add("hidden");
                    }
                }

                if (requests.length === 0) {
                    container.innerHTML = `<div class="p-8 text-center text-slate-400 text-xs">Chưa có yêu cầu nào được gửi.</div>`;
                    return;
                }

                container.innerHTML = requests.map(r => {
                    let statusBadge = "";
                    if (r.status === "APPROVED") {
                        statusBadge = `<span class="px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-emerald-100 text-emerald-800">✅ ĐÃ ĐỒNG Ý</span>`;
                    } else if (r.status === "EXPIRED") {
                        statusBadge = '<span class="text-xs text-slate-500">Đã hết hạn</span>';
                    } else if (r.status === "REJECTED") {
                        statusBadge = `<span class="px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-rose-100 text-rose-800">❌ CHƯA ĐỒNG Ý</span>`;
                    } else {
                        statusBadge = `<span class="px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-amber-100 text-amber-800">⏳ ĐANG CHỜ PHẢN HỒI</span>`;
                    }

                    return `
                        <div class="p-3.5 bg-slate-50 border border-slate-200 rounded-xl space-y-1.5">
                            <div class="flex items-center justify-between">
                                <span class="font-bold text-xs text-slate-800">${escapeHtml(r.target_detail)}</span>
                                ${statusBadge}
                            </div>
                            <div class="text-[11px] text-slate-500 italic">
                                "Lý do của con: ${escapeHtml(r.reason_from_child || 'Không có lý do')}"
                            </div>
                            ${r.parent_feedback ? `
                                <div class="mt-1 pt-1.5 border-t border-slate-200 text-[11px] font-semibold text-indigo-700 flex items-center gap-1">
                                    <span>💬 Cha Mẹ dặn:</span>
                                    <span>"${escapeHtml(r.parent_feedback)}"</span>
                                </div>
                            ` : ''}
                        </div>
                    `;
                }).join("");

            } catch (err) {
                console.error("Lỗi nạp requests:", err);
            }
        }

        // --- KHỞI TẠO BAN ĐẦU ---
        window.addEventListener("DOMContentLoaded", async () => {
            updateSoundUI();
            showBackendAddress();
            await fetchActiveChild();
            initWebSocket();
            if (!currentChild) openChildLoginModal();
            else {
                openBrowserRequest();
                connectWebTracking();
            }
            fetchAllowedRules();
            fetchUsageStats();
            fetchChildRequests();

            document.addEventListener("visibilitychange", () => {
                if (!document.hidden) fetchUsageStats();
            });

            // Định kỳ cập nhật dữ liệu ngầm mỗi 10 giây
            setInterval(() => {
                if (currentChild) connectWebTracking();
                fetchAllowedRules();
                fetchUsageStats();
            }, 10000);
        });
