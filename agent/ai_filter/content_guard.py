import asyncio
import json
import urllib.request
from typing import Optional, Dict, Any

from .text_analyzer import AITextAnalyzer
from .image_analyzer import AIImageAnalyzer

class AIContentGuard:
    """
    Bộ điều phối AI Content Filtering bảo vệ trẻ em theo thời gian thực trên luồng hiển thị.
    Phối hợp phân tích văn bản và phân tích thị giác để ngăn chặn nội dung độc hại.
    """

    def __init__(self, backend_url: str = "http://127.0.0.1:8008", ws_callback=None):
        self.backend_url = backend_url
        self.ws_callback = ws_callback
        self.text_analyzer = AITextAnalyzer()
        self.image_analyzer = AIImageAnalyzer()
        self.is_active = True
        self.recent_alerts = set()

    def inspect_text(self, text: str, source_name: str = "Cửa sổ") -> Optional[Dict[str, Any]]:
        """Kiểm tra văn bản (tiêu đề cửa sổ, url, thanh tìm kiếm)."""
        if not self.is_active or not text:
            return None

        result = self.text_analyzer.analyze(text)
        if not result["is_safe"]:
            alert_key = f"{result['category']}_{text[:20]}"
            if alert_key not in self.recent_alerts:
                self.recent_alerts.add(alert_key)
                self.report_violation(
                    source=source_name,
                    category=f"AI_CONTENT_{result['category']}",
                    reason=result["reason"],
                    confidence=result["confidence"]
                )
            return result
        return None

    def inspect_image_buffer(self, width: int, height: int, rgb_bytes: bytes, source_name: str = "Màn hình") -> Optional[Dict[str, Any]]:
        """Kiểm tra luồng hiển thị hình ảnh màn hình."""
        if not self.is_active or not rgb_bytes:
            return None

        result = self.image_analyzer.analyze_rgb_buffer(width, height, rgb_bytes)
        if not result["is_safe"]:
            self.report_violation(
                source=source_name,
                category=f"AI_CONTENT_{result['category']}",
                reason=result["reason"],
                confidence=result["confidence"]
            )
            return result
        return None

    def report_violation(self, source: str, category: str, reason: str, confidence: float):
        """Gửi báo cáo vi phạm tức thời về Backend và thông báo qua WebSocket."""
        print(f"\n🚨 [AI CONTENT FILTER ĐÃ CHẶN]: {reason} (Độ tin cậy: {int(confidence * 100)}%)")

        # 1. Gửi qua REST API tới Backend
        try:
            payload = json.dumps({
                "target_value": source,
                "reason": f"[AI Filter] {reason}",
                "category": category,
                "is_web": True
            }).encode("utf-8")
            req = urllib.request.Request(
                f"{self.backend_url}/alerts/",
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            urllib.request.urlopen(req, timeout=1.5)
        except Exception:
            pass

        # 2. Phát tín hiệu thời gian thực nếu có WebSocket
        if self.ws_callback:
            try:
                self.ws_callback({
                    "type": "AI_CONTENT_VIOLATION",
                    "source": source,
                    "category": category,
                    "reason": reason,
                    "confidence": confidence
                })
            except Exception:
                pass
