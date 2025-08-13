from .base import NODE_CATEGORY

BIGMAX = 2**53 - 1


class GetImageRange:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "images": ("IMAGE",),
                "start": ("INT", {"default": 0, "min": 0, "max": BIGMAX, "step": 1}),
                "end": ("INT", {"default": 1, "min": 1, "max": BIGMAX, "step": 1}),
            },
        }

    RETURN_TYPES = ("IMAGE",)
    RETURN_NAMES = ("images",)
    FUNCTION = "get_first"
    CATEGORY = NODE_CATEGORY

    def get_first(self, images, start=0, end=1):
        return (images[start:end],)
