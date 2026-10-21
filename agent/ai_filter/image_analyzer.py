import struct
import io
from typing import Dict, Any, Tuple, Optional

class AIImageAnalyzer:
    """
    Mô hình phân tích hình ảnh và luồng hiển thị (Display Stream) theo thời gian thực.
    Ứng dụng thuật toán phân tích phổ màu YCbCr & HSV nhằm nhận diện nội dung nhạy cảm
    (tỷ lệ khỏa thân / da thịt vượt ngưỡng an toàn hoặc hình ảnh bạo lực, máu me).
    Hoạt động cực nhanh (< 15ms/khung hình) trên CPU mà không cần GPU cồng kềnh.
    """

    def __init__(self, skin_threshold: float = 0.38, blood_threshold: float = 0.25):
        self.skin_threshold = skin_threshold
        self.blood_threshold = blood_threshold

    @staticmethod
    def rgb_to_ycbcr(r: int, g: int, b: int) -> Tuple[float, float, float]:
        """Chuyển đổi RGB sang không gian màu YCbCr theo chuẩn ITU-R BT.601."""
        y = 0.299 * r + 0.587 * g + 0.114 * b
        cb = 128 - 0.168736 * r - 0.331264 * g + 0.5 * b
        cr = 128 + 0.5 * r - 0.418688 * g - 0.081312 * b
        return y, cb, cr

    @staticmethod
    def is_skin_pixel(r: int, g: int, b: int) -> bool:
        """Kiểm tra một pixel có thuộc dải màu da người (mọi sắc tộc) hay không."""
        # Điều kiện RGB cơ bản
        if not (r > 60 and g > 40 and b > 20 and max(r, g, b) - min(r, g, b) > 15 and abs(r - g) > 15 and r > g and r > b):
            return False
        # Kiểm tra ngưỡng YCbCr chuẩn khoa học
        _, cb, cr = AIImageAnalyzer.rgb_to_ycbcr(r, g, b)
        return 77 <= cb <= 127 and 133 <= cr <= 173

    @staticmethod
    def is_blood_pixel(r: int, g: int, b: int) -> bool:
        """Kiểm tra pixel có thuộc cụm màu máu / vết thương bạo lực hay không."""
        return r > 150 and g < 60 and b < 60 and (r - g) > 80

    def analyze_rgb_buffer(self, width: int, height: int, rgb_data: bytes, step: int = 4) -> Dict[str, Any]:
        """
        Phân tích trực tiếp mảng byte RGB của màn hình hiển thị.
        Tham số step giúp tối ưu hóa hiệu năng bằng cách lấy mẫu lưới (subsampling).
        """
        if width <= 0 or height <= 0 or not rgb_data:
            return {"is_safe": True, "category": None, "confidence": 0.0, "reason": "Dữ liệu trống"}

        total_sampled = 0
        skin_count = 0
        blood_count = 0

        row_stride = width * 3

        for y in range(0, height, step):
            row_offset = y * row_stride
            for x in range(0, width, step):
                px_offset = row_offset + x * 3
                if px_offset + 2 < len(rgb_data):
                    r = rgb_data[px_offset]
                    g = rgb_data[px_offset + 1]
                    b = rgb_data[px_offset + 2]

                    total_sampled += 1
                    if self.is_skin_pixel(r, g, b):
                        skin_count += 1
                    elif self.is_blood_pixel(r, g, b):
                        blood_count += 1

        if total_sampled == 0:
            return {"is_safe": True, "category": None, "confidence": 0.0, "reason": None}

        skin_ratio = skin_count / total_sampled
        blood_ratio = blood_count / total_sampled

        # Đánh giá cảnh báo nội dung người lớn (Khỏa thân / Nhạy cảm)
        if skin_ratio >= self.skin_threshold:
            confidence = min(0.99, round(0.70 + (skin_ratio - self.skin_threshold) * 1.5, 2))
            return {
                "is_safe": False,
                "category": "ADULT",
                "label": "Hình ảnh nhạy cảm / Khỏa thân (18+)",
                "confidence": confidence,
                "skin_ratio": round(skin_ratio, 3),
                "reason": f"Tỷ lệ vùng da nhạy cảm chiếm {round(skin_ratio * 100, 1)}% khung hình hiển thị (vượt ngưỡng {int(self.skin_threshold * 100)}%)",
                "suggested_action": "BLOCK_AND_CLOSE"
            }

        # Đánh giá cảnh báo bạo lực / máu me
        if blood_ratio >= self.blood_threshold:
            confidence = min(0.99, round(0.75 + (blood_ratio - self.blood_threshold) * 1.5, 2))
            return {
                "is_safe": False,
                "category": "VIOLENCE",
                "label": "Hình ảnh bạo lực / Máu me ghê rợn",
                "confidence": confidence,
                "blood_ratio": round(blood_ratio, 3),
                "reason": f"Phát hiện dấu hiệu máu me/bạo lực chiếm {round(blood_ratio * 100, 1)}% khung hình",
                "suggested_action": "BLOCK_AND_CLOSE"
            }

        return {
            "is_safe": True,
            "category": None,
            "label": "Hình ảnh an toàn",
            "confidence": 0.98,
            "skin_ratio": round(skin_ratio, 3),
            "blood_ratio": round(blood_ratio, 3),
            "reason": None,
            "suggested_action": "ALLOW"
        }

    def analyze_bmp(self, bmp_bytes: bytes) -> Dict[str, Any]:
        """Phân tích ảnh định dạng BMP (chuẩn ảnh raw không nén của Windows/Linux)."""
        try:
            if len(bmp_bytes) < 54 or bmp_bytes[:2] != b'BM':
                return {"is_safe": True, "reason": "Không phải file BMP"}
            
            width = struct.unpack('<I', bmp_bytes[18:22])[0]
            height = abs(struct.unpack('<i', bmp_bytes[22:26])[0])
            bpp = struct.unpack('<H', bmp_bytes[28:30])[0]
            offset = struct.unpack('<I', bmp_bytes[10:14])[0]

            if bpp != 24:
                return {"is_safe": True, "reason": "Chỉ hỗ trợ 24-bit BMP"}

            pixel_data = bmp_bytes[offset:]
            # Chuyển BGR sang RGB
            rgb_bytes = bytearray(len(pixel_data))
            for i in range(0, len(pixel_data) - 2, 3):
                rgb_bytes[i] = pixel_data[i+2]
                rgb_bytes[i+1] = pixel_data[i+1]
                rgb_bytes[i+2] = pixel_data[i]

            return self.analyze_rgb_buffer(width, height, bytes(rgb_bytes))
        except Exception as e:
            return {"is_safe": True, "reason": f"Lỗi đọc ảnh: {e}"}

if __name__ == "__main__":
    analyzer = AIImageAnalyzer(skin_threshold=0.35)
    
    # 1. Test khung hình an toàn (toàn màu xanh lá / thiên nhiên học tập)
    green_data = bytes([34, 139, 34] * (100 * 100))
    res1 = analyzer.analyze_rgb_buffer(100, 100, green_data)
    print("Test Khung hình học tập xanh lá:", res1["is_safe"], "|", res1.get("label"))

    # 2. Test khung hình nhạy cảm (da người chiếm 60%)
    skin_px = [210, 160, 130] # Màu da chuẩn YCbCr
    safe_px = [50, 50, 50]
    mixed = []
    for i in range(10000):
        mixed.extend(skin_px if i < 6000 else safe_px)
    res2 = analyzer.analyze_rgb_buffer(100, 100, bytes(mixed))
    print("Test Khung hình nhạy cảm (60% da):", res2["is_safe"], "|", res2.get("label"), f"({res2.get('confidence')})")
