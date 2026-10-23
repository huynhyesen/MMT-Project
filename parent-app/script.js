let API_BASE = "http://127.0.0.1:8008";
        let WS_URL = "ws://127.0.0.1:8008/ws/agent/parent_dashboard";

        if (window.location.protocol === "http:" || window.location.protocol === "https:") {
            const host = window.location.hostname || "127.0.0.1";
            const port = window.location.port || (window.location.protocol === "https:" ? "443" : "80");
            const wsProto = window.location.protocol === "https:" ? "wss:" : "ws:";
            API_BASE = `${window.location.protocol}//${host}${window.location.port ? ':' + window.location.port : ''}`;
            WS_URL = `${wsProto}//${host}${window.location.port ? ':' + window.location.port : ''}/ws/agent/parent_dashboard`;
        }

        let ws = null;
        let cachedUsageItems = [];
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
            'gamification': { title: '🏆 Đổi Việc Tốt Lấy Giờ Chơi', desc: 'Giao bài tập hoặc việc nhà để thưởng thêm thời gian cho con' },
            'stats': { title: '📊 Thống Kê & Giới Hạn', desc: 'Thống kê các app/web thực sự sử dụng với nhãn AI và tự điền giới hạn' },
            'rules': { title: '🛡️ Quản Lý Quy Tắc Web / App', desc: 'Danh sách các trang web / phần mềm đang được Cho phép hoặc Chặn' },
            'curfew': { title: '🌙 Khung Giờ Giới Nghiêm', desc: 'Tự động vô hiệu hóa máy ban đêm và mở lại vào sáng hôm sau' },
            'alerts': { title: '🚨 Nhật Ký Cảnh Báo & Lọc AI', desc: 'Phát hiện nội dung không phù hợp qua AI và cảnh báo can thiệp Anti-Tamper' },
            'devices': { title: '💻 Quản Lý Thiết Bị & Ghép Nối (Cloud WAN)', desc: 'Ghép nối máy con từ xa theo mã HWID, điều khiển qua Cloud Relay và bảo vệ chống tắt' },
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
        }

        function toggleMobileMenu() {
            const nav = document.getElementById('sidebar-nav');
            if (nav) nav.classList.toggle('hidden');
        }

        async function autoDetectBackendPort() {
            if (window.location.protocol === "file:") {
                const ports = [8008, 8000, 8001, 8080];
                for (const p of ports) {
                    try {
                        const res = await fetch(`http://127.0.0.1:${p}/`, { signal: AbortSignal.timeout(400) });
                        if (res.ok) {
                            API_BASE = `http://127.0.0.1:${p}`;
                            WS_URL = `ws://127.0.0.1:${p}/ws/agent/parent_dashboard`;
                            const customInput = document.getElementById("custom-backend-url");
                            if (customInput) customInput.value = API_BASE;
                            return true;
                        }
                    } catch (e) {}
                }
            }
            return false;
        }

        function changeBackendUrl() {
            const input = document.getElementById("custom-backend-url");
            if (input && input.value.trim()) {
                let target = input.value.trim();
                if (!target.startsWith("http")) target = "http://" + target;
                API_BASE = target;
                const wsHost = target.replace("http://", "").replace("https://", "");
                WS_URL = `ws://${wsHost}/ws/agent/parent_dashboard`;
            }
            initWebSocket();
            fetchRequests();
            fetchTasks();
            fetchUsageStats();
            fetchRules();
            fetchChildren();
            fetchCurfew();
            fetchAlerts();
            fetchDevices();
        }

        function showServerNotice(show) {
            const banner = document.getElementById("server-offline-banner");
            if (banner) {
                if (show) banner.classList.remove("hidden");
                else banner.classList.add("hidden");
            }
            const customInput = document.getElementById("custom-backend-url");
            if (customInput && !customInput.value) {
                customInput.value = API_BASE;
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
                            fetchDevices();
                        } else if (data.type === "PROFILES_UPDATED" || data.type === "CHILD_SWITCHED") {
                            fetchChildren();
                            fetchUsageStats();
                            fetchDevices();
                        } else if (data.type === "CURFEW_UPDATED") {
                            fetchCurfew();
                        } else if (data.type === "RULES_UPDATED") {
                            fetchRules();
                            fetchUsageStats();
                        } else if (data.type === "TASK_WAITING_APPROVAL") {
                            playNotificationSound('ting');
                            showDesktopNotification("🏆 Bé hoàn thành việc tốt!", `Bé đã làm xong: "${data.title}" (+${data.reward_minutes} phút)`);
                            showToast(`🏆 Bé đã hoàn thành: "${data.title}"! Hãy duyệt để thưởng +${data.reward_minutes} phút cho con.`, "success");
                            fetchTasks();
                        } else if (data.type === "REQUEST_DECIDED") {
                            fetchRequests();
                            fetchRules();
                            fetchUsageStats();
                        } else if (data.type === "USAGE_RESET" || data.type === "DAILY_RESET_TRIGGERED") {
                            fetchUsageStats();
                            fetchRules();
                            fetchTasks();
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
            toast.innerHTML = `<span>${message}</span><button onclick="this.parentElement.remove()" class="text-white hover:text-slate-200 ml-4 font-bold text-base">&times;</button>`;
            container.appendChild(toast);
            setTimeout(() => toast.remove(), 8000);
        }

        function sendLockCommand() {
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ type: "LOCK_MACHINE" }));
                showToast("🔒 Đã gửi lệnh khóa máy đến con!", "info");
            } else {
                fetch(`${API_BASE}/control/lock`, { method: "POST" })
                    .then(() => showToast("🔒 Đã gửi lệnh khóa máy đến con!", "info"))
                    .catch(() => alert("Chưa kết nối được máy chủ!"));
            }
        }

        function sendUnlockCommand() {
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ type: "UNLOCK_MACHINE" }));
                showToast("🔓 Đã gửi lệnh mở khóa máy cho con!", "success");
            } else {
                fetch(`${API_BASE}/control/unlock`, { method: "POST" })
                    .then(() => showToast("🔓 Đã gửi lệnh mở khóa máy cho con!", "success"))
                    .catch(() => alert("Chưa kết nối được máy chủ!"));
            }
        }

        function sendMessageToChild() {
            const input = document.getElementById("parent-message-input");
            const msg = input.value.trim();
            if (!msg) return alert("Vui lòng nhập lời nhắn!");
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ type: "PARENT_MESSAGE", message: msg }));
                showToast(`💬 Đã gửi lời nhắn: "${msg}"`, "info");
                input.value = "";
            } else {
                fetch(`${API_BASE}/control/message`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ message: msg })
                }).then(() => {
                    showToast(`💬 Đã gửi lời nhắn: "${msg}"`, "info");
                    input.value = "";
                }).catch(() => alert("Chưa kết nối được máy chủ!"));
            }
        }

        function sendQuickMessage() {
            const input = document.getElementById("parent-quick-msg");
            const msg = input.value.trim();
            if (!msg) return alert("Vui lòng nhập lời nhắn!");
            if (ws && ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ type: "PARENT_MESSAGE", message: msg }));
                showToast(`💬 Đã gửi lời nhắn: "${msg}"`, "info");
                input.value = "";
            } else {
                fetch(`${API_BASE}/control/message`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ message: msg })
                }).then(() => {
                    showToast(`💬 Đã gửi lời nhắn: "${msg}"`, "info");
                    input.value = "";
                }).catch(() => alert("Chưa kết nối được máy chủ!"));
            }
        }

        async function fetchRequests() {
            const container = document.getElementById("requests-container");
            const navBadge = document.getElementById("nav-pending-badge");
            const overviewPendingReq = document.getElementById("overview-pending-req");

            try {
                const response = await fetch(`${API_BASE}/requests/`);
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
                                <span class="font-semibold text-slate-700">Lời nhắn từ Phụ huynh:</span> "${req.parent_feedback}"
                            </div>
                        `;
                    }

                    card.innerHTML = `
                        <div class="flex items-start justify-between gap-2">
                            <div>
                                <span class="text-[11px] font-semibold uppercase tracking-wider text-slate-500">${typeLabel}</span>
                                <h4 class="font-bold text-slate-800 text-sm mt-0.5">${req.target_detail}</h4>
                            </div>
                            <div>${statusBadge}</div>
                        </div>
                        <p class="text-xs text-slate-600 mt-2 bg-white p-2.5 rounded-lg border border-slate-100">
                            <span class="font-semibold text-slate-700">Lý do của con:</span> ${req.reason_from_child}
                        </p>
                        ${actionHtml}
                    `;
                    container.appendChild(card);
                });
            } catch (error) {
                container.innerHTML = `<p class="text-rose-500 text-xs py-4 text-center">Lỗi khi tải dữ liệu: ${error.message}</p>`;
            }
        }

        async function handleDecision(requestId, status) {
            const feedbackInput = document.getElementById(`feedback-${requestId}`);
            const feedback = feedbackInput ? feedbackInput.value.trim() : "";

            try {
                const response = await fetch(`${API_BASE}/requests/${requestId}`, {
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

        async function fetchTasks() {
            const container = document.getElementById("tasks-container");
            try {
                const res = await fetch(`${API_BASE}/tasks/`);
                const tasks = await res.json();
                container.innerHTML = "";

                if (tasks.length === 0) {
                    container.innerHTML = `<p class="text-slate-400 text-xs italic py-4 text-center">Chưa có nhiệm vụ nào được tạo. Hãy tạo việc tốt cho con bằng form phía trên!</p>`;
                    return;
                }

                tasks.forEach(t => {
                    const row = document.createElement("div");
                    row.className = "p-3 bg-slate-50 border border-slate-200 rounded-xl flex items-center justify-between gap-3 text-xs";
                    
                    let statusBadge = "";
                    let actionBtn = "";
                    if (t.status === "TODO") {
                        statusBadge = `<span class="px-2 py-0.5 rounded-full bg-slate-200 text-slate-700 font-semibold text-[10px]">⏳ Chờ con làm</span>`;
                    } else if (t.status === "COMPLETED_WAITING_APPROVAL") {
                        statusBadge = `<span class="px-2 py-0.5 rounded-full bg-amber-100 text-amber-800 font-bold text-[10px] animate-pulse">🟡 Đã xong (Chờ duyệt)</span>`;
                        actionBtn = `<button onclick="approveTask(${t.id})" class="px-2.5 py-1 bg-emerald-600 hover:bg-emerald-700 text-white font-bold rounded-lg text-xs shadow-sm transition">✅ Duyệt & Thưởng +${t.reward_minutes}p</button>`;
                    } else {
                        statusBadge = `<span class="px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-800 font-bold text-[10px]">🟢 Đã thưởng +${t.reward_minutes}p</span>`;
                    }

                    row.innerHTML = `
                        <div class="flex items-center gap-2.5">
                            <span class="text-base">🏆</span>
                            <div>
                                <h4 class="font-bold text-slate-800">${t.title}</h4>
                                <p class="text-[11px] text-slate-500">${t.description || 'Nhiệm vụ rèn luyện'} • Thưởng: <strong>+${t.reward_minutes} phút</strong></p>
                            </div>
                        </div>
                        <div class="flex items-center gap-2">
                            ${statusBadge}
                            ${actionBtn}
                            <button onclick="deleteTask(${t.id})" class="text-slate-400 hover:text-rose-600 text-xs font-semibold ml-1">&times;</button>
                        </div>
                    `;
                    container.appendChild(row);
                });
            } catch (e) {
                container.innerHTML = `<p class="text-rose-500 text-xs py-2 text-center">Lỗi tải nhiệm vụ: ${e.message}</p>`;
            }
        }

        async function createTask(e) {
            e.preventDefault();
            const title = document.getElementById("taskTitle").value.trim();
            const reward = parseInt(document.getElementById("taskReward").value, 10);
            if (!title) return;

            try {
                const res = await fetch(`${API_BASE}/tasks/`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ title: title, reward_minutes: reward })
                });
                if (res.ok) {
                    showToast(`Đã tạo việc tốt "${title}" (+${reward}p) thành công!`, "success");
                    document.getElementById("taskTitle").value = "";
                    fetchTasks();
                }
            } catch (err) {
                alert("Lỗi tạo nhiệm vụ: " + err.message);
            }
        }

        async function approveTask(id) {
            try {
                const res = await fetch(`${API_BASE}/tasks/${id}/approve`, { method: "PATCH" });
                if (res.ok) {
                    showToast("Đã duyệt và cộng thêm phút sử dụng cho con!", "success");
                    fetchTasks();
                    fetchRules();
                    fetchUsageStats();
                }
            } catch (err) {
                alert("Lỗi duyệt nhiệm vụ: " + err.message);
            }
        }

        async function deleteTask(id) {
            if (!confirm("Bạn có chắc muốn xóa nhiệm vụ này?")) return;
            try {
                const res = await fetch(`${API_BASE}/tasks/${id}`, { method: "DELETE" });
                if (res.ok) {
                    showToast("Đã xóa nhiệm vụ!", "info");
                    fetchTasks();
                }
            } catch (err) {
                alert("Lỗi xóa nhiệm vụ: " + err.message);
            }
        }

        let parentChart = null;

        function updateParentChart(learnM, entM, socM) {
            const ctx = document.getElementById("parentUsageChart");
            if (!ctx) return;
            const total = (learnM || 0) + (entM || 0) + (socM || 0);
            const legendText = document.getElementById("chart-legend-text");
            if (legendText) {
                if (total === 0) {
                    legendText.innerText = "Chưa có hoạt động hôm nay";
                } else {
                    legendText.innerHTML = `📚 <b>${learnM}p</b> • 🎮 <b>${entM}p</b> • 💬 <b>${socM}p</b>`;
                }
            }

            const dataValues = total === 0 ? [1] : [learnM || 0, entM || 0, socM || 0];
            const bgColors = total === 0 ? ['#e2e8f0'] : ['#10b981', '#f43f5e', '#3b82f6'];
            const labels = total === 0 ? ['Chưa dùng'] : ['Học tập', 'Giải trí', 'Mạng xã hội'];

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
                                        if (total === 0) return "Chưa có dữ liệu";
                                        return ` ${context.label}: ${context.raw} phút`;
                                    }
                                }
                            }
                        }
                    }
                });
            }
        }

        async function fetchUsageStats() {
            const listEl = document.getElementById("usage-list");
            try {
                const response = await fetch(`${API_BASE}/usage-stats/`);
                const data = await response.json();

                document.getElementById("stat-total-time").innerText = data.total_formatted;
                document.getElementById("stat-learning-time").innerText = data.learning_formatted || "0 phút";
                document.getElementById("stat-entertainment-time").innerText = data.entertainment_formatted;

                const overviewUsed = document.getElementById("overview-used-time");
                if (overviewUsed) overviewUsed.textContent = data.total_formatted;

                updateParentChart(data.learning_minutes, data.entertainment_minutes, data.social_minutes);

                cachedUsageItems = data.items || [];
                renderUsageList(cachedUsageItems);
            } catch (error) {
                if (listEl) listEl.innerHTML = `<p class="text-rose-500 text-xs py-2 text-center">Lỗi khi tải báo cáo: ${error.message}</p>`;
            }
        }

        function filterUsage(tag, btn) {
            document.querySelectorAll(".usage-filter-btn").forEach(b => {
                b.className = "usage-filter-btn px-3 py-1 rounded-full text-xs font-semibold bg-slate-100 text-slate-600 hover:bg-slate-200";
            });
            btn.className = "usage-filter-btn px-3 py-1 rounded-full text-xs font-semibold bg-emerald-600 text-white";

            if (tag === "ALL") {
                renderUsageList(cachedUsageItems);
            } else {
                const filtered = cachedUsageItems.filter(item => item.tag === tag);
                renderUsageList(filtered);
            }
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
                            <span class="font-bold text-slate-800 text-xs md:text-sm">${item.app_name}</span>
                            <span class="text-[10px] font-semibold px-2 py-0.5 rounded-full border ${item.badge_color}">${item.category}</span>
                        </div>
                        <div class="flex flex-wrap items-center gap-2 text-xs">
                            <span class="text-slate-500">Đã dùng: <strong>${item.duration_formatted}</strong></span>
                            <span>•</span>
                            <span class="text-[11px] px-2.5 py-0.5 rounded-full border ${remColor}">
                                ${item.is_expired ? '🛑 Đã hết giờ (0p)' : '⏳ ' + item.remaining_formatted}
                            </span>
                            <button onclick="openLimitModal('${item.app_name}', ${item.time_limit_minutes})" class="text-blue-600 hover:text-blue-800 text-xs font-semibold px-2 py-1 bg-white border border-blue-200 rounded-lg shadow-xs">
                                ⚙️ Đặt hạn mức
                            </button>
                        </div>
                    </div>
                    
                    <div class="flex flex-wrap items-center justify-between gap-2 pt-1.5 border-t border-slate-200/50">
                        <div class="flex items-center gap-1 text-[11px] text-slate-500">
                            <span>⚡ Tự điền nhanh:</span>
                            <button onclick="setQuickLimit('${item.app_name}', 30)" class="px-2 py-0.5 bg-white hover:bg-blue-50 hover:text-blue-600 border border-slate-200 rounded text-[10px] font-semibold">30p</button>
                            <button onclick="setQuickLimit('${item.app_name}', 45)" class="px-2 py-0.5 bg-white hover:bg-blue-50 hover:text-blue-600 border border-slate-200 rounded text-[10px] font-semibold">45p</button>
                            <button onclick="setQuickLimit('${item.app_name}', 60)" class="px-2 py-0.5 bg-white hover:bg-blue-50 hover:text-blue-600 border border-slate-200 rounded text-[10px] font-semibold">60p</button>
                            <button onclick="setQuickLimit('${item.app_name}', 90)" class="px-2 py-0.5 bg-white hover:bg-blue-50 hover:text-blue-600 border border-slate-200 rounded text-[10px] font-semibold">90p</button>
                            <button onclick="setQuickLimit('${item.app_name}', 120)" class="px-2 py-0.5 bg-white hover:bg-blue-50 hover:text-blue-600 border border-slate-200 rounded text-[10px] font-semibold">120p</button>
                            <button onclick="setQuickLimit('${item.app_name}', 0)" class="px-2 py-0.5 bg-white hover:bg-slate-100 border border-slate-200 rounded text-[10px] font-semibold text-slate-500">Không GH</button>
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

        async function autoFillLimits() {
            if (!confirm("Tự động điền hạn mức khuyên dùng cho các web và app (Học tập: 120p, Giải trí: 45p, MXH: 30p)?")) return;
            try {
                const res = await fetch(`${API_BASE}/rules/auto-fill-defaults`, { method: "POST" });
                if (res.ok) {
                    const data = await res.json();
                    showToast(`⚡ Đã tự điền hạn mức khuyên dùng thành công (${data.count} mục)!`, "success");
                    fetchUsageStats();
                    fetchRules();
                }
            } catch (e) {
                alert("Lỗi tự điền hạn mức: " + e.message);
            }
        }

        async function setQuickLimit(targetName, mins) {
            try {
                const res = await fetch(`${API_BASE}/rules/`, {
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
                const res = await fetch(`${API_BASE}/curfew/`);
                if (res.ok) {
                    const data = await res.json();
                    document.getElementById("curfew-bedtime-input").value = data.bedtime;
                    document.getElementById("curfew-wakeup-input").value = data.wakeup_time;
                    
                    const badge = document.getElementById("curfew-status-badge");
                    const overviewCurfewText = document.getElementById("overview-curfew-text");
                    const overviewCurfewStatus = document.getElementById("overview-curfew-status");
                    
                    if (overviewCurfewText) {
                        overviewCurfewText.textContent = `${data.bedtime} → ${data.wakeup_time}`;
                    }

                    if (data.is_within_curfew) {
                        if (badge) {
                            badge.className = "inline-flex items-center px-3 py-1 rounded-full text-xs font-semibold bg-rose-100 text-rose-800 border border-rose-300 animate-pulse";
                            badge.innerHTML = "🌙 Máy con đang bị vô hiệu hóa";
                        }
                        if (overviewCurfewStatus) {
                            overviewCurfewStatus.className = "text-[10px] text-rose-600 font-bold animate-pulse";
                            overviewCurfewStatus.textContent = "🌙 Đang bị khóa";
                        }
                    } else {
                        if (badge) {
                            badge.className = "inline-flex items-center px-3 py-1 rounded-full text-xs font-semibold bg-emerald-100 text-emerald-800 border border-emerald-300";
                            badge.innerHTML = "🟢 Máy con đang mở";
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
            const bedtime = document.getElementById("curfew-bedtime-input").value || "22:00";
            const wakeup = document.getElementById("curfew-wakeup-input").value || "06:00";
            try {
                const res = await fetch(`${API_BASE}/curfew/`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ bedtime: bedtime, wakeup_time: wakeup })
                });
                if (res.ok) {
                    showToast(`🌙 Đã cập nhật giờ vô hiệu hóa: ${bedtime} (Tối) → ${wakeup} (Sáng)!`, "success");
                    fetchCurfew();
                }
            } catch (e) {
                alert("Lỗi lưu khung giờ: " + e.message);
            }
        }

        let currentChildren = [];

        async function fetchChildren() {
            const container = document.getElementById("children-profiles-container");
            const headerActive = document.getElementById("header-active-child-name");
            const overviewChild = document.getElementById("overview-child-name");

            try {
                const res = await fetch(`${API_BASE}/children/`);
                if (!res.ok) return;
                currentChildren = await res.json();

                const active = currentChildren.find(c => c.is_active) || currentChildren[0];
                if (active) {
                    if (headerActive) headerActive.textContent = `${active.avatar || '🧒'} ${active.name}`;
                    if (overviewChild) overviewChild.textContent = `${active.avatar || '🧒'} ${active.name}`;
                }

                if (currentChildren.length === 0) {
                    container.innerHTML = `<p class="text-slate-400 text-xs italic py-2 text-center col-span-full">Chưa có hồ sơ trẻ nào. Bấm 'Thêm hồ sơ bé' để tạo!</p>`;
                    return;
                }

                container.innerHTML = currentChildren.map(c => `
                    <div class="p-4 rounded-2xl border ${c.is_active ? 'bg-blue-50/70 border-blue-400 ring-2 ring-blue-300/40' : 'bg-slate-50 border-slate-200'} flex flex-col justify-between gap-3 transition">
                        <div class="flex items-center gap-3">
                            <div class="text-3xl p-2 bg-white rounded-2xl shadow-xs border border-slate-100 flex items-center justify-center w-12 h-12">
                                ${c.avatar || '🧒'}
                            </div>
                            <div>
                                <div class="flex items-center gap-1.5">
                                    <span class="font-bold text-slate-800 text-sm">${c.name}</span>
                                    ${c.is_active ? '<span class="px-2 py-0.5 rounded-full text-[10px] font-bold bg-blue-600 text-white animate-pulse">Đang dùng máy</span>' : ''}
                                </div>
                                <div class="text-[11px] text-slate-500 mt-0.5">
                                    ${c.age} tuổi • Hạn mức: <strong>${c.daily_limit_minutes} phút</strong>
                                </div>
                                <div class="text-[10px] text-slate-400">
                                    Mã PIN: <span class="font-mono bg-slate-200/80 px-1.5 py-0.5 rounded text-slate-700 font-bold">${c.pin || 'Không có'}</span>
                                </div>
                            </div>
                        </div>
                        <div class="flex items-center gap-2 pt-2 border-t border-slate-200/60">
                            ${!c.is_active ? `
                                <button onclick="selectChild(${c.id})" class="flex-1 py-1.5 px-2 bg-blue-600 hover:bg-blue-700 text-white rounded-xl text-xs font-semibold transition">
                                    Đổi sang trẻ này 🔄
                                </button>
                            ` : `
                                <span class="flex-1 py-1.5 text-center text-blue-700 text-xs font-semibold">Tài khoản hiện tại 💻</span>
                            `}
                            ${currentChildren.length > 1 ? `
                                <button onclick="deleteChild(${c.id})" class="text-rose-500 hover:text-rose-700 p-1.5 text-xs rounded-lg hover:bg-rose-50 transition" title="Xóa hồ sơ">
                                    🗑️
                                </button>
                            ` : ''}
                        </div>
                    </div>
                `).join("");
            } catch (e) {
                if (container) container.innerHTML = `<p class="text-rose-500 text-xs py-2 text-center col-span-full">Lỗi nạp hồ sơ: ${e.message}</p>`;
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
            const pin = document.getElementById("cpPin").value.trim() || "1234";
            const avatar = document.getElementById("cpAvatar").value || "🧒";
            const limit = parseInt(document.getElementById("cpLimit").value, 10) || 120;

            try {
                const res = await fetch(`${API_BASE}/children/`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        name: name,
                        avatar: avatar,
                        age: age,
                        pin: pin,
                        daily_limit_minutes: limit
                    })
                });
                if (res.ok) {
                    closeChildProfileModal();
                    showToast(`👶 Đã tạo hồ sơ cho bé "${name}" thành công!`, "success");
                    fetchChildren();
                }
            } catch (err) {
                alert("Lỗi lưu hồ sơ: " + err.message);
            }
        }

        async function selectChild(childId) {
            try {
                const res = await fetch(`${API_BASE}/children/select/${childId}`, { method: "POST" });
                if (res.ok) {
                    showToast("🔄 Đã chuyển tài khoản trẻ thành công!", "success");
                    fetchChildren();
                    fetchUsageStats();
                }
            } catch (err) {
                alert("Lỗi chuyển tài khoản: " + err.message);
            }
        }

        async function deleteChild(childId) {
            if (!confirm("Bạn có chắc chắn muốn xóa hồ sơ của bé này?")) return;
            try {
                const res = await fetch(`${API_BASE}/children/${childId}`, { method: "DELETE" });
                if (res.ok) {
                    showToast("🗑️ Đã xóa hồ sơ trẻ thành công!", "info");
                    fetchChildren();
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
                const res = await fetch(`${API_BASE}/alerts/`);
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
                    container.innerHTML = `<p class="text-slate-400 text-xs italic py-4 text-center">Chưa có cảnh báo vi phạm nào. An toàn tuyệt đối! 🟢</p>`;
                    return;
                }

                container.innerHTML = alerts.map(a => {
                    const timeStr = new Date(a.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
                    
                    let catBadge = `<span class="text-[9px] bg-blue-100 text-blue-800 border border-blue-200 font-bold px-1.5 py-0.5 rounded">⚠️ Web Lạ Chưa Phép</span>`;
                    if (a.category === "AI_CONTENT_TEXT") {
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
                                        <span class="font-bold text-rose-900 text-xs">${a.target_value}</span>
                                        ${catBadge}
                                        <span class="text-[10px] bg-rose-200 text-rose-800 px-1.5 py-0.5 rounded font-mono">${timeStr}</span>
                                    </div>
                                    <p class="text-[11px] text-rose-700 mt-0.5">${a.reason || "Cố tình truy cập trang web lạ chưa xin phép"}</p>
                                </div>
                            </div>
                            <div class="flex items-center gap-1.5 self-end sm:self-auto">
                                <button onclick="quickAllowAlert('${a.target_value}')" class="px-2.5 py-1 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg text-xs font-semibold shadow-xs transition">
                                    ✅ Cho phép
                                </button>
                                <button onclick="quickBlockAlert('${a.target_value}')" class="px-2.5 py-1 bg-slate-800 hover:bg-slate-900 text-white rounded-lg text-xs font-semibold shadow-xs transition">
                                    ⛔ Chặn
                                </button>
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
                await fetch(`${API_BASE}/alerts/`, { method: "DELETE" });
                showToast("🧹 Đã làm sạch toàn bộ cảnh báo!", "info");
                fetchAlerts();
            } catch (e) {}
        }

        async function deleteAlert(id) {
            try {
                await fetch(`${API_BASE}/alerts/${id}`, { method: "DELETE" });
                fetchAlerts();
            } catch (e) {}
        }

        async function quickAllowAlert(target) {
            await setQuickLimit(target, 45);
            fetchAlerts();
        }

        async function quickBlockAlert(target) {
            try {
                await fetch(`${API_BASE}/rules/`, {
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

        // ==========================================
        // QUẢN LÝ THIẾT BỊ CON CÁI & GHÉP NỐI (DEVICES)
        // ==========================================
        let cachedDevices = [];

        async function fetchDevices() {
            const container = document.getElementById("devices-container");
            const navBadge = document.getElementById("nav-devices-badge");
            try {
                const res = await fetch(`${API_BASE}/devices/`);
                if (!res.ok) return;
                const devices = await res.json();
                cachedDevices = devices;

                if (navBadge) {
                    navBadge.textContent = devices.length;
                }

                if (!container) return;

                if (devices.length === 0) {
                    container.innerHTML = `
                        <div class="p-8 text-center text-slate-400 text-xs col-span-2 border-2 border-dashed border-slate-200 rounded-2xl bg-slate-50/50">
                            <span class="text-3xl block mb-2">💻</span>
                            Chưa có thiết bị nào được ghép nối.<br>
                            Hãy bấm <strong>➕ Thêm Thiết Bị Của Con</strong> để tạo hồ sơ và lấy mã ghép nối cài lên máy tính của con!
                        </div>
                    `;
                    return;
                }

                container.innerHTML = devices.map(d => {
                    const isOnline = d.status === "ONLINE_WAN" || d.status === "ONLINE_LAN";
                    const isPending = !d.is_paired;
                    
                    let statusBadge = "";
                    if (isOnline) {
                        statusBadge = `<span class="px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-100 text-emerald-800 border border-emerald-300 flex items-center gap-1"><span class="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></span>Trực tuyến (Cloud WAN)</span>`;
                    } else if (isPending) {
                        statusBadge = `<span class="px-2 py-0.5 rounded-full text-[10px] font-bold bg-amber-100 text-amber-800 border border-amber-300">🟡 Chờ ghép nối (Mã: ${d.pairing_code})</span>`;
                    } else {
                        statusBadge = `<span class="px-2 py-0.5 rounded-full text-[10px] font-bold bg-slate-100 text-slate-600 border border-slate-300">⚪ Ngoại tuyến</span>`;
                    }

                    const platformIcon = (d.platform || "").toLowerCase().includes("win") ? "🪟 Windows" : "🐧 Linux";

                    return `
                        <div class="p-4 bg-white border border-slate-200 rounded-2xl shadow-xs hover:shadow-md transition space-y-3">
                            <div class="flex items-start justify-between gap-2">
                                <div class="flex items-center gap-3">
                                    <div class="w-10 h-10 rounded-xl bg-blue-50 border border-blue-200 text-blue-600 flex items-center justify-center text-xl shadow-xs">
                                        💻
                                    </div>
                                    <div>
                                        <h4 class="font-bold text-slate-800 text-xs">${d.device_name}</h4>
                                        <span class="text-[10px] text-slate-500">${platformIcon} • ${d.child_name ? '🧒 ' + d.child_name : 'Chưa gán bé'}</span>
                                    </div>
                                </div>
                                <div>${statusBadge}</div>
                            </div>

                            <!-- Thông tin phần cứng & Bảo mật -->
                            <div class="p-2.5 bg-slate-50 border border-slate-100 rounded-xl space-y-1 text-[11px]">
                                <div class="flex justify-between items-center text-slate-600">
                                    <span>Mã phần cứng (HWID):</span>
                                    <code class="font-mono text-[10px] font-bold text-slate-800 bg-white px-1.5 py-0.5 rounded border border-slate-200 select-all">${d.device_hwid || 'Chờ máy con gửi HWID'}</code>
                                </div>
                                <div class="flex justify-between items-center text-slate-600">
                                    <span>Bảo vệ chống tắt:</span>
                                    <span class="font-semibold text-indigo-700">🔒 System Service / Daemon (Mật khẩu Admin)</span>
                                </div>
                                <div class="flex justify-between items-center text-slate-600">
                                    <span>Bộ lọc AI:</span>
                                    <span class="font-semibold text-emerald-700">🤖 Văn bản & Màn hình thời gian thực</span>
                                </div>
                            </div>

                            <!-- Các nút điều khiển từ xa qua Cloud Relay -->
                            <div class="flex items-center justify-between pt-1 border-t border-slate-100">
                                <div class="flex items-center gap-1.5">
                                    <button onclick="sendRemoteDeviceCommand('${d.device_hwid || d.id}', 'LOCK_MACHINE')" class="px-2.5 py-1 bg-amber-600 hover:bg-amber-700 text-white rounded-lg text-xs font-semibold shadow-xs transition" title="Khóa màn hình máy con ngay lập tức qua WAN">
                                        🔒 Khóa
                                    </button>
                                    <button onclick="sendRemoteDeviceCommand('${d.device_hwid || d.id}', 'UNLOCK_MACHINE')" class="px-2.5 py-1 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg text-xs font-semibold shadow-xs transition" title="Mở khóa máy con từ xa">
                                        🔓 Mở
                                    </button>
                                    <button onclick="promptSendMessage('${d.device_hwid || d.id}')" class="px-2.5 py-1 bg-blue-600 hover:bg-blue-700 text-white rounded-lg text-xs font-semibold shadow-xs transition" title="Gửi lời nhắn tới máy con">
                                        💬 Nhắn
                                    </button>
                                </div>
                                <button onclick="deleteDeviceItem('${d.id}')" class="text-slate-400 hover:text-rose-600 text-xs transition p-1" title="Xóa thiết bị này">
                                    🗑️ Xóa
                                </button>
                            </div>
                        </div>
                    `;
                }).join("");
            } catch (e) {}
        }

        function openAddDeviceModal() {
            const selectEl = document.getElementById("devChildProfile");
            if (selectEl && Array.isArray(currentChildren) && currentChildren.length > 0) {
                selectEl.innerHTML = `<option value="">-- Chưa gán bé cụ thể --</option>` + currentChildren.map(c => `
                    <option value="${c.id}">${c.avatar || '🧒'} ${c.name} (${c.age} tuổi)</option>
                `).join("");
            }
            document.getElementById("create-device-form").classList.remove("hidden");
            document.getElementById("device-paired-instructions").classList.add("hidden");
            document.getElementById("add-device-modal").classList.remove("hidden");
        }

        function closeAddDeviceModal() {
            document.getElementById("add-device-modal").classList.add("hidden");
        }

        async function submitCreateDevice(e) {
            e.preventDefault();
            const name = document.getElementById("devName").value.trim();
            const childId = document.getElementById("devChildProfile").value;
            const limit = parseInt(document.getElementById("devLimit").value) || 90;
            const bedtime = document.getElementById("devBedtime").value.trim() || "22:00";

            const blockedItems = [];
            if (document.getElementById("block-roblox")?.checked) blockedItems.push("roblox");
            if (document.getElementById("block-tiktok")?.checked) blockedItems.push("tiktok.com");
            if (document.getElementById("block-discord")?.checked) blockedItems.push("discord.com");
            if (document.getElementById("block-facebook")?.checked) blockedItems.push("facebook.com");

            try {
                const res = await fetch(`${API_BASE}/devices/create`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        device_name: name,
                        child_profile_id: childId ? parseInt(childId) : null,
                        daily_limit_minutes: limit,
                        bedtime: bedtime,
                        blocked_items: blockedItems
                    })
                });
                if (res.ok) {
                    const data = await res.json();
                    document.getElementById("create-device-form").classList.add("hidden");
                    document.getElementById("generated-pairing-code").textContent = data.pairing_code;
                    const serverFlag = API_BASE ? ` --server ${API_BASE}` : "";
                    document.getElementById("pairing-cmd-linux").textContent = `python agent/agent_main.py --pair-code ${data.pairing_code}${serverFlag}`;
                    document.getElementById("device-paired-instructions").classList.remove("hidden");
                    showToast(`🎉 Đã tạo mã ghép nối: ${data.pairing_code}`, "success");
                    fetchDevices();
                } else {
                    alert("Không thể tạo thiết bị, vui lòng thử lại!");
                }
            } catch (err) {
                alert("Lỗi kết nối máy chủ: " + err.message);
            }
        }

        async function sendRemoteDeviceCommand(hwid, action) {
            try {
                const res = await fetch(`${API_BASE}/relay/command`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        target_hwid: hwid,
                        action: action
                    })
                });
                if (res.ok) {
                    showToast(`🚀 Đã gửi lệnh ${action} tới máy con qua Cloud Relay WAN!`, "success");
                }
            } catch (e) {
                alert("Lỗi gửi lệnh: " + e.message);
            }
        }

        function promptSendMessage(hwid) {
            const msg = prompt("Nhập lời nhắn gửi tới máy con:");
            if (!msg) return;
            fetch(`${API_BASE}/relay/command`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    target_hwid: hwid,
                    action: "PARENT_MESSAGE",
                    data: { message: msg }
                })
            }).then(() => showToast(`💬 Đã gửi lời nhắn: "${msg}"`, "info"));
        }

        async function deleteDeviceItem(devId) {
            if (!confirm("Bạn có chắc chắn muốn hủy liên kết và xóa thiết bị này?")) return;
            try {
                const res = await fetch(`${API_BASE}/devices/${devId}`, { method: "DELETE" });
                if (res.ok) {
                    showToast("Đã xóa thiết bị thành công", "info");
                    fetchDevices();
                }
            } catch (e) {}
        }

        async function fetchRules() {
            const listEl = document.getElementById("rules-list");
            if (!listEl) return;
            try {
                const res = await fetch(`${API_BASE}/rules/`);
                const rules = await res.json();
                listEl.innerHTML = "";

                if (rules.length === 0) {
                    listEl.innerHTML = `<p class="text-slate-400 text-xs italic col-span-full py-4 text-center">Chưa có quy tắc nào.</p>`;
                    return;
                }

                rules.forEach(r => {
                    const card = document.createElement("div");
                    const isAllow = r.action === "ALLOW";
                    const badgeBg = isAllow ? "bg-emerald-100 text-emerald-800 border-emerald-300" : "bg-rose-100 text-rose-800 border-rose-300";
                    const badgeText = isAllow ? "Cho phép ✅" : "Chặn 🛑";
                    const icon = r.rule_type === "WEBSITE" ? "🌐" : "📱";

                    let remText = r.time_limit_minutes > 0 ? `${r.remaining_formatted}` : "Vô hạn";

                    card.className = "p-3.5 bg-slate-50 border border-slate-200 rounded-xl flex items-center justify-between text-xs";
                    card.innerHTML = `
                        <div class="flex items-center gap-2 overflow-hidden">
                            <span>${icon}</span>
                            <div>
                                <span class="font-bold text-slate-700 block truncate">${r.target_value}</span>
                                <span class="text-[10px] text-slate-500">Giới hạn: ${r.time_limit_minutes > 0 ? r.time_limit_minutes + 'p' : 'Vô hạn'} (${remText})</span>
                            </div>
                        </div>
                        <div class="flex items-center gap-2">
                            <span class="text-[10px] font-semibold px-2 py-0.5 rounded-full border ${badgeBg}">${badgeText}</span>
                            <button onclick="deleteRule('${r.id}')" class="text-slate-400 hover:text-rose-600 text-xs font-semibold px-1">
                                Xóa
                            </button>
                        </div>
                    `;
                    listEl.appendChild(card);
                });
            } catch (e) {
                listEl.innerHTML = `<p class="text-rose-500 text-xs col-span-full">Lỗi tải quy tắc: ${e.message}</p>`;
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
                const res = await fetch(`${API_BASE}/rules/`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        rule_type: type,
                        target_value: target,
                        action: action,
                        time_limit_minutes: limit
                    })
                });

                if (res.ok) {
                    showToast(`Đã thêm quy tắc cho "${target}"!`, "success");
                    document.getElementById("newRuleValue").value = "";
                    fetchRules();
                    fetchUsageStats();
                }
            } catch (err) {
                alert("Lỗi thêm quy tắc: " + err.message);
            }
        }

        async function deleteRule(ruleId) {
            if (!confirm("Bạn có chắc muốn xóa quy tắc này?")) return;
            try {
                const res = await fetch(`${API_BASE}/rules/${ruleId}`, { method: "DELETE" });
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

            if (type === "daily") {
                confirmMsg = "Bắt đầu ngày mới? Thời gian đã dùng sẽ về 0 và danh sách việc tốt hàng ngày sẽ được mở lại.";
                endpoint = "/reset/daily";
            } else if (type === "usage") {
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
                const res = await fetch(`${API_BASE}${endpoint}`, { method: "POST" });
                const result = await res.json();
                if (res.ok) {
                    showToast(result.message || "Thao tác reset thành công!", "success");
                    fetchUsageStats();
                    fetchRules();
                    fetchRequests();
                    fetchTasks();
                }
            } catch (err) {
                alert("Lỗi kết nối máy chủ: " + err.message);
            }
        }

        window.addEventListener("DOMContentLoaded", async () => {
            updateSoundUI();
            await autoDetectBackendPort();
            initWebSocket();
            fetchRequests();
            fetchTasks();
            fetchUsageStats();
            fetchRules();
            fetchCurfew();
            fetchChildren();
            fetchAlerts();
            fetchDevices();

            switchParentTab('overview');
        });
