import re
from typing import Dict, Any, List

# Từ điển và mẫu ngữ nghĩa phân loại nội dung AI đa ngôn ngữ (Tiếng Việt & Tiếng Anh)
INAPPROPRIATE_LEXICON = {
    "ADULT": {
        "label": "Nội dung người lớn (18+ / Khiêu dâm)",
        "weight": 0.95,
        "keywords": [
            "porn", "porno", "xxx", "sex", "hentai", "nsfw", "erotic", "nude", "naked",
            "khiêu dâm", "đồi trụy", "gái gọi", "phim người lớn", "phim cấp 3", "tình dục",
            "thủ dâm", "loạn luân", "lộ clip", "ảnh nóng", "khoả thân", "gái xinh cởi đồ",
            "show hàng", "kích dục", "mại dâm", "camshow", "xvideos", "pornhub", "xnxx",
            "redtube", "onlyfans"
        ],
        "patterns": [
            r"\b(p[o0]rn|s[e3]x|xxx)\b",
            r"(phim\s*(18\+|người\s*lớn|cấp\s*3))",
            r"(lộ\s*clip|ảnh\s*nóng|show\s*hàng)"
        ]
    },
    "GAMBLING": {
        "label": "Cờ bạc & Cá cược trực tuyến",
        "weight": 0.90,
        "keywords": [
            "casino", "bet", "betting", "poker", "baccarat", "roulette", "blackjack", "slot machine",
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
            "suicide", "kill myself", "blood", "beheading", "gore", "murder", "bomb making",
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
            r"\b(đ[m|ụ|ịt]\s*(má|mẹ))\b",
            r"\b(f[u|*]ck|b[i|*]tch)\b"
        ]
    }
}

class AITextAnalyzer:
    """Mô hình phân tích văn bản AI thời gian thực phát hiện nội dung độc hại."""

    def __init__(self):
        # Tiền biên dịch các biểu thức chính quy (Regex) để tăng tốc độ xử lý (< 1ms)
        self.compiled_rules = {}
        for category, info in INAPPROPRIATE_LEXICON.items():
            compiled_pats = [re.compile(p, re.IGNORECASE) for p in info.get("patterns", [])]
            self.compiled_rules[category] = {
                "label": info["label"],
                "weight": info["weight"],
                "keywords": set(kw.lower() for kw in info["keywords"]),
                "patterns": compiled_pats
            }

    def analyze(self, text: str) -> Dict[str, Any]:
        """
        Phân tích chuỗi văn bản (tiêu đề cửa sổ, URL, nội dung tìm kiếm...).
        Trả về kết quả đánh giá độ an toàn và mức độ tin cậy.
        """
        if not text:
            return {"is_safe": True, "category": None, "confidence": 0.0, "reason": None}

        clean_text = text.lower().strip()
        matched_categories = []

        for category, data in self.compiled_rules.items():
            detected_keywords = []
            
            # 1. So khớp từ khóa trực tiếp
            for kw in data["keywords"]:
                if kw in clean_text:
                    detected_keywords.append(kw)

            # 2. So khớp biểu thức Regex
            for pat in data["patterns"]:
                if pat.search(clean_text):
                    detected_keywords.append(pat.pattern)

            if detected_keywords:
                matched_categories.append({
                    "category": category,
                    "label": data["label"],
                    "confidence": min(0.99, data["weight"] + len(detected_keywords) * 0.02),
                    "matches": detected_keywords[:3]
                })

        if matched_categories:
            # Chọn loại vi phạm có độ tin cậy cao nhất
            matched_categories.sort(key=lambda x: x["confidence"], reverse=True)
            top = matched_categories[0]
            reason = f"Phát hiện {top['label']} qua từ khóa/mẫu: {', '.join(top['matches'])}"
            return {
                "is_safe": False,
                "category": top["category"],
                "label": top["label"],
                "confidence": round(top["confidence"], 2),
                "reason": reason,
                "suggested_action": "BLOCK_AND_CLOSE"
            }

        return {
            "is_safe": True,
            "category": None,
            "label": "Nội dung an toàn",
            "confidence": 0.98,
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
