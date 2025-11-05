# coding: utf-8

# flake8: noqa: F403
# flake8: noqa: F405

from .dimension_nodes import *
from .image_processing import *
from .string_nodes import *
from .utils import *

NODE_CLASS_MAPPINGS = {
    "StringContainsKeywordNode": StringContainsKeywordNode,
    "StringSelectNode": StringSelectNode,
    "FindBestAspectRatio": FindBestAspectRatio,
    "FindBestAspectRatioV2": FindBestAspectRatioV2,
    "AdjustToAspectRatio": AdjustToAspectRatio,
    "GetOutputSize": GetOutputSize,
    "ShowText": ShowText,
    "StringAddNode": StringAddNode,
    "StringReplaceNode": StringReplaceNode,
    "GetImageRange": GetImageRange,
    "CalculateDimensionsByArea": CalculateDimensionsByArea,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "StringContainsKeywordNode": "String Contains Keyword Node",
    "StringSelectNode": "String Select Node",
    "FindBestAspectRatio": "Find Best Aspect Ratio",
    "FindBestAspectRatioV2": "Find Best Aspect Ratio V2",
    "AdjustToAspectRatio": "Adjust To Aspect Ratio",
    "GetOutputSize": "Get Output Size",
    "CalculateDimensionsByArea": "Calculate Dimensions By Area",
    "ShowText": "Show Text",
    "StringAddNode": "String Add Node",
    "StringReplaceNode": "String Replace Node",
    "GetImageRange": "Get Image Range",
}


try:
    from .image_processing import *

    NODE_CLASS_MAPPINGS.update(
        {
            "LoadImageFromURL": LoadImageFromURL,
        }
    )
    NODE_DISPLAY_NAME_MAPPINGS.update(
        {
            "LoadImageFromURL": "Load Image From URL",
        }
    )
except ImportError:
    pass
