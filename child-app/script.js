let API_BASE = "http://127.0.0.1:8008";
        let WS_BASE = "ws://127.0.0.1:8008";

        if (window.location.protocol === "http:" || window.location.protocol === "https:") {
            const host = window.location.hostname || "127.0.0.1";
            const port = window.location.port || (window.location.protocol === "https:" ? "443" : "80");
            const wsProto = window.location.protocol === "https:" ? "wss:" : "ws:";
            API_BASE = `${window.location.protocol}//${host}${window.location.port ? ':' + window.location.port : ''}`;
            WS_BASE = `${wsProto}//${host}${window.location.port ? ':' + window.location.port : ''}`;
        }

        let ws = null;
        let countdownInterval = null;
        let countdownSeconds = -1;
        let lastServerDailyLimit = null;
        let isTickerRunning = false;
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
            check: { title: "Kiểm Tra & Vào Web An Toàn", desc: "Kiểm tra độ an toàn trước khi vào trang web mới" },
            stats: { title: "Thống Kê Chi Tiết Thời Gian", desc: "Biểu đồ phân loại theo Học tập, Giải trí và Mạng xã hội" },
            gamification: { title: "Đổi Việc Tốt Lấy Giờ Chơi", desc: "Hoàn thành nhiệm vụ tốt để tích lũy thêm giờ chơi" },
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
        function updateClock() {
            const now = new Date();
            const timeStr = now.toLocaleTimeString('vi-VN', { hour12: false });
            const clockEl = document.getElementById('realtime-clock');
            if (clockEl) clockEl.textContent = timeStr;
        }
        setInterval(updateClock, 1000);
        updateClock();

        // --- TỰ ĐỘNG DÒ TÌM CỔNG BACKEND HOẠT ĐỘNG ---
        async function autoDetectBackendPort() {
            if (window.location.protocol === "http:" || window.location.protocol === "https:") {
                const host = window.location.hostname || "127.0.0.1";
                const port = window.location.port || (window.location.protocol === "https:" ? "443" : "80");
                const wsProto = window.location.protocol === "https:" ? "wss:" : "ws:";
                API_BASE = `${window.location.protocol}//${host}${window.location.port ? ':' + window.location.port : ''}`;
                WS_BASE = `${wsProto}//${host}${window.location.port ? ':' + window.location.port : ''}`;
                const portEl = document.getElementById("sidebar-port");
                if (portEl) portEl.textContent = port;
                const statusEl = document.getElementById("sidebar-backend-status");
                if (statusEl) statusEl.innerHTML = `<span class="w-1.5 h-1.5 rounded-full bg-emerald-400"></span> Trực tuyến (${host}:${port})`;
                const banner = document.getElementById("server-offline-banner");
                if (banner) banner.classList.add("hidden");
                return;
            }

            const candidatePorts = [8008, 8000, 8001, 8080];
            const currentPort = window.location.port;
            if (currentPort && !candidatePorts.includes(parseInt(currentPort))) {
                candidatePorts.unshift(parseInt(currentPort));
            }

            for (const port of candidatePorts) {
                try {
                    const testUrl = `http://127.0.0.1:${port}/usage-stats/`;
                    const ctrl = new AbortController();
                    const timer = setTimeout(() => ctrl.abort(), 800);
                    const res = await fetch(testUrl, { signal: ctrl.signal });
                    clearTimeout(timer);
                    if (res.ok) {
                        API_BASE = `http://127.0.0.1:${port}`;
                        WS_BASE = `ws://127.0.0.1:${port}`;
                        document.getElementById("sidebar-port").textContent = port;
                        document.getElementById("sidebar-backend-status").innerHTML = `<span class="w-1.5 h-1.5 rounded-full bg-emerald-400"></span> Trực tuyến (Cổng ${port})`;
                        document.getElementById("server-offline-banner").classList.add("hidden");
                        return;
                    }
                } catch (e) {}
            }
            document.getElementById("server-offline-banner").classList.remove("hidden");
            document.getElementById("sidebar-backend-status").innerHTML = `<span class="w-1.5 h-1.5 rounded-full bg-rose-400"></span> Mất kết nối`;
        }

        function changeBackendUrl() {
            const input = document.getElementById("custom-backend-url").value.trim();
            if (input) {
                API_BASE = input.replace(/\/$/, "");
                WS_BASE = API_BASE.replace(/^http/, "ws");
                initWebSocket();
                fetchActiveChild();
                fetchAllowedRules();
                fetchUsageStats();
                fetchTasks();
                fetchChildRequests();
                document.getElementById("server-offline-banner").classList.add("hidden");
            }
        }

        // --- KHỞI TẠO WEBSOCKET ĐỂ NHẬN LỆNH THỜI GIAN THỰC ---
        function initWebSocket() {
            const wsBadge = document.getElementById("ws-badge");
            try {
                if (ws) ws.close();
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
                    setTimeout(initWebSocket, 4000);
                };

                ws.onerror = () => {
                    wsBadge.className = "inline-flex items-center px-3 py-1 rounded-full text-xs font-semibold bg-rose-100 text-rose-800";
                    wsBadge.innerHTML = '<span class="w-2 h-2 mr-1.5 rounded-full bg-rose-500"></span> Lỗi mạng';
                };
            } catch (err) {
                setTimeout(initWebSocket, 4000);
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
            } else if (type === "PARENT_MESSAGE") {
                playNotificationSound('ting');
                showDesktopNotification("💬 Lời nhắn từ Cha Mẹ", data.message || "Cha Mẹ vừa gửi một lời nhắn cho con!");
                const banner = document.getElementById("parent-message-banner");
                document.getElementById("parent-message-text").innerText = data.message || "";
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
                fetchChildRequests();
                fetchAllowedRules();
                fetchUsageStats();
            } else if (type === "AI_CONTENT_VIOLATION") {
                playNotificationSound('alert');
                showDesktopNotification("🤖 AI Content Filter!", `Nội dung "${data.source || 'Cửa sổ'}" đã bị tạm dừng.`);
                const alertEl = document.getElementById("ai-content-alert");
                if (alertEl) {
                    document.getElementById("ai-alert-title").innerText = `🤖 AI FILTER: NỘI DUNG "${data.source || 'Cửa sổ'}" ĐÃ BỊ CHẶN!`;
                    document.getElementById("ai-alert-desc").innerText = data.reason || "Hệ thống AI vừa phát hiện nội dung có thể không phù hợp với lứa tuổi của con.";
                    alertEl.classList.remove("hidden");
                }
                showToast(`🤖 AI Content Filter vừa chặn: ${data.source || 'nội dung vi phạm'}`, "rose");
            } else if (type === "CHILD_SWITCHED" || type === "PROFILES_UPDATED") {
                countdownSeconds = -1;
                lastServerDailyLimit = null;
                fetchActiveChild();
                fetchUsageStats();
            } else if (type === "CURFEW_UPDATED") {
                fetchUsageStats();
            } else if (type === "DAILY_RESET_TRIGGERED") {
                showToast("🌅 Chào ngày mới! Thời gian đã được làm mới tự động.", "emerald");
                countdownSeconds = -1;
                lastServerDailyLimit = null;
                fetchAllowedRules();
                fetchUsageStats();
                fetchTasks();
                fetchChildRequests();
            } else if (type === "USAGE_RESET" || type === "RULES_RESET" || type === "FULL_RESET" || type === "LIMIT_UPDATED") {
                showToast("⚙️ Dữ liệu hệ thống vừa được cập nhật!", "blue");
                countdownSeconds = -1;
                lastServerDailyLimit = null;
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
                <span>${message}</span>
                <button onclick="this.parentElement.remove()" class="ml-2 font-bold opacity-80 hover:opacity-100">&times;</button>
            `;
            container.appendChild(toast);
            setTimeout(() => {
                if (toast.parentElement) toast.remove();
            }, 6000);
        }

        // --- SUB-TABS TRONG FORM XIN PHÉP ---
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
                request_type: `PERMISSION_${targetType}`,
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
                    document.getElementById("unlock-reason").value = "";
                    fetchChildRequests();
                    switchChildTab('history');
                } else {
                    alert("Không thể gửi yêu cầu, vui lòng thử lại!");
                }
            } catch (err) {
                alert("Lỗi kết nối tới máy chủ Backend!");
            }
        }

        // --- TẢI DANH SÁCH QUY TẮC ĐƯỢC PHÉP (ALLOWED RULES) ---
        let allowedRulesCache = [];
        let pendingStrangeTarget = "";

        async function fetchAllowedRules() {
            try {
                const res = await fetch(`${API_BASE}/rules/`);
                if (!res.ok) return;
                const rules = await res.json();
                const container = document.getElementById("allowed-list");

                const allowed = rules.filter(r => r.action === "ALLOW");
                allowedRulesCache = allowed;

                if (allowed.length === 0) {
                    container.innerHTML = `<div class="p-8 text-center text-slate-400 text-xs col-span-2">Chưa có trang web hoặc ứng dụng nào được mở khóa. Hãy gửi yêu cầu xin phép ở mục Xin Phép!</div>`;
                    return;
                }

                container.innerHTML = allowed.map(r => {
                    const isWeb = r.rule_type === "WEBSITE" || r.target_value.includes(".");
                    const icon = isWeb ? "🌐" : "💻";
                    const webUrl = r.target_value.startsWith("http") ? r.target_value : `https://${r.target_value}`;
                    
                    const remBadgeClass = r.is_expired ? "bg-rose-100 text-rose-800" : (r.remaining_minutes <= 15 ? "bg-amber-100 text-amber-800" : "bg-emerald-100 text-emerald-800");

                    return `
                        <div class="p-3.5 bg-slate-50 border border-slate-200 rounded-2xl flex items-center justify-between hover:bg-slate-100/70 transition">
                            <div class="flex items-center gap-3">
                                <div class="w-10 h-10 rounded-xl bg-white border border-slate-200 flex items-center justify-center text-lg shadow-xs">
                                    ${icon}
                                </div>
                                <div>
                                    <div class="font-bold text-xs text-slate-800 flex items-center gap-1.5">
                                        <span>${r.target_value}</span>
                                        <span class="text-[10px] px-1.5 py-0.2 rounded font-semibold ${remBadgeClass}">
                                            ${r.remaining_formatted}
                                        </span>
                                    </div>
                                    <div class="text-[11px] text-slate-400 mt-0.5">
                                        Đã dùng: ${r.used_minutes}p / Giới hạn: ${r.time_limit_minutes > 0 ? r.time_limit_minutes + 'p' : 'Không GH'}
                                    </div>
                                </div>
                            </div>

                            <div>
                                ${isWeb ? `
                                    <button onclick="handleOpenAllowedTarget('${r.target_value}')" class="inline-flex items-center gap-1 px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white rounded-xl text-xs font-semibold shadow-xs transition">
                                        <span>Mở trang web</span> ↗
                                    </button>
                                ` : `
                                    <button onclick="handleOpenAllowedTarget('${r.target_value}')" class="inline-flex items-center gap-1 px-3 py-1.5 bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl text-xs font-semibold shadow-xs transition">
                                        <span>Mở ứng dụng</span> 🚀
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

        // --- THEO DÕI VÀ ĐẾM GIỜ SỬ DỤNG WEB/APP (AI GÁN NHÃN) ---
        let activeUsageSession = null;
        let activeSessionTimer = null;
        let activeSessionSeconds = 0;

        function startActiveUsageTracking(targetName, aiInfo) {
            if (activeSessionTimer) clearInterval(activeSessionTimer);

            activeUsageSession = targetName;
            activeSessionSeconds = 0;

            const banner = document.getElementById("active-tracking-banner");
            if (banner) {
                document.getElementById("active-tracking-title").textContent = targetName;
                const catEl = document.getElementById("active-tracking-category");
                if (catEl) {
                    catEl.innerHTML = `${aiInfo.icon || '📱'} ${aiInfo.category || 'Chưa phân loại'}`;
                    catEl.className = `px-2.5 py-0.5 rounded-full text-[11px] font-bold border ${aiInfo.badge_color || 'bg-blue-100 text-blue-800 border-blue-300'}`;
                }
                document.getElementById("active-tracking-time").textContent = "00:00";
                banner.classList.remove("hidden");
            }

            // Gửi telemetry 5 giây đầu tiên
            sendAppTelemetry(targetName, 5);

            // Bắt đầu đếm giây sử dụng cho phiên này
            activeSessionTimer = setInterval(() => {
                activeSessionSeconds++;
                const mins = Math.floor(activeSessionSeconds / 60);
                const secs = activeSessionSeconds % 60;
                const formatted = `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
                const timeEl = document.getElementById("active-tracking-time");
                if (timeEl) timeEl.textContent = formatted;

                // Mỗi 5 giây gửi telemetry để cộng dồn vào bảng thống kê
                if (activeSessionSeconds % 5 === 0) {
                    sendAppTelemetry(targetName, 5);
                }
            }, 1000);
        }

        async function sendAppTelemetry(appName, durationSec) {
            try {
                await fetch(`${API_BASE}/telemetry/`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        app_name: appName,
                        duration_seconds: durationSec
                    })
                });
                // Cập nhật lại số liệu bảng thống kê
                fetchUsageStats();
            } catch (e) {}
        }

        function stopActiveUsageTracking() {
            if (!activeUsageSession) return;
            if (activeSessionTimer) clearInterval(activeSessionTimer);
            activeSessionTimer = null;
            const banner = document.getElementById("active-tracking-banner");
            if (banner) banner.classList.add("hidden");
            const durationMins = Math.max(1, Math.round(activeSessionSeconds / 60));
            showToast(`⏹️ Đã dừng phiên dùng "${activeUsageSession}". Đã ghi nhận ${durationMins} phút vào bảng thống kê!`, "emerald");
            activeUsageSession = null;
            fetchUsageStats();
            fetchAllowedRules();
        }

        async function handleOpenAllowedTarget(targetValue) {
            try {
                const res = await fetch(`${API_BASE}/check-permission/`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ target: targetValue })
                });
                if (res.ok) {
                    const data = await res.json();
                    if (!data.allowed) {
                        alert(`Không thể mở "${targetValue}": ${data.reason}`);
                        return;
                    }
                    const aiInfo = data.classification || {};
                    const isWeb = targetValue.includes(".") || targetValue.startsWith("http");
                    if (isWeb) {
                        const webUrl = targetValue.startsWith("http") ? targetValue : `https://${targetValue}`;
                        window.open(webUrl, '_blank');
                    }
                    showToast(`✅ Đang mở: ${targetValue} • AI gán nhãn: ${aiInfo.icon || '🏷️'} ${aiInfo.category || ''}`, "emerald");
                    startActiveUsageTracking(targetValue, aiInfo);
                    return;
                }
            } catch (e) {}

            const isWeb = targetValue.includes(".") || targetValue.startsWith("http");
            if (isWeb) {
                const webUrl = targetValue.startsWith("http") ? targetValue : `https://${targetValue}`;
                window.open(webUrl, '_blank');
            }
            startActiveUsageTracking(targetValue, { category: 'Ứng dụng khác', icon: '🌐' });
        }

        // --- KIỂM TRA TRUY CẬP WEBSITE & CẢNH BÁO WEB LẠ ---
        async function checkAndOpenUrl() {
            const input = document.getElementById("check-url-input");
            const rawVal = (input.value || "").trim();
            if (!rawVal) return alert("Vui lòng nhập địa chỉ website hoặc ứng dụng con muốn vào!");

            let domain = rawVal.toLowerCase().replace(/^https?:\/\//, '').replace(/^www\./, '').split('/')[0].split('?')[0];

            // 0. AI Content Filter kiểm tra thời gian thực từ khóa & ngữ nghĩa
            try {
                const aiRes = await fetch(`${API_BASE}/ai/content-check`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ text_content: rawVal, url: domain })
                });
                if (aiRes.ok) {
                    const aiData = await aiRes.json();
                    if (!aiData.is_safe) {
                        const alertEl = document.getElementById("ai-content-alert");
                        if (alertEl) {
                            document.getElementById("ai-alert-title").innerText = `🤖 AI FILTER: NỘI DUNG KHÔNG PHÙ HỢP ("${rawVal}")!`;
                            document.getElementById("ai-alert-desc").innerText = aiData.reason || "Hệ thống AI vừa phát hiện nội dung có thể không phù hợp với lứa tuổi của con.";
                            alertEl.classList.remove("hidden");
                        }
                        showToast(`🚨 AI Content Filter đã chặn: ${rawVal}`, "rose");
                        fetch(`${API_BASE}/alerts/`, {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({
                                target_value: rawVal,
                                reason: `AI Filter chặn: ${aiData.reason}`,
                                category: `AI_CONTENT_${aiData.violation_category || 'TEXT'}`,
                                is_web: true
                            })
                        }).catch(() => {});
                        return;
                    }
                }
            } catch (e) {}

            try {
                // 1. Kiểm tra với Backend xem web/app có được phép không + Lấy nhãn AI
                const res = await fetch(`${API_BASE}/check-permission/`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ target: domain })
                });

                if (res.ok) {
                    const checkResult = await res.json();
                    const aiInfo = checkResult.classification || {};
                    
                    if (checkResult.allowed) {
                        // ĐƯỢC PHÉP: Mở web và đếm giờ sử dụng!
                        document.getElementById("strange-web-alert").classList.add("hidden");
                        let fullUrl = rawVal.startsWith("http") ? rawVal : `https://${domain}`;
                        window.open(fullUrl, '_blank');
                        
                        showToast(`✅ Được phép mở: ${domain} • AI gán nhãn: ${aiInfo.icon || '🏷️'} ${aiInfo.category || ''}`, "emerald");
                        
                        // BẮT ĐẦU ĐẾM GIỜ SỬ DỤNG CHO MỤC NÀY (ACTIVE USAGE TRACKER)
                        startActiveUsageTracking(domain, aiInfo);
                    } else {
                        // KHÔNG ĐƯỢC PHÉP: Cảnh báo web lạ / bị chặn + Nhãn AI
                        pendingStrangeTarget = domain;
                        const alertBox = document.getElementById("strange-web-alert");
                        document.getElementById("strange-alert-title").innerText = `⚠️ CẢNH BÁO: "${domain}" CHƯA ĐƯỢC PHÉP!`;
                        document.getElementById("strange-alert-desc").innerHTML = `
                            ${checkResult.reason || 'Trang web chưa được cha mẹ duyệt.'}<br>
                            <span class="inline-flex items-center gap-1 mt-2 text-[11px] font-bold ${aiInfo.badge_color || ''} px-2.5 py-0.5 rounded-md border">
                                <span>Phân loại AI:</span> <span>${aiInfo.icon || '💻'}</span> <span>${aiInfo.category || 'Chưa phân loại'}</span>
                            </span>
                        `;
                        alertBox.classList.remove("hidden");
                        showToast(`🛑 Đã chặn "${domain}"! ${checkResult.reason}`, "rose");

                        // Gửi alert lên server để cha mẹ thấy tức thì
                        fetch(`${API_BASE}/alerts/`, {
                            method: "POST",
                            headers: { "Content-Type": "application/json" },
                            body: JSON.stringify({
                                target_value: domain,
                                reason: `Trẻ cố truy cập "${domain}" (${aiInfo.category || 'Web lạ'}) nhưng bị chặn: ${checkResult.reason}`,
                                is_web: true
                            })
                        }).catch(() => {});
                    }
                }
            } catch (err) {
                let fullUrl = rawVal.startsWith("http") ? rawVal : `https://${domain}`;
                window.open(fullUrl, '_blank');
            }
        }

        function requestStrangeWebPermission() {
            if (!pendingStrangeTarget) return;
            switchChildTab('request');
            switchFormTab('unlock');
            document.getElementById("unlock-type").value = "WEBSITE";
            document.getElementById("unlock-target").value = pendingStrangeTarget;
            document.getElementById("unlock-reason").value = `Con muốn vào trang "${pendingStrangeTarget}" để học tập và giải trí, mong cha mẹ duyệt cho con nhé!`;
        }

        // --- QUẢN LÝ HỒ SƠ CON CÁI & ĐĂNG NHẬP MÁY ---
        let currentChild = null;
        let allChildrenList = [];
        let pendingLoginChildId = null;

        async function fetchActiveChild() {
            try {
                const res = await fetch(`${API_BASE}/children/active`);
                if (res.ok) {
                    currentChild = await res.json();
                    document.getElementById("child-avatar").textContent = currentChild.avatar || "🧒";
                    document.getElementById("child-name").textContent = currentChild.name || "Bé An";
                }
            } catch (e) {}
        }

        async function openChildLoginModal() {
            try {
                const res = await fetch(`${API_BASE}/children/`);
                if (res.ok) {
                    allChildrenList = await res.json();
                    const listEl = document.getElementById("child-login-list");
                    listEl.innerHTML = allChildrenList.map(c => `
                        <div onclick="selectChildToLogin(${c.id}, '${c.name}', '${c.pin || ''}')" class="cursor-pointer p-4 rounded-2xl border-2 ${currentChild && currentChild.id === c.id ? 'border-blue-500 bg-blue-50/70' : 'border-slate-200 hover:border-blue-300 hover:bg-slate-50'} text-center transition flex flex-col items-center gap-1.5 shadow-xs">
                            <span class="text-4xl p-2 bg-white rounded-2xl shadow-xs border border-slate-100">${c.avatar || '🧒'}</span>
                            <span class="font-bold text-xs text-slate-800">${c.name}</span>
                            <span class="text-[10px] text-slate-500">${c.age} tuổi</span>
                            ${currentChild && currentChild.id === c.id ? '<span class="text-[9px] font-bold text-blue-600 bg-blue-100 px-2 py-0.5 rounded-full mt-1">Đang đăng nhập</span>' : ''}
                        </div>
                    `).join("");
                    document.getElementById("pin-login-box").classList.add("hidden");
                    document.getElementById("childPinInput").value = "";
                    document.getElementById("child-login-modal").classList.remove("hidden");
                }
            } catch (e) {}
        }

        function closeChildLoginModal() {
            document.getElementById("child-login-modal").classList.add("hidden");
        }

        function selectChildToLogin(childId, name, pin) {
            if (!pin) {
                doChildLogin(childId, "");
            } else {
                pendingLoginChildId = childId;
                document.getElementById("pin-prompt-text").innerText = `Nhập mã PIN để đăng nhập với tư cách ${name}:`;
                document.getElementById("pin-login-box").classList.remove("hidden");
                document.getElementById("childPinInput").focus();
            }
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
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ child_id: childId, pin: pin })
                });
                if (res.ok) {
                    const data = await res.json();
                    closeChildLoginModal();
                    showToast(`🎉 ${data.message}`, "emerald");
                    countdownSeconds = -1;
                    lastServerDailyLimit = null;
                    fetchActiveChild();
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

        function updateChildChart(learnM, entM, socM) {
            const ctx = document.getElementById("childUsageChart");
            if (!ctx) return;
            const total = (learnM || 0) + (entM || 0) + (socM || 0);
            const legendEl = document.getElementById("child-chart-legend");
            if (legendEl) {
                if (total === 0) {
                    legendEl.textContent = "Chưa có hoạt động hôm nay";
                } else {
                    legendEl.innerHTML = `📚 <b>${learnM}p</b> • 🎮 <b>${entM}p</b> • 💬 <b>${socM}p</b>`;
                }
            }

            const dataValues = total === 0 ? [1] : [learnM || 0, entM || 0, socM || 0];
            const bgColors = total === 0 ? ['#e2e8f0'] : ['#10b981', '#f43f5e', '#3b82f6'];
            const labels = total === 0 ? ['Chưa dùng'] : ['Học tập', 'Giải trí', 'Mạng xã hội'];

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
                                        if (total === 0) return "Chưa dùng";
                                        return ` ${context.label}: ${context.raw} phút`;
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

        function initCountdownTicker() {
            if (isTickerRunning) return;
            isTickerRunning = true;

            setInterval(() => {
                if (countdownSeconds > 0) {
                    countdownSeconds--;
                }
                renderCountdownDisplay();
            }, 1000);
        }

        // --- TẢI DỮ LIỆU THỐNG KÊ SỬ DỤNG (USAGE STATS) ---
        async function fetchUsageStats() {
            try {
                const res = await fetch(`${API_BASE}/usage-stats/`);
                if (!res.ok) return;
                const data = await res.json();

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

                updateChildChart(data.learning_minutes, data.entertainment_minutes, data.social_minutes);

                const totalMins = data.total_minutes || 0;
                document.getElementById("summary-used-time").textContent = `${totalMins} phút`;

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

                // Cập nhật thanh tiến độ theo hạn mức thực tế
                const pct = dailyLimit > 0 ? Math.min(100, Math.round((totalMins / dailyLimit) * 100)) : 0;
                document.getElementById("summary-percentage-text").textContent = `${pct}% (Đã dùng ${totalMins}/${dailyLimit} phút)`;

                const pBar = document.getElementById("summary-progress-bar");
                pBar.style.width = `${pct}%`;
                pBar.className = pct >= 90 ? "bg-rose-400 h-3 rounded-full transition-all duration-500" : (pct >= 60 ? "bg-amber-400 h-3 rounded-full transition-all duration-500" : "bg-emerald-400 h-3 rounded-full transition-all duration-500");

                // ĐỒNG BỘ ĐỒNG HỒ ĐẾM NGƯỢC (CHẠY LIÊN TỤC VỀ 0, TUYỆT ĐỐI KHÔNG BỊ RESET MỖI PHÚT)
                if (countdownSeconds < 0) {
                    // Lần đầu tải trang: Khởi tạo chính xác số giây còn lại từ server
                    countdownSeconds = Math.max(0, serverRemainingSec);
                    lastServerDailyLimit = dailyLimit;
                    renderCountdownDisplay();
                } else if (lastServerDailyLimit !== null && dailyLimit > lastServerDailyLimit) {
                    // Phụ huynh vừa duyệt thêm giờ: cộng dồn đúng số giây được duyệt vào đồng hồ hiện tại
                    const addedSec = (dailyLimit - lastServerDailyLimit) * 60;
                    countdownSeconds += addedSec;
                    lastServerDailyLimit = dailyLimit;
                    renderCountdownDisplay();
                } else if (lastServerDailyLimit !== null && dailyLimit < lastServerDailyLimit) {
                    // Phụ huynh giảm hạn mức: cập nhật lại theo server
                    countdownSeconds = Math.max(0, serverRemainingSec);
                    lastServerDailyLimit = dailyLimit;
                    renderCountdownDisplay();
                } else if (serverRemainingSec <= 0) {
                    // Server xác nhận đã hết giờ hoàn toàn: kẹp về 00:00:00
                    countdownSeconds = 0;
                    renderCountdownDisplay();
                } else {
                    // Khi đang đếm bình thường: Giữ nguyên giây đang đếm, chỉ đồng bộ nếu lệch quá lớn (>45s) do máy ngủ
                    const drift = Math.abs(countdownSeconds - serverRemainingSec);
                    if (drift > 45 && serverRemainingSec < countdownSeconds) {
                        countdownSeconds = serverRemainingSec;
                        renderCountdownDisplay();
                    }
                }

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
                            <span>${item.app_name}</span>
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

        // --- TẢI DANH SÁCH VIỆC TỐT (GAMIFICATION) ---
        async function fetchTasks() {
            try {
                const res = await fetch(`${API_BASE}/tasks/`);
                if (!res.ok) return;
                const tasks = await res.json();
                const container = document.getElementById("tasks-list");
                const navBadge = document.getElementById("nav-tasks-badge");

                if (navBadge) {
                    const activeCount = tasks.filter(t => t.status === "TODO").length;
                    if (activeCount > 0) {
                        navBadge.textContent = activeCount;
                        navBadge.classList.remove("hidden");
                    } else {
                        navBadge.classList.add("hidden");
                    }
                }

                if (tasks.length === 0) {
                    container.innerHTML = `
                        <div class="p-8 text-center text-slate-400 text-xs">
                            <span class="text-4xl block mb-2">🌟</span>
                            Hiện tại chưa có nhiệm vụ nào. Con hãy nhờ cha mẹ giao việc tốt ở Trạm điều khiển nhé!
                        </div>
                    `;
                    return;
                }

                container.innerHTML = tasks.map(t => {
                    let actionHtml = "";
                    if (t.status === "TODO") {
                        actionHtml = `
                            <button onclick="markTaskDone(${t.id})" class="px-3 py-1.5 bg-amber-500 hover:bg-amber-600 text-white rounded-xl text-xs font-bold shadow-xs transition flex items-center gap-1">
                                <span>Báo đã làm xong</span> 🏆
                            </button>
                        `;
                    } else if (t.status === "COMPLETED_WAITING_APPROVAL") {
                        actionHtml = `
                            <span class="px-3 py-1 bg-amber-100 text-amber-800 rounded-xl text-xs font-semibold">
                                Đang chờ cha mẹ duyệt ⏳
                            </span>
                        `;
                    } else if (t.status === "APPROVED") {
                        actionHtml = `
                            <span class="px-3 py-1 bg-emerald-100 text-emerald-800 rounded-xl text-xs font-bold">
                                Đã nhận +${t.reward_minutes} phút 🎉
                            </span>
                        `;
                    }

                    return `
                        <div class="p-3.5 bg-slate-50 border border-slate-200 rounded-2xl flex items-center justify-between hover:bg-slate-100/70 transition">
                            <div class="flex items-center gap-3">
                                <div class="w-10 h-10 rounded-xl bg-amber-100 text-amber-700 flex items-center justify-center text-lg font-bold">
                                    +${t.reward_minutes}p
                                </div>
                                <div>
                                    <div class="font-bold text-xs text-slate-800">${t.title}</div>
                                    <div class="text-[11px] text-slate-400 mt-0.5">${t.description || "Làm tốt để nhận thêm giờ chơi!"}</div>
                                </div>
                            </div>
                            <div>
                                ${actionHtml}
                            </div>
                        </div>
                    `;
                }).join("");

            } catch (err) {
                console.error("Lỗi nạp tasks:", err);
            }
        }

        async function markTaskDone(taskId) {
            try {
                const res = await fetch(`${API_BASE}/tasks/${taskId}/complete`, {
                    method: "PATCH"
                });
                if (res.ok) {
                    showToast("🎉 Giỏi lắm! Đã báo hoàn thành việc tốt cho Cha Mẹ.", "amber");
                    fetchTasks();
                } else {
                    alert("Không thể cập nhật việc tốt.");
                }
            } catch (err) {
                alert("Lỗi kết nối máy chủ!");
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
                    } else if (r.status === "REJECTED") {
                        statusBadge = `<span class="px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-rose-100 text-rose-800">❌ CHƯA ĐỒNG Ý</span>`;
                    } else {
                        statusBadge = `<span class="px-2.5 py-0.5 rounded-full text-[10px] font-bold bg-amber-100 text-amber-800">⏳ ĐANG CHỜ PHẢN HỒI</span>`;
                    }

                    return `
                        <div class="p-3.5 bg-slate-50 border border-slate-200 rounded-xl space-y-1.5">
                            <div class="flex items-center justify-between">
                                <span class="font-bold text-xs text-slate-800">${r.target_detail}</span>
                                ${statusBadge}
                            </div>
                            <div class="text-[11px] text-slate-500 italic">
                                "Lý do của con: ${r.reason_from_child || 'Không có lý do'}"
                            </div>
                            ${r.parent_feedback ? `
                                <div class="mt-1 pt-1.5 border-t border-slate-200 text-[11px] font-semibold text-indigo-700 flex items-center gap-1">
                                    <span>💬 Cha Mẹ dặn:</span>
                                    <span>"${r.parent_feedback}"</span>
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
            initCountdownTicker();
            await autoDetectBackendPort();
            initWebSocket();
            fetchActiveChild();
            fetchAllowedRules();
            fetchUsageStats();
            fetchTasks();
            fetchChildRequests();

            // Định kỳ cập nhật dữ liệu ngầm mỗi 10 giây
            setInterval(() => {
                fetchAllowedRules();
                fetchUsageStats();
            }, 10000);
        });
