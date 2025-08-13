from .base import NODE_CATEGORY


class StringContainsKeywordNode:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "input_string": ("STRING", {"default": "", "multiline": True}),
                "key_words": ("STRING", {"default": "", "multiline": True}),
            }
        }

    RETURN_TYPES = (["true", "false"],)
    RETURN_NAMES = ("true/false",)
    FUNCTION = "if_contains"
    CATEGORY = NODE_CATEGORY

    def if_contains(self, input_string, key_words):
        key_parts = [part.strip().lower() for part in key_words.split(",")]
        for part in key_parts:
            if part in input_string.lower():
                return ("true",)
        return ("false",)


class StringSelectNode:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "input_string1": ("STRING", {"default": "", "multiline": True}),
                "input_string2": ("STRING", {"default": "", "multiline": True}),
                "true_or_false": (["true", "false"], {}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("output_string",)
    FUNCTION = "select"
    CATEGORY = NODE_CATEGORY

    def select(self, input_string1, input_string2, true_or_false):
        return (input_string1,) if true_or_false == "true" else (input_string2,)


class StringAddNode:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "input_string1": ("STRING", {"default": "", "multiline": True}),
                "input_string2": ("STRING", {"default": "", "multiline": True}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("output_string",)
    FUNCTION = "add"
    CATEGORY = NODE_CATEGORY

    def add(self, input_string1, input_string2):
        return (input_string1 + "\n" + input_string2,)


class StringReplaceNode:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "input_string": ("STRING", {"default": "", "multiline": True}),
                "find_words": ("STRING", {"default": "{}", "multiline": True}),
                "replace_words": ("STRING", {"default": "", "multiline": True}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("output_string",)
    FUNCTION = "replace"
    CATEGORY = NODE_CATEGORY

    def replace(self, input_string, find_words, replace_words):
        return (input_string.replace(find_words, replace_words),)


class ShowText:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "text": ("STRING", {"forceInput": True}),
            },
        }

    INPUT_IS_LIST = True
    RETURN_TYPES = ("STRING",)
    FUNCTION = "notify"
    OUTPUT_NODE = True
    OUTPUT_IS_LIST = (True,)
    CATEGORY = NODE_CATEGORY

    def notify(self, text):
        return {"ui": {"text": text}, "result": (text,)}
