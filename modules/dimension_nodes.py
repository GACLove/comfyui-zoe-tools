from .base import NODE_CATEGORY


class FindBestAspectRatio:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "width": ("INT", {"default": 1024, "min": 64, "max": 8192}),
                "height": ("INT", {"default": 1024, "min": 64, "max": 8192}),
            }
        }

    RETURN_TYPES = ("INT", "INT")
    RETURN_NAMES = ("ratio_width", "ratio_height")
    FUNCTION = "find_ratio"
    CATEGORY = NODE_CATEGORY

    def find_ratio(self, width, height):
        common_ratios = [
            (16, 9),
            (9, 16),
            (1, 1),
            (3, 2),
            (2, 3),
        ]
        original_ratio = width / height
        best_ratio = min(common_ratios, key=lambda r: abs(r[0] / r[1] - original_ratio))
        return best_ratio


def gcd(a: int, b: int) -> int:
    while b:
        a, b = b, a % b
    return a


class FindBestAspectRatioV2:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "width": ("INT", {"default": 1024, "min": 64, "max": 8192}),
                "height": ("INT", {"default": 1024, "min": 64, "max": 8192}),
                "find_best_ratio": (
                    "BOOLEAN",
                    {
                        "default": True,
                        "suggestions": ["True", "False"],
                        "placeholder": "False 则计算输入宽高比, True 则查找最接近的标准宽高比",
                    },
                ),
                "aspect_ratio": (
                    "STRING",
                    {
                        "default": "",
                        "multiline": False,
                        "suggestions": [
                            "1:1",
                            "16:9",
                            "9:16",
                            "3:2",
                            "2:3",
                            "4:3",
                            "21:9",
                        ],
                        "placeholder": "输入格式: 数字:数字 (例如 16:9)，如果为空则计算输入宽高比，否则直接使用的指定宽高比",
                    },
                ),
            }
        }

    RETURN_TYPES = ("INT", "INT")
    RETURN_NAMES = ("ratio_width", "ratio_height")
    FUNCTION = "process_dimensions"
    CATEGORY = NODE_CATEGORY

    def validate_aspect_ratio(self, aspect_ratio: str) -> tuple[float, float]:
        if ":" not in aspect_ratio:
            raise ValueError("格式必须是 'width:height'")

        w_ratio, h_ratio = aspect_ratio.split(":")
        w_ratio = float(w_ratio.strip())
        h_ratio = float(h_ratio.strip())

        if w_ratio <= 0 or h_ratio <= 0:
            raise ValueError("宽高比必须为正数")

        return (w_ratio, h_ratio)

    def calculate_ratio(self, width: int, height: int) -> tuple[int, int]:
        divisor = gcd(width, height)
        return (width // divisor, height // divisor)

    def find_best_ratio(self, width: int, height: int) -> tuple[int, int]:
        common_ratios = [
            (1, 1),
            (1, 2),
            (2, 1),
            (2, 3),
            (3, 2),
            (3, 4),
            (4, 3),
            (9, 16),
            (16, 9),
            (9, 21),
            (21, 9),
        ]
        original_ratio = width / height
        best_ratio = min(common_ratios, key=lambda r: abs(r[0] / r[1] - original_ratio))
        return best_ratio

    def process_dimensions(
        self, width: int, height: int, find_best_ratio: bool, aspect_ratio: str
    ) -> tuple[int, int]:
        if aspect_ratio.strip():
            target_ratio = self.validate_aspect_ratio(aspect_ratio)
            return self.calculate_ratio(int(target_ratio[0]), int(target_ratio[1]))

        if find_best_ratio:
            return self.find_best_ratio(width, height)

        return self.calculate_ratio(width, height)


class AdjustToAspectRatio:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "ratio_width": ("INT", {"default": 16, "min": 1, "max": 21}),
                "ratio_height": ("INT", {"default": 9, "min": 1, "max": 21}),
                "origin_width": ("INT", {"default": 1024, "min": 64, "max": 8192}),
                "origin_height": ("INT", {"default": 1024, "min": 64, "max": 8192}),
                "min_stride": ("INT", {"default": 16, "min": 8, "max": 64}),
                "max_area": ("INT", {"default": 768 * 1360, "min": 1, "max": 1044480}),
                "min_area": ("INT", {"default": 640 * 1136, "min": 1, "max": 727040}),
            }
        }

    RETURN_TYPES = ("INT", "INT")
    RETURN_NAMES = ("adjusted_width", "adjusted_height")
    FUNCTION = "adjust"
    CATEGORY = NODE_CATEGORY

    def adjust(
        self,
        ratio_width,
        ratio_height,
        origin_width,
        origin_height,
        min_stride=16,
        max_area=768 * 1360,
        min_area=640 * 1136,
    ):
        assert origin_width >= 300 and origin_height >= 300
        assert min_area <= max_area

        target_ratio = ratio_width / ratio_height
        original_ratio = origin_width / origin_height

        min_w_offset = ratio_width * min_stride
        min_h_offset = ratio_height * min_stride

        if (
            abs(target_ratio - original_ratio) < 0.001
            and origin_width * origin_height <= max_area
            and origin_width * origin_height >= min_area
        ):
            width_divided_by_min_stride = int(origin_width // min_stride) * min_stride
            height_divided_by_min_stride = int(origin_height // min_stride) * min_stride

            while width_divided_by_min_stride * height_divided_by_min_stride < min_area:
                width_divided_by_min_stride += min_w_offset
                height_divided_by_min_stride += min_h_offset

            return (width_divided_by_min_stride, height_divided_by_min_stride)

        width_i = 300 // (ratio_width * min_stride)
        height_i = 300 // (ratio_height * min_stride)
        min_idx = min(width_i, height_i)
        new_width = ratio_width * min_stride * min_idx
        new_height = ratio_height * min_stride * min_idx

        cached_w, cached_h = new_width, new_height
        valid_result = None  # 用于记录满足 min_area 的最优解
        while new_width * new_height <= max_area:
            if new_width * new_height >= min_area:
                valid_result = (int(new_width), int(new_height))
            cached_w, cached_h = new_width, new_height
            new_width = cached_w + min_w_offset
            new_height = cached_h + min_h_offset

        if valid_result:
            return valid_result

        return (int(cached_w), int(cached_h))


class GetOutputSize:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "ratio_width": ("INT", {"default": 16, "min": 1, "max": 21}),
                "ratio_height": ("INT", {"default": 9, "min": 1, "max": 21}),
                "min_size": ("INT", {"default": 720, "min": 300, "max": 4096}),
            }
        }

    RETURN_TYPES = ("INT", "INT")
    RETURN_NAMES = ("output_width", "output_height")
    FUNCTION = "calculate"
    CATEGORY = NODE_CATEGORY

    def calculate(self, ratio_width, ratio_height, min_size=720):
        target_ratio = ratio_width / ratio_height
        if target_ratio < 1:
            new_width = min_size
            new_height = round(new_width / target_ratio)
        else:
            new_height = min_size
            new_width = round(new_height * target_ratio)
        return (new_width, new_height)
