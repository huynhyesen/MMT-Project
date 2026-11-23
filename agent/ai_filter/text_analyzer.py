import re
from typing import Dict, Any
from unicodedata import normalize

# Từ khóa và mẫu cảnh báo cho tiếng Việt và tiếng Anh.
INAPPROPRIATE_LEXICON = {
    "ADULT": {
        "label": "Nội dung người lớn (18+ / Khiêu dâm)",
        "weight": 0.95,
        "keywords": [
            "porn", "porno", "xxx", "hentai", "nsfw", "erotic", "sex video",
            "khiêu dâm", "đồi trụy", "gái gọi", "phim người lớn", "phim cấp 3",
            "thủ dâm", "loạn luân", "lộ clip", "ảnh nóng", "khoả thân", "gái xinh cởi đồ",
            "show hàng", "kích dục", "mại dâm", "camshow", "xvideos", "pornhub", "xnxx",
            "redtube", "onlyfans"
        ],
        "patterns": [
            r"\b(p[o0]rn|xxx)\b",
            r"(phim\s*(18\+|người\s*lớn|cấp\s*3))",
            r"(lộ\s*clip|ảnh\s*nóng|show\s*hàng)"
        ]
    },
    "GAMBLING": {
        "label": "Cờ bạc & Cá cược trực tuyến",
        "weight": 0.90,
        "keywords": [
            "casino", "betting", "poker", "baccarat", "roulette", "blackjack", "slot machine",
            "cá độ", "cá cược", "tài xỉu", "đá gà", "nổ hũ", "đánh bài đổi thưởng", "lô đề",
            "quay hũ", "bắn cá đổi tiền", "kubet", "thabet", "fun88", "w88", "188bet", "m88",
            "socvip", "sunwin", "go88", "rikvip", "b52 club"
        ],
        "patterns": [
            r"(cá\s*cược|cá\s*độ|tài\s*xỉu|nổ\s*hũ)",
            r"(đánh\s*bài\s*(ăn\s*tiền|đổi\s*thưởng))",
            r"\b(bet88|kubet|w88|go88|sunwin)\b"
        ]
    },
    "VIOLENCE": {
        "label": "Bạo lực, Máu me & Tự hại",
        "weight": 0.92,
        "keywords": [
            "suicide", "kill myself", "beheading", "gore video", "murder", "bomb making",
            "tự tử", "tự hại", "cắt cổ tay", "chém nhau", "đâm chém", "súng đạn", "chế tạo bom",
            "thuốc nổ", "máu me ghê rợn", "hành hạ dã man", "tự sát", "nhảy lầu"
        ],
        "patterns": [
            r"(tự\s*(tử|sát|hại)|cắt\s*cổ\s*tay)",
            r"(chế\s*tạo\s*(bom|thuốc\s*nổ|vũ\s*khí))",
            r"(đâm\s*chém|giết\s*người)"
        ]
    },
    "TOXIC": {
        "label": "Ngôn từ thù ghét & Bắt nạt qua mạng",
        "weight": 0.85,
        "keywords": [
            "đụ mẹ", "địt mẹ", "đụ má", "cặc", "lồn", "chó đẻ", "khốn nạn", "đĩ", "con đĩ",
            "chết đi", "fuck you", "motherfucker", "bitch", "bastard", "nigger"
        ],
        "patterns": [
            r"\bđ(?:m|ụ|ịt)\s*(má|mẹ)\b",
            r"\b(f[u*]ck|b[i*]tch)\b"
        ]
    }
}

class AITextAnalyzer:
    """Phân tích từ khóa tiếng Việt và tiếng Anh trong văn bản được cung cấp."""

    def __init__(self):
        # Tiền biên dịch từ khóa theo ranh giới từ và các mẫu nhiều từ.
        self.compiled_rules = {}
        for category, info in INAPPROPRIATE_LEXICON.items():
            keywords = (r"(?<!\w)" + re.escape(word.casefold()) + r"(?!\w)" for word in info["keywords"])
            compiled_pats = [re.compile(pattern) for pattern in (*keywords, *info["patterns"])]
            self.compiled_rules[category] = {
                "label": info["label"],
                "weight": info["weight"],
                "patterns": compiled_pats
            }

    def analyze(self, text: str) -> Dict[str, Any]:
        """
        Phân tích chuỗi văn bản (tiêu đề cửa sổ, URL, nội dung tìm kiếm...).
        Trả về kết quả đánh giá độ an toàn và mức độ tin cậy.
        """
        if not text:
            return {"is_safe": True, "category": None, "confidence": 0.0, "reason": None}

        clean_text = " ".join(normalize("NFC", text).casefold().split())
        matched_categories = []

        for category, data in self.compiled_rules.items():
            if any(pattern.search(clean_text) for pattern in data["patterns"]):
                matched_categories.append({
                    "category": category,
                    "label": data["label"],
                    "confidence": data["weight"],
                })

        if matched_categories:
            # Ưu tiên nhóm quy tắc có trọng số cao nhất khi có nhiều nhóm khớp.
            matched_categories.sort(key=lambda x: x["confidence"], reverse=True)
            top = matched_categories[0]
            reason = f"Văn bản khớp quy tắc cảnh báo về {top['label']}."
            return {
                "is_safe": False,
                "category": top["category"],
                "label": top["label"],
                "confidence": round(top["confidence"], 2),
                "reason": reason,
                "suggested_action": "WARN"
            }

        return {
            "is_safe": True,
            "category": None,
            "label": "Chưa có dấu hiệu khớp quy tắc",
            "confidence": 0.0,
            "reason": None,
            "suggested_action": "ALLOW"
        }

if __name__ == "__main__":
    analyzer = AITextAnalyzer()
    samples = [
        "Cách giải bài tập phương trình bậc hai Toán lớp 9",
        "Xem phim 18+ gái xinh lộ clip nóng Full HD",
        "Trang chủ cá cược bóng đá tài xỉu trực tuyến uy tín",
        "Hướng dẫn lập trình Python với Scratch",
        "Cách tự tử không đau đớn"
    ]
    for s in samples:
        res = analyzer.analyze(s)
        print(f"Text: '{s}' -> An toàn: {res['is_safe']} | {res.get('label')} ({res.get('confidence')})")
