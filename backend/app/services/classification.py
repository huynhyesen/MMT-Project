from agent.web_policy import is_adult_host, normalize_host


WEB_CATEGORIES = {
    "LEARNING": {
        "khanacademy.org", "wikipedia.org", "duolingo.com", "scratch.mit.edu", "coursera.org",
        "edx.org", "udemy.com", "quizlet.com", "hocmai.vn", "vio.edu.vn", "vnedu.vn", "olm.vn",
        "vietjack.com", "geogebra.org", "code.org", "w3schools.com", "leetcode.com", "hackerrank.com",
        "stackoverflow.com", "github.com", "gitlab.com", "python.org", "violet.vn", "zoom.us",
        "classroom.google.com", "meet.google.com", "teams.microsoft.com", "schoology.com", "oj.vnoi.info",
    },
    "ENTERTAINMENT": {
        "youtube.com", "youtu.be", "netflix.com", "spotify.com", "roblox.com", "minecraft.net",
        "steampowered.com", "steamcommunity.com", "epicgames.com", "friv.com", "poki.com",
        "bilibili.com", "twitch.tv", "webtoons.com", "soundcloud.com", "music.apple.com",
        "zingmp3.vn", "nhaccuatui.com", "fptplay.vn", "vieon.vn", "vtvgo.vn", "chess.com",
    },
    "SOCIAL": {
        "discord.com", "discord.gg", "facebook.com", "fb.com", "messenger.com", "zalo.me",
        "telegram.org", "t.me", "tiktok.com", "instagram.com", "threads.net", "twitter.com",
        "x.com", "skype.com", "viber.com", "whatsapp.com", "wechat.com", "reddit.com",
        "pinterest.com", "snapchat.com", "tumblr.com",
    },
    "UTILITY": {
        "google.com", "bing.com", "canva.com", "figma.com", "gimp.org", "audacityteam.org",
    },
}


def extract_target_name(target: str) -> str:
    """Normalize domain or application name."""
    if not target:
        return ""

    target = target.split("[")[0].strip()

    if "://" in target:
        target = target.split("://")[1]

    target = target.split("/")[0].split("?")[0].split(":")[0]

    if target.lower().startswith("www."):
        target = target[4:]

    return target


def is_system_process(name: str) -> bool:
    name = name.lower().strip()

    prefixes = [
        "kworker", "kthread", "rcu", "pool_", "irq/",
        "ksoftirqd", "systemd", "migration", "auditd"
    ]

    if any(name.startswith(prefix) for prefix in prefixes):
        return True

    system_processes = {
        "system", "registry", "svchost.exe", "dbus-daemon",
        "pipewire", "pulseaudio", "xorg", "gnome-shell",
        "bash", "sh", "python", "python3", "uvicorn",
        "idle", "kthreadd", "pool_workqueue_release",
        "rcu_tasks_kthread"
    }

    return name in system_processes


def classify_item(name: str, *, is_web: bool | None = None) -> dict:
    """Classify a website or application into a category."""

    default_result = {
        "category": "Ứng dụng khác",
        "tag": "OTHER",
        "icon": "💻",
        "badge_color": "bg-slate-100 text-slate-800 border-slate-300",
        "default_limit": 60,
        "is_educational": False
    }

    if not name or is_system_process(name):
        return default_result

    name = name.lower().strip()
    host = normalize_host(name)
    if is_web is None:
        is_web = bool(host) and not host.endswith((".exe", ".app", ".bin"))
    web_tag = None
    if is_web:
        if host and is_adult_host(host):
            return {
                "category": "Nội dung 18+",
                "tag": "ADULT",
                "icon": "🔞",
                "badge_color": "bg-rose-100 text-rose-800 border-rose-300",
                "default_limit": 0,
                "is_educational": False,
            }
        default_result["category"] = "Chưa phân loại"
        labels = host.split(".")
        for index in range(len(labels)):
            domain = ".".join(labels[index:])
            web_tag = next((tag for tag, domains in WEB_CATEGORIES.items() if domain in domains), None)
            if web_tag:
                break
        if not web_tag and host.endswith((".edu", ".edu.vn")):
            web_tag = "LEARNING"

    categories = {
        "LEARNING": {
            "keywords": [
                "khanacademy", "wikipedia", "duolingo", "scratch",
                "coursera", "edx", "udemy", "quizlet", "canvas",
                "blackboard", "hocmai", "vioedu", "vnedu", "olm",
                "k12online", "vietjack", "tuyensinh247", "geogebra",
                "code.org", "w3schools", "leetcode", "hackerrank",
                "stackoverflow", "github", "gitlab", "python",
                "sachmem", "violet.vn", "word", "excel", "powerpoint",
                "onenote", "acrobat", "reader", "pdf", "zoom", "teams",
                "classroom", "meet", ".edu", "school", "portal",
                "lophoc", "trithuc", "tienganh", "toan", "vatly",
                "hoahoc", "lichsu", "dialy", "ielts", "toeic",
                "learn", "study", "math"
            ],
            "category": "Học tập & Giáo dục",
            "icon": "📚",
            "color": "bg-emerald-100 text-emerald-800 border-emerald-300",
            "limit": 180,
            "educational": True
        },

        "ENTERTAINMENT": {
            "keywords": [
                "youtube", "youtu.be", "netflix", "spotify",
                "roblox", "minecraft", "steam", "epicgames",
                "league", "valorant", "genshin", "fifa", "pubg",
                "game", "friv", "poki", "bilibili", "twitch",
                "anime", "manga", "truyen", "comic", "zingmp3",
                "nhaccuatui", "fptplay", "vieon", "movie",
                "film", "cinema", "chess", "cotuong", "caro",
                "webtoon", "soundcloud", "apple music", "zing",
                "vtvgo", "clip", "video"
            ],
            "category": "Giải trí & Game",
            "icon": "🎮",
            "color": "bg-rose-100 text-rose-800 border-rose-300",
            "limit": 45,
            "educational": False
        },

        "SOCIAL": {
            "keywords": [
                "discord", "facebook", "fb.com", "messenger",
                "zalo", "telegram", "tiktok", "instagram",
                "threads", "twitter", "x.com", "skype", "viber",
                "whatsapp", "wechat", "reddit", "pinterest",
                "snapchat", "tumblr", "chat", "direct"
            ],
            "category": "Mạng xã hội & Chat",
            "icon": "💬",
            "color": "bg-blue-100 text-blue-800 border-blue-300",
            "limit": 30,
            "educational": False
        },

        "UTILITY": {
            "keywords": [
                "google", "bing", "chrome", "edge", "firefox",
                "safari", "brave", "coccoc", "opera", "calc",
                "calculator", "paint", "notepad", "notes",
                "canva", "figma", "photoshop", "gimp",
                "audacity", "vlc", "terminal", "cmd",
                "calendar", "clock"
            ],
            "category": "Công cụ & Tiện ích",
            "icon": "🛠️",
            "color": "bg-amber-100 text-amber-800 border-amber-300",
            "limit": 60,
            "educational": False
        }
    }

    for tag, config in categories.items():
        if (is_web and tag == web_tag) or (not is_web and any(keyword in name for keyword in config["keywords"])):
            return {
                "category": config["category"],
                "tag": tag,
                "icon": config["icon"],
                "badge_color": config["color"],
                "default_limit": config["limit"],
                "is_educational": config["educational"]
            }

    return default_result

#Phan loai website & ung dung
