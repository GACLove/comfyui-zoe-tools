import math

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
                "max_area": ("INT", {"default": 4096 * 4096, "min": 90000, "max": 16777216}),
                "min_area": ("INT", {"default": 300 * 300, "min": 90000, "max": 16777216}),
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

        valid_result = None
        closest_result = (new_width, new_height)

        while new_width * new_height <= max_area:
            current_area = new_width * new_height

            if current_area >= min_area:
                valid_result = (int(new_width), int(new_height))

            # 更新最接近 min_area 的结果
            if abs(current_area - min_area) < abs(closest_result[0] * closest_result[1] - min_area):
                closest_result = (new_width, new_height)

            new_width += min_w_offset
            new_height += min_h_offset

        if valid_result:
            return valid_result

        # 否则返回最接近 min_area 的结果
        return (int(closest_result[0]), int(closest_result[1]))


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


class CalculateDimensionsByArea:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "target_area": ("INT", {"default": 1024 * 1024, "min": 90000, "max": 16777216}),
                "ratio_width": ("INT", {"default": 16, "min": 1, "max": 21}),
                "ratio_height": ("INT", {"default": 9, "min": 1, "max": 21}),
                "alignment": ("INT", {"default": 32, "min": 8, "max": 64}),
            }
        }

    RETURN_TYPES = ("INT", "INT")
    RETURN_NAMES = ("width", "height")
    FUNCTION = "calculate_dimensions"
    CATEGORY = NODE_CATEGORY

    def calculate_dimensions(
        self,
        target_area,
        ratio_width,
        ratio_height,
        alignment=32,
    ):
        """
        根据目标面积和宽高比计算对齐后的尺寸

        Args:
            target_area: 目标面积（像素）
            ratio_width: 宽度比例
            ratio_height: 高度比例
            alignment: 对齐值（默认32）

        Returns:
            (width, height): 对齐后的宽度和高度
        """
        # 计算比例
        ratio = ratio_width / ratio_height

        # 根据面积和比例计算宽度
        # area = width * height = width * (width / ratio)
        # width^2 = area * ratio
        width = math.sqrt(target_area * ratio)
        height = width / ratio

        # 对齐到指定的倍数
        width = round(width / alignment) * alignment
        height = round(height / alignment) * alignment

        return (int(width), int(height))


class AutoResolutionByPixels:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "ratio_mode": (["image", "custom"],),
                "custom_ratio": (
                    "FLOAT",
                    {
                        "default": 1.777777,
                        "min": 0.05,
                        "max": 20.0,
                        "step": 0.001,
                    },
                ),
                "megapixels": (
                    "FLOAT",
                    {
                        "default": 1.0,
                        "min": 0.01,
                        "max": 16.0,
                        "step": 0.01,
                    },
                ),
                "multiple": (
                    "INT",
                    {
                        "default": 32,
                        "min": 1,
                        "max": 256,
                        "step": 1,
                    },
                ),
            },
            "optional": {
                "image": ("IMAGE",),
            },
        }

    RETURN_TYPES = ("INT", "INT", "FLOAT")
    RETURN_NAMES = ("width", "height", "ratio")
    FUNCTION = "calculate"
    CATEGORY = "utils/resolution"

    def calculate(self, ratio_mode, custom_ratio, megapixels, multiple, image=None):
        if megapixels <= 0:
            raise ValueError("Megapixels must be positive")
        if multiple <= 0:
            raise ValueError("Multiple must be positive")

        if ratio_mode == "image":
            if image is None:
                raise ValueError("Image is required when ratio mode is 'image'")

            source_h = int(image.shape[1])
            source_w = int(image.shape[2])
            if source_h <= 0 or source_w <= 0:
                raise ValueError("Image width and height must be positive")

            ratio = source_w / source_h
        elif ratio_mode == "custom":
            if custom_ratio <= 0:
                raise ValueError("Custom ratio must be positive")
            ratio = custom_ratio
        else:
            raise ValueError(f"Unsupported ratio mode: {ratio_mode}")

        total_pixels = megapixels * 1024 * 1024

        target_h = math.sqrt(total_pixels / ratio)
        target_w = target_h * ratio

        target_w = max(multiple, round(target_w / multiple) * multiple)
        target_h = max(multiple, round(target_h / multiple) * multiple)

        return (int(target_w), int(target_h), float(ratio))
