#!/usr/bin/env python3
"""Router split-fix3 PE baseline, adapted to accept per-run prompt templates.

Based on the supplied t2i_pe_core.py Router path; rendering and CLI are excluded.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import logging
import os
import re
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

VERSION = "split-fix3"
ARM = "split_fix3"
DEFAULT_MODEL = "gpt-5.6-terra"
DEFAULT_BASE_URL = "https://api.edgecloudapp.com/v2/llm/openai"
DEFAULT_REASONING_EFFORT = "none"
DEFAULT_MAX_TOKENS = 2048
DEFAULT_SERVICE_TIER = "priority"
USER_MARKER = "{{USER_VISUAL_REQUEST}}"
BASE_URL: str | None = None
DEFAULT_PROFILE = DEFAULT_MODEL
MODEL_PROFILES = {DEFAULT_PROFILE: {"model": DEFAULT_MODEL}}
AUTO_CANVAS_PRESETS = {
    "1:1": (2048, 2048),
    "16:9": (2720, 1536),
    "9:16": (1536, 2720),
    "3:2": (2496, 1664),
    "2:3": (1664, 2496),
    "4:3": (2368, 1760),
    "3:4": (1760, 2368),
    "1:2": (1440, 2880),
    "2:1": (2880, 1440),
    "1:3": (1152, 3456),
    "3:1": (3456, 1152),
}
DEFAULT_AUTO_CANVAS_RATIO = "1:1"
DEFAULT_AUTO_CANVAS_WH = AUTO_CANVAS_PRESETS[DEFAULT_AUTO_CANVAS_RATIO]
AUTO_CANVAS_GUIDANCE = """ROUTER AUTO-CANVAS REQUIREMENT
No output size was given. Pick the single best aspect ratio and matching W/H for the request.
Choose exactly one preset (ratio: W x H):
1:1: 2048 x 2048; 16:9: 2720 x 1536; 9:16: 1536 x 2720;
3:2: 2496 x 1664; 2:3: 1664 x 2496; 4:3: 2368 x 1760; 3:4: 1760 x 2368.
Honor any ratio/orientation stated explicitly. Otherwise match orientation to the content's shape, not a default-tall habit:
wide (16:9/3:2) for time-series, horizontal timelines, wide maps, multi-column tables;
square (1:1/4:3) for 2x2 matrices, quadrants, grids, mind maps, radial/cycle;
tall (9:16/2:3/3:4) for vertical flows, funnels, ranked lists, single-column resumes, mobile posters.
Never force a 2x2 into 9:16 or a wide chart into tall.
Write H and W as positive JSON integers and aspect_ratio exactly as the chosen ratio."""
logger = logging.getLogger("T2I PE")


# ===== prompt 明文常量（内联自原 t2i_pe_split_fix3.py）=====
SYSTEM_PROMPT = r"""You are a helpful assistant.

Given the user's natural-language request below, generate a dense structured JSON that fully describes the portion of the image assigned to this parallel shard. The JSON must strictly follow the template after the request, including every top-level key and every nested subfield.

The output is always dense. Even when the request is brief, infer plausible, scene-consistent details for every field. Do not leave a field empty merely because the request did not mention it. Be creative but stay grounded: preserve the request's concrete visual design and depicted moment. Inferred additions must be physically plausible, naturally varied where appropriate, and internally consistent with the request. When a detail is restated across fields, keep it consistent without progressively amplifying or regularizing it.

OVERALL OUTPUT GOAL
The final result must be a complete structured JSON that can be used directly for image generation. Four parallel shards jointly produce the complete JSON:
- A · Subjects: describes the main subjects, their appearance, actions, counts, and relationships.
- B · Spatial: describes the environment, background, overall layout, regional occupancy, and spatial relationships.
- C · Visual direction: describes lighting, aesthetics, composition, camera, medium, and artistic style.
- D · Delivery and text: describes the scene's purpose and supplies the closed whitelist of visible text so every promised text region is renderable without pseudo-text."""


A_SUBJECTS_PROMPT = r"""CURRENT SHARD TASK: A · SUBJECTS
Generate only `subjects` and `subject_details`. Read the complete user request and accurately extract every visible subject and every directly subject-related fact that affects the rendered image.

PURPOSE OF THIS SHARD
- `subjects`: each primary scene anchor or independently acting entity — appearance, location, orientation, pose, count, relations.
- `subject_details`: constraints not fitting the fixed fields — cross-subject layout, order, exact counts, stage consistency, geometry.

BOUNDARIES WITH OTHER SHARDS
- B owns the environment and global spatial layout; retain only each subject's own location and relationships between subjects here.
- C owns lighting, color, composition, camera and artistic style; do not expand those topics in subject descriptions.
- D owns literal visible copy; do not repeat or paraphrase the text inventory here.
- Do not omit a fact required to describe a subject merely because it also affects another shard; keep it scoped to subject semantics.

NOTES
- Write descriptive values in concise English; each string a short renderable phrase without explanation, rationale or decorative inference.
- One subject object per primary scene anchor or independently acting entity. Put contained, attached, worn, held or surface-arranged components inside that subject or in `subject_details`; do not split every small prop into a separate subject.
- Preserve every explicitly requested location, orientation, action, count and relationship; when unspecified add only brief plausible detail.
- For every field here, write specific content keeping the request's explicitly requested visual distinctions perceptible.
- If the request names an unusual overall layout (spiral/螺旋, radial/放射, ring/环形, fan-step/扇形, S-curve, staircase, isometric), restate that shape in `subject_details` in the user's own shape words and make each subject's `location` and `orientation` follow it; never flatten it to a grid or row.
- MANDATORY, every subject: surfaces (skin, food, fur, fabric, props) default to matte, with texture described as it reads at normal viewing distance rather than strand-by-strand or pore-by-pore. Use gloss/sheen/glisten/wet-look only on a surface the request calls glossy, once, and never echo it onto another subject. Hair keeps real highlights as soft diffuse sheen that follows the strand flow and breaks up over curls and layers.
- MANDATORY per human: `skin_tone_and_texture` names >=2 CONCRETE TEXTURE details (visible pores, vellus hair, fine skin grain, uneven matte zones, subsurface warmth). Generic-only (smooth/fine/natural/healthy/clear/flawless) or waxy/airbrushed/porcelain/plastic is rejected.
- Set `artifact_type` for this shard: `text_led_graphic` for a flat reading surface (infographic, chart, table, diagram, slide, UI, résumé, menu); `natural_image` for a scene (photo, portrait, landscape, product, illustrated or 3D). Judge by visual subject, not the user's label: a poster/cover/KV built on a photographic- or illustration-grade scene is `natural_image`.
- For `text_led_graphic`, leave person fields empty ("" or 0): clothing, expression, gender, age, skin_tone_and_texture, facial_features, number_of_arms/legs/hands/fingers; describe graphic blocks, panels, icons, data elements as subjects.

- Empty values ("", 0, [], {}) only for truly inapplicable fields; count and anatomy fields are JSON integers, never numeric strings.
- Never add keys outside the template or omit required keys.
- Aim for about 500 completion tokens; requests with many explicit or structurally necessary constraints may exceed it rather than lose information.
- Return only the JSON object, no Markdown fences or prose outside JSON.

USER VISUAL REQUEST:
{{USER_VISUAL_REQUEST}}

Lists may contain zero or more items of the shape shown. Every top-level key must always be present; fill unused fields with "", 0, {}, or [] as appropriate.

{
  "subjects": [
    {
      "description": "full visual description of the subject",
      "appearance_details": "additional visual details such as accessories, texture, and distinguishing features",
      "relationship": "how this subject relates to others or to the scene",
      "location": "where the subject is in frame, for example center foreground or top right",
      "relative_size": "size of the subject within the frame",
      "orientation": "direction the subject faces relative to the camera",
      "pose": "body position and posture; for limb/hand actions name each joint connection and limb direction, keeping limbs attached, unduplicated, un-crossed",
      "clothing": "clothing and accessories; empty string if non-human or not applicable",
      "expression": "facial expression; empty string if non-human or not applicable",
      "gender": "Male, Female, Unknown, or N/A",
      "age": "age category",
      "skin_tone_and_texture": "skin tone and surface texture; empty string if non-human",
      "facial_features": "notable facial features; empty string if non-human or not visible",
      "number_of_subjects": "integer; total in this subject group, 0 if not applicable",
      "number_of_arms": "integer; normally 2 per human subject, 0 if non-human",
      "number_of_legs": "integer; normally 2 per human subject, 0 if non-human",
      "number_of_hands": "integer; normally 2 per human subject, 0 if non-human",
      "number_of_fingers": "integer; normally 10 per human subject, 0 if non-human"
    }
  ],
  "subject_details": {
    "key_name_1": "free-form image-specific attribute; empty object if not applicable"
  },
  "artifact_type": "exactly one of: text_led_graphic | natural_image"
}"""


B_SPATIAL_PROMPT = r"""CURRENT SHARD TASK: B · SPATIAL
Generate only `background_setting`, `quadrant_scan`, `resolution`, and `aspect_ratio`. Read the complete user request and establish a clear, unambiguous scene structure that remains faithful to the request.

PURPOSE OF THIS SHARD
- `background_setting`: the environment, major surfaces or functional zones, and the scene-wide arrangement of subjects and key objects.
- `quadrant_scan`: main contents of the top-left, top-right, bottom-left, bottom-right and absolute-center regions, reinforcing explicit spatial constraints.
- `resolution` and `aspect_ratio`: canvas fields required by the complete JSON; final values are overwritten by runtime parameters after merging.

BOUNDARIES WITH OTHER SHARDS
- A owns subject appearance, clothing, anatomy, expression and action. Spatial text may briefly name subjects and actions to remove layout ambiguity, but must not repeat full subject descriptions.
- C owns compositional aesthetics, camera, lighting, color, mood and style; keep those out of the environment and quadrant fields.
- D owns scene purpose and visible text; never expand copy, typography or text hierarchy here.
- Express each spatial constraint in the single most appropriate place; repeat between the overall setting and an exact region only when it materially reduces ambiguity.

NOTES
- Write `background_setting` as two or three focused sentences on environment, major zones and scene-wide arrangement.
- When the request implies a shallow-depth photograph, write the out-of-focus zones of `background_setting` and `quadrant_scan` as soft shapes, light pools and colour masses instead of readable detail, so the background agrees with the focal plane.
- Write each `quadrant_scan` value as one or two short phrases naming occupants and any needed placement, count, order, orientation or geometry.
- CONNECTIONS ARE DIRECTIONAL: for arrows, leader lines, connectors or brackets, `background_setting` states each link as `from <start> to <end>, pointing <direction>` — never merely that arrows exist; `quadrant_scan` says whether a link starts, passes or ends there, so a cross-region connector keeps one direction.
- MAP REQUESTS: put each marker at its true compass bearing (e.g. northwest inland, east coast) and run its leader line to its own card, never onto another card.
- Preserve every explicitly requested left/right, top/bottom, foreground/background, layer, panel, grid, relative position, shared reference viewpoint and geometric relationship. If an unusual overall layout is named (spiral/螺旋, radial/放射, ring/环形, fan-step/扇形, S-curve, staircase, isometric), the environment and every `quadrant_scan` value must trace that same shape in the user's words, never a plain grid.
- For every field here, write specific content keeping the request's explicitly requested visual distinctions perceptible.
- Never invent subjects or decorations just to fill a quadrant; for an empty region describe a plausible continuation of the background or negative space.
- Never add keys outside the template or omit required keys.
- Aim for about 500 completion tokens; requests with many explicit or structurally necessary constraints may exceed it rather than lose information.
- Return only the JSON object, no Markdown fences or prose outside JSON.

USER VISUAL REQUEST:
{{USER_VISUAL_REQUEST}}

Every top-level key must always be present. Canvas fields that will later be overwritten must still be returned according to the template.

{
  "background_setting": "full prose description of the environment and setting",
  "quadrant_scan": {
    "top_left": "description of what appears in the top-left region",
    "top_right": "description of what appears in the top-right region",
    "bottom_left": "description of what appears in the bottom-left region",
    "bottom_right": "description of what appears in the bottom-right region",
    "absolute_center": "description of what appears at the absolute center; note when a region sits outside the focal plane"
  },
  "resolution": {
    "H": "will be overwritten by the selected resolution and aspect ratio",
    "W": "will be overwritten by the selected resolution and aspect ratio"
  },
  "aspect_ratio": "will be overwritten by the selected aspect ratio"
}"""


C_DIRECTION_PROMPT = r"""CURRENT SHARD TASK: C · VISUAL DIRECTION
Generate only `lighting`, `aesthetics`, `cinematography`, `style_medium`, and `artistic_style`. Read the complete user request and establish one coherent, executable rendering direction for the same scene.

PURPOSE OF THIS SHARD
- `lighting`: defines light conditions, direction, shadows, and the overall illumination effect.
- `aesthetics`: defines compositional strategy, color system, mood, and visual patterns.
- `cinematography`: framing, camera position, depth of field, focus, lens language.
- `style_medium` and `artistic_style`: define the image medium and specific artistic treatment.

BOUNDARIES WITH OTHER SHARDS
- A owns subject identity, appearance, action, count, and relationships; do not fully redescribe subjects in visual-direction fields.
- B owns environmental contents, regional occupancy and exact spatial relationships; `aesthetics.composition` expresses compositional strategy without creating a second competing object layout.
- D owns scene purpose and literal visible copy; you may plan hierarchy, contrast and negative space for an explicitly text-bearing artifact, but never repeat any copy.
- Every visual choice must support the request's subject and spatial constraints without changing counts, positions, relationships or the depicted moment.

NOTES
- Preserve explicitly requested medium, artistic style, palette, lighting, camera and composition requirements first.
- When unspecified, add one mutually consistent set of visual choices for the scene; do not stack conflicting style or camera terminology.
- MANDATORY for `natural_image`: `depth_of_field` is a PHRASE naming the focal plane, the falloff, and HOW FAR the background dissolves — state whether out-of-focus areas keep recognisable shapes or melt into pure colour and light with no identifiable objects, and match that to the request; a bare Shallow/Deep/Uniform focus is rejected. Background softer than subject; never all legible, uniform sharpness or everything in focus. `focus` must name what is OUT of focus.
- `optical_character` applies ONLY when `artifact_type` is `natural_image` AND `style_medium` is photography: give this shot its real-lens behaviour — gentle edge falloff and corner softness, flare or halation when a light source faces the lens, and the shutter result for any motion (slight trailing blur or a frozen instant), plus faint colour fringing on high-contrast edges, progressive highlight rolloff and retained shadow detail rather than an HDR-mapped or clarity-slider finish. For illustration, 3D, ink, painterly or any `text_led_graphic` output, set it to none and keep the rendering clean.
- Classify the artifact in `artifact_type` (authoritative: this value decides whether photographic direction is kept or replaced with flat 2D values). Use exactly one of:
  - `text_led_graphic`: flat text-and-layout graphic, valued by READING: infographic, chart, table, diagram, flowchart, timeline, dashboard, slide, UI, résumé, menu, schematic, editorial layout.
  - `natural_image`: a real or imagined SCENE, valued by LOOKING: photography, portrait, landscape, still life, product shot, illustrated or 3D scene, character art.
  DECIDE BY THE VISUAL SUBJECT, NOT THE USER'S LABEL. If the main visual is a photographic- or illustration-grade scene, person, product or environment with copy composited on top, use `natural_image` — even if called poster, cover, KV, banner, album art, 海报/封面/主视觉; they need lighting, shadow, depth, reflection, atmosphere, material feel, which `text_led_graphic` strips away.
  Signals for `natural_image` despite poster wording: photo/photo-composite, 3D render, clay, cinematic or studio lighting, backlight/rim/golden hour, bokeh, reflection, glow, light particles, film grain, scene depth, named materials, a character.
  Choose `text_led_graphic` only when layout and copy THEMSELVES are the product — blocks, cells, axes, fields — with imagery as flat decoration; a flat vector or hand-drawn poster that is essentially typeset copy plus flat shapes still counts. A scene with incidental signage or a product label stays `natural_image`.
- Default `aesthetics.color_scheme`, `mood_atmosphere`, `lighting.illumination_effect` to true-to-life color, natural white balance, restrained grading; no oversaturation, heavy filtering, teal-orange push, crushed or milky contrast. Ban intensity words there (vivid, bright, brighten, lift, boost, pop, punchy, rich, lush, radiant, glowing); state white balance, exposure, contrast, highlight retention instead, and accept muted or flat tonality. Depart only on an explicit stylized/graded/high-saturation request.
- Default `style_medium` to authentic photography with physically real materials: natural surface texture, fine grain, subtle asymmetry; no plastic-smooth surfaces, over-clean environments or glossy CG. Use illustration/3D/CG only if explicitly asked; keep flat diagrams, UI, posters as clean 2D artifacts.
- MANDATORY: keep `lighting` restrained — even, believable intensity without stressed highlights or rendered finish. Restrained still means SHAPED: name one dominant light direction, a readable core shadow and terminator across the face or form, contact shadows where surfaces meet, and keep micro-shadow in pores, hair strands and fabric layers instead of flat all-over diffusion. Never call a photographic scene rendered, 3D render, or CGI.
- Default to natural, candid framing from a believable eye-level viewpoint with mild asymmetry, not rigid centered/symmetrical wallpaper layouts. Use centered/symmetrical composition only when the request or artifact type (poster, cover, formal portrait, product shot) calls for it.
- For every field here, write specific content keeping the request's explicitly requested visual distinctions perceptible.
- Flat diagrams, UI, tables and pure graphic designs use 2D-appropriate lighting and camera values; never force photographic depth of field or dramatic cast shadows.
- Text-led graphic (infographic/poster/diagram/chart/UI/map/résumé/图鉴/关卡图 etc., not a photo or illustrated scene): set `style_medium` to a flat 2D vector medium and `artistic_style` to the exact graphic style requested (e.g. flat vector infographic, cyberpunk UI, ink-and-paper, retro print); never photography, real materials, film grain, or depth-of-field. `aesthetics.color_scheme` must reproduce any requested dominant palette or per-element color coding verbatim, not a generic "limited flat palette".
- PRESERVE EXPLICIT NON-STANDARD GEOMETRY (CRITICAL): if the request names an unusual overall layout — spiral/螺旋, rotating-staircase/旋转楼梯, fan-step/扇形, radial/放射, ring/环形, isometric/等距, 3D-extruded, zig-zag, S-curve — `aesthetics.composition` MUST restate that exact geometry as the dominant strategy in the user's own shape words (curvature, rotation, depth); never replace it with generic grid / straight-axis / clean-margin phrasing that flattens it.
- Plan text space only when the request explicitly requires text or the artifact is inherently text-bearing; do not reserve an optional title area in an ordinary scene.
- Use "None" or "N/A" only for truly inapplicable fields.
- Do not add keys outside the template and do not omit required keys.
- Aim for about 500 completion tokens; requests with many explicit or structurally necessary constraints may exceed it rather than lose information.
- Return only the JSON object, without Markdown fences or prose outside JSON.

USER VISUAL REQUEST:
{{USER_VISUAL_REQUEST}}

Every top-level key must always be present and must strictly follow the field definitions below.

{
  "lighting": {
    "conditions": "type and quality of light",
    "direction": "where the light comes from; None for flat digital images",
    "shadows": "shadow description including the shading that models form and separates layers; None for flat digital images",
    "illumination_effect": "overall effect of the lighting"
  },
  "aesthetics": {
    "composition": "framing and compositional choices",
    "color_scheme": "dominant colors and palette",
    "mood_atmosphere": "emotional atmosphere in short phrases",
    "patterns": "notable repeating visual patterns; None if none"
  },
  "cinematography": {
    "framing": "shot type",
    "camera_angle": "angle such as Eye-level, Low angle, or High angle",
    "depth_of_field": "depth of field with its focal plane and falloff",
    "focus": "what is focused on AND what is left out of focus; natural focus wording",
    "lens_focal_length": "descriptive focal length",
    "optical_character": "real-lens and sensor behaviour, ONLY for photographic natural_image; otherwise the string none"
  },
  "style_medium": "visual medium, for example Photography, Digital illustration, or Screenshot",
  "artistic_style": "genre or approach",
  "artifact_type": "exactly one of: text_led_graphic | natural_image"
}"""


D_DELIVERY_PROMPT = r"""CURRENT SHARD TASK: D · DELIVERY AND TEXT
Generate only `context` and `text_and_signage_elements`. Read the complete user request, identify the image's use context, and build an accurate, complete, renderable visible-copy ledger without unnecessary expansion.

PURPOSE OF THIS SHARD
- `context`: concisely identifies the artifact or scene type, intended use, likely viewing situation, and—when explicitly supported—the audience and communication goal.
- `text_and_signage_elements`: is the closed whitelist of every glyph sequence intended to be visible. It records exact user literals and the minimum final copy required to make requested text-bearing sections complete, together with appearance, position, and role.

BOUNDARIES WITH OTHER SHARDS
- A owns subjects, objects, and their actions; do not turn a text carrier into a second full subject description.
- B owns the environment and overall spatial layout; describe only each text block's own position, alignment, order, and grouping here, without creating another scene layout.
- C owns composition, color, lighting, camera, and overall artistic style; provide only the typography, weight, relative size, color, and contrast necessary for the text itself.
- Do not restate the complete user request or turn non-text visual requirements into titles, slogans, logos, or explanatory copy.

NOTES
- Preserve every user-specified literal exactly, including language, spelling, capitalization, numerals, punctuation, separators, and line content. Do not translate, paraphrase, autocorrect, shorten, expand, or add filler inside an exact literal.
- Treat `text_and_signage_elements` as a closed visible-copy ledger: every listed `text` is final viewer-facing copy, and no unlisted letters, numerals, logos, decorative pseudo-copy, or metadata should appear elsewhere.
- Use `logo` only when the user explicitly requests an actual logo or brand mark. A stylized poster title, cover headline, or editorial heading remains `body_text`; never loosen glyph fidelity by relabeling ordinary copy as a logo.
- For a text-led artifact such as a poster, cover, infographic, calendar, table, map, diagram, editorial layout, or UI, resolve every semantically requested text section into final renderable copy. Never emit an orphan heading that promises an empty body, an unlabeled reserved text area, a placeholder, `TBD`, lorem ipsum, or alphanumeric noise.
- When the user specifies a section's meaning but not its wording, generate the smallest coherent final copy that fulfills it. Reuse supplied names, dates, times, places, and numbers before inferring anything new. For an explicitly fictional or art-directed mock artifact, concise fictional names and non-claim functional wording are allowed as design payload; keep them mutually consistent and do not imply real-world attribution.
- Write every `text` value in the same language and script as the user request, including copy you generate yourself. If the request is written in Chinese, all headings, labels, section titles, category names, and body copy you infer must also be Chinese; do not translate the user's wording into English and do not default to English headings such as "EDUCATION" or "PROFILE". Keep an English literal only when the user wrote it in English, or when the term is a real proper noun, brand, product, code, or unit that is conventionally written that way. This rule governs the viewer-facing `text` field only; `appearance`, `spatial`, and `context` stay in concise English.
- Do not complete a roster, contributor list, item list, destination list, or similar member-bearing section by repeating the artifact title, subtitle, section heading, or another non-member label as its member. When distinct members are required but unsupplied in a fictional mock artifact, create a small set of concise fictional member names instead.
- Do not invent brands, citations, statistics, certifications, contacts, URLs, addresses, promotional claims, prices, or consequential real-world facts. If a requested section would normally require unsupported specifics, complete it with qualitative source-safe wording, or reuse only supplied literals; do not leave the heading alone.
- Avoid duplicated information. If a title, subtitle, or existing block already supplies a requested semantic role such as time and venue, do not create a second conflicting value; either group the same exact literals into one logical block or omit the redundant heading.
- If an ordinary scene naturally contains text-bearing surfaces—for example storefront signs, transit displays, control panels, books, product labels, uniforms, room signs, or wayfinding—ground only a small number of visually important surfaces with concise, plausible, legible functional copy. Do not enumerate distant microtext or decorative packaging text.
- If the request neither specifies text nor contains any visually important text-bearing surface, return an empty `text_and_signage_elements` array. An empty array means the whole image is text-free; never use a sentence such as "no visible text" as a placeholder item.
- For standalone typography, logos, diagrams, posters, and other text-led artifacts, keep the literal, glyph style, hierarchy, placement, and communicative role tightly coupled in each item so the requested lettering remains legible instead of becoming ornamental pseudo-glyphs.
- When lettering is requested as experimental, distorted, directional, italic, compressed, or kinetic, preserve the standard internal skeleton of every character. Apply experimentation only through whole-word shear, width, weight, baseline direction, outline, shadow, or backing geometry; never cut apart, replace, fuse, or abstract the character's identity. Explicit legibility requirements take priority over deformation.
- Use one item per logical text block. A multiline `text` value may contain a heading and its completed supporting lines when they form one visual unit. Dense repeated structures may be grouped into renderable rows or columns instead of being exploded into many verbose objects.
- Give every text block one unique placement and a quiet, text-free local surround. Registration marks, borders, waveforms, speed lines, bars, and other decoration must remain purely geometric, with no tiny captions, codes, ticks, pseudo-labels, or repeated ledger copy embedded in them.
- TEXT LEDGER = THE ONLY SOURCE OF ON-CANVAS GLYPHS (CRITICAL for text_led_graphics): the renderer draws glyphs only where this ledger gives a concrete literal and fabricates garbled filler on any styled info-bearing surface left without one, so never drop or vaguely-placeholder requested or layout-implied content — enumerate EVERY visible text slot with its exact final value. (a) Data layouts (charts, tables, dashboards, timelines, map legends): every axis title/tick, legend, date, %/count/unit, code, cell, footnote, source — reuse the user's values verbatim, emit the shortest correct literal for any structural label the user did not word, never consolidate cells into a vague block; coverage beats brevity. (b) Repeated cards: fix ONE field schema and give every card the SAME complete labeled fields as literals; also enumerate auxiliary regions (trend-chart axis titles + ticks + each series value, totals/legend strip, header subtitle, footer source + update line). (c) Labels drawn ON a subject (map pins/place names, node & connector labels, legend swatches, callouts) hide in subject prose where the renderer cannot read them — each MUST ALSO appear here as its own short literal, spelled identically to its matching entry, drawn exactly once. (d) Mock/demo/fictional artifacts: author plausible design-payload values (dates, numbers, %, codes, short on-theme entries) as design content, not factual claims; always prefer a concrete value over an empty slot. SCOPE: for a pictorial scene, illustrated map, or artwork keep only the callouts actually requested and reserve "text-free" for pure non-semantic decoration; never add filler ticks or micro-labels to decorative surfaces.
- Before returning, audit every requested or structurally implied text region: it must either be represented by final literal copy in the ledger or intentionally absent with no empty text container requested. Remove duplicate literals, contradictory values, headings without content, and any prose that is not meant to be typeset.
- Keep `appearance`, `spatial`, and each item's `context` concise, executable, and non-redundant. Prioritize exact, complete copy over descriptive prose.
- For every field assigned to this shard, write specific content that supports the request and keeps its explicitly requested visual distinctions clearly perceptible.
- Do not add keys outside the template and do not omit required keys.
- Aim to stay within about 500 completion tokens. Requests with many explicit or structurally necessary constraints may exceed this target rather than lose information.
- Return only the JSON object, without Markdown fences or prose outside JSON.

USER VISUAL REQUEST:
{{USER_VISUAL_REQUEST}}

Lists may contain zero or more items of the shape shown. Both `context` and `text_and_signage_elements` must always be present; use an empty array only when neither requested nor naturally required visible text exists.

{
  "context": "scene context or use case",
  "text_and_signage_elements": [
    {
      "text": "final exact viewer-facing copy; preserve user-specified text verbatim and fully complete any necessary inferred block",
      "category": "physical_in_scene, ui_text, body_text, scene_sign, logo, or label",
      "appearance": "font, color, size, style",
      "spatial": "position in the image",
      "context": "purpose or meaning of the text"
    }
  ]
}"""


SHARD_KEYS = {
    "a_subjects": ["subjects", "subject_details"],
    "b_spatial": ["background_setting", "quadrant_scan", "resolution", "aspect_ratio"],
    "c_direction": ["lighting", "aesthetics", "cinematography", "style_medium", "artistic_style"],
    "d_delivery": ["context", "text_and_signage_elements"],
}
MERGE_ORDER = [
    "subjects",
    "subject_details",
    "background_setting",
    "lighting",
    "aesthetics",
    "cinematography",
    "style_medium",
    "artistic_style",
    "context",
    "text_and_signage_elements",
    "quadrant_scan",
    "comprehensive_t2i_caption",
    "resolution",
    "aspect_ratio",
]
REQUIRED_KEYS = {
    "subjects",
    "subject_details",
    "background_setting",
    "lighting",
    "aesthetics",
    "cinematography",
    "style_medium",
    "artistic_style",
    "context",
    "text_and_signage_elements",
    "quadrant_scan",
    "comprehensive_t2i_caption",
    "resolution",
    "aspect_ratio",
}
EMPTY_MARKERS = {"", "n/a", "none", "not applicable"}


def load_prompt_bundle() -> dict[str, str]:
    bundle = {
        "system": SYSTEM_PROMPT,
        "a_subjects": A_SUBJECTS_PROMPT,
        "b_spatial": B_SPATIAL_PROMPT,
        "c_direction": C_DIRECTION_PROMPT,
        "d_delivery": D_DELIVERY_PROMPT,
    }
    expected = {"system", *SHARD_KEYS}
    if set(bundle) != expected:
        raise RuntimeError(f"plaintext prompt keys changed: {sorted(bundle)}")
    for name in SHARD_KEYS:
        if bundle[name].count(USER_MARKER) != 1:
            raise RuntimeError(f"{name}: expected exactly one user-request marker")
    return bundle


PROMPTS = load_prompt_bundle()

ARTIFACT_TYPE_KEY = "artifact_type"
ARTIFACT_TEXT_LED = "text_led_graphic"
ARTIFACT_NATURAL = "natural_image"
ARTIFACT_TYPES = (ARTIFACT_TEXT_LED, ARTIFACT_NATURAL)
DEFAULT_ARTIFACT_TYPE = ARTIFACT_NATURAL

# text_led_graphic 时替换 c_direction 的 2D 平面中性值：
# 切断摄影先验（景深/投影/胶片颗粒/写实材质）对信息图的污染
FLAT_GRAPHIC_DIRECTION = {
    "lighting": {
        "light_source": "Flat even illumination inherent to a 2D digital artifact",
        "light_direction": "N/A",
        "shadows": "None",
        "lighting_effect": "Uniform legibility across the whole canvas with no cast shadows or photographic falloff",
    },
    "aesthetics": {
        "composition": "Clear reading order with aligned grid structure, consistent margins, and balanced whitespace between blocks",
        "color_scheme": "Limited flat palette with strong figure-ground contrast for legibility",
        "mood_atmosphere": "Clean, informative, professional",
        "visual_patterns": "Consistent iconography, aligned panels, and repeated typographic hierarchy",
    },
    "cinematography": {
        "framing": "Full-canvas flat view of the artifact",
        "camera_angle": "N/A",
        "depth_of_field": "Uniform focus",
        "focus": "Entire canvas uniformly legible",
        "lens_focal_length": "N/A",
    },
    "style_medium": "Flat 2D graphic design",
    "artistic_style": "Clean vector infographic with crisp edges and no photographic texture",
}


# text_led_graphic 覆盖时只中和"纯摄影先验"的键(光照/摄影机景深镜头)。
# aesthetics(主色调/构图/氛围/母题)与 style_medium/artistic_style(用户显式指定的
# 平面风格)保留模型产出，避免把用户要求的主色调与风格一并丢弃。
FLAT_GRAPHIC_PHOTO_KEYS = ("lighting", "cinematography")

# text_led_graphic 时需要清空的人物字段。a_subjects 的 prompt 规则会自行置空，
# merge 阶段再按 c_direction 的权威判定兜底一次（两者判定不一致时以 C 为准）。
PERSON_TEXT_FIELDS = (
    "clothing",
    "expression",
    "gender",
    "age",
    "skin_tone_and_texture",
    "facial_features",
)
PERSON_COUNT_FIELDS = ("number_of_arms", "number_of_legs", "number_of_hands", "number_of_fingers")


# 永久性错误：重试无意义，命中即快速失败（省掉 2/3 无效调用并尽快暴露问题）。
# 来源：2026-09-23 ds 模型被下架后，9/28 日志出现 8136 次同一个 403 model_offline，
# 全部走完 3 次重试，模型下架半个月无人发现。
PERMANENT_ERROR_PATTERNS = (
    "model_offline",
    "model_not_found",
    "does not exist or you do not have access",
    "无可用渠道",
    "已由",  # 「模型 X 在分组 Y 已由 Z 下架」
    "下架",
    "auth_failed",
    "invalid token",
    "invalid_api_key",
    "insufficient_quota",
)
# 这些 HTTP 码配合上面的关键字才算永久错误；403/401 单独出现也视为永久。
PERMANENT_HTTP_CODES = ("401", "403", "404")


def is_permanent_error(error: Exception) -> tuple[bool, str]:
    """判断该错误是否重试无意义。返回 (是否永久, 命中原因)。"""
    text = f"{type(error).__name__}: {error}".lower()
    for pat in PERMANENT_ERROR_PATTERNS:
        if pat.lower() in text:
            return True, pat
    match = re.search(r"http (\d{3})", text)
    if match and match.group(1) in PERMANENT_HTTP_CODES:
        return True, f"HTTP {match.group(1)}"
    return False, ""


class FallbackMonitor:
    """PE 兜底率滑窗监控：静默兜底曾让模型下架半个月无人发现，故超阈值主动告警。"""

    def __init__(
        self, window: int = 20, ratio_threshold: float = 0.5, streak_threshold: int = 3
    ) -> None:
        self.window = window
        self.ratio_threshold = ratio_threshold
        self.streak_threshold = streak_threshold
        self._recent: deque[bool] = deque(maxlen=window)  # True = 兜底
        self._streak = 0
        self._total = 0
        self._fallbacks = 0
        self._last_alert = 0.0

    def record(self, fell_back: bool, reason: str = "") -> None:
        self._total += 1
        self._recent.append(fell_back)
        if fell_back:
            self._fallbacks += 1
            self._streak += 1
        else:
            self._streak = 0
            return

        ratio = sum(self._recent) / len(self._recent)
        streak_hit = self._streak >= self.streak_threshold
        ratio_hit = len(self._recent) >= self.streak_threshold and ratio >= self.ratio_threshold
        if not (streak_hit or ratio_hit):
            return
        now = time.time()
        if now - self._last_alert < 60:  # 最多每分钟告警一次，避免刷屏
            return
        self._last_alert = now
        logger.critical(
            "T2I PE 兜底率告警：连续兜底=%d 次，最近 %d 次兜底率=%.0f%%（累计 %d/%d）"
            "，PE 实际未生效，图像将退化为原始 prompt 直出。最后原因=%s",
            self._streak,
            len(self._recent),
            ratio * 100,
            self._fallbacks,
            self._total,
            reason[:300] or "未知",
        )

    def snapshot(self) -> dict[str, Any]:
        return {
            "total": self._total,
            "fallbacks": self._fallbacks,
            "streak": self._streak,
            "window_ratio": (
                round(sum(self._recent) / len(self._recent), 3) if self._recent else 0.0
            ),
        }


FALLBACK_MONITOR = FallbackMonitor()


def _coerce_artifact_type(value: Any) -> str:
    """把模型输出的分类值归一化；非法值回落 natural_image(保持现状行为)。"""
    if isinstance(value, str):
        normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
        if normalized in ARTIFACT_TYPES:
            return normalized
    return DEFAULT_ARTIFACT_TYPE


SHARD_TEMPLATES = {shard: PROMPTS[shard] for shard in SHARD_KEYS}
EXPECTED_TEMPLATE_SHA256 = {
    shard: hashlib.sha256(template.encode("utf-8")).hexdigest()
    for shard, template in SHARD_TEMPLATES.items()
}


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def validate_embedded_contract() -> None:
    if set(SHARD_TEMPLATES) != set(SHARD_KEYS):
        raise RuntimeError("embedded split-3 shard set is incomplete")
    owned = [key for shard in SHARD_KEYS.values() for key in shard]
    expected_model_keys = [key for key in MERGE_ORDER if key != "comprehensive_t2i_caption"]
    if sorted(owned) != sorted(expected_model_keys) or len(owned) != len(set(owned)):
        raise RuntimeError("invalid split-3 field ownership")
    for shard, template in SHARD_TEMPLATES.items():
        if template.count(USER_MARKER) != 1:
            raise RuntimeError(f"{shard}: user marker count is not exactly one")
        actual = sha256_text(template)
        if actual != EXPECTED_TEMPLATE_SHA256[shard]:
            raise RuntimeError(f"{shard}: embedded template SHA-256 mismatch")


def extract_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", cleaned, flags=re.DOTALL)
    if fenced:
        cleaned = fenced.group(1).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end < start:
        raise ValueError("model response does not contain a JSON object")
    value = json.loads(cleaned[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("model response JSON must be an object")
    return value


def usage_value(usage: dict[str, Any], kind: str) -> int:
    names = {
        "input": ("input_tokens", "prompt_tokens"),
        "output": ("output_tokens", "completion_tokens"),
    }[kind]
    for name in names:
        value = usage.get(name)
        if isinstance(value, (int, float)):
            return int(value)
    return 0


def api_key_from_environment(name: str) -> str:
    if name:
        value = os.environ.get(name, "").strip()
        if not value:
            raise RuntimeError(f"environment variable {name!r} is not set")
        return value
    for candidate in ("PROMPT_UPSAMPLER_API_KEY",):
        value = os.environ.get(candidate, "").strip()
        if value:
            return value
    raise RuntimeError("set PROMPT_UPSAMPLER_API_KEY")


def chat_completion(
    *,
    api_key: str,
    base_url: str,
    model: str,
    reasoning_effort: str,
    max_tokens: int,
    service_tier: str,
    system_prompt: str,
    user_message: str,
    timeout: int,
) -> tuple[dict[str, Any], dict[str, Any], str, str]:
    url = base_url.rstrip("/") + "/chat/completions"
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "max_completion_tokens": max_tokens,
        "response_format": {"type": "json_object"},
        "reasoning_effort": reasoning_effort,
    }
    if service_tier != "default":
        body["service_tier"] = service_tier
    request = Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")[:2000]
        raise RuntimeError(f"HTTP {error.code}: {detail}") from error
    except URLError as error:
        raise RuntimeError(f"request failed: {error}") from error
    choices = payload.get("choices") or []
    if not choices:
        raise ValueError(f"response has no choices: {str(payload)[:1000]}")
    content = (choices[0].get("message") or {}).get("content") or ""
    try:
        parsed = extract_json_object(content)
    except ValueError as error:
        raise ValueError(f"invalid model response: {error}; response: {content[:4000]}") from error
    usage = payload.get("usage") or {}
    finish_reason = str(choices[0].get("finish_reason") or "")
    return parsed, usage, finish_reason, content


# ===== 确定性 caption helper（内联自原 t2i_pe_split_fix3.py）=====
def _clean(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    text = re.sub(r"\s+", " ", value).strip()
    return "" if text.lower() in EMPTY_MARKERS else text


def _normalized(value: str) -> str:
    return re.sub(r"[^\w\u3400-\u9fff]+", "", value).lower()


def _unique(values) -> list[str]:
    kept, normalized = [], []
    for value in values:
        text = _clean(value)
        marker = _normalized(text)
        if not marker or any(marker == prior or marker in prior for prior in normalized):
            continue
        kept.append(text)
        normalized.append(marker)
    return kept


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: max(1, limit - 1)].rstrip(" ,;:.，；：。") + "…"


def _bounded(values, total_limit: int) -> list[str]:
    content = _unique(values)
    if not content:
        return []
    per_item = max(8, (total_limit - 2 * (len(content) - 1)) // len(content))
    return [_truncate(value, per_item) for value in content]


def _clause(label: str, values, limit: int) -> str:
    content = _bounded(values, limit)
    return f"{label}: {'; '.join(content)}." if content else ""


def _subject_summaries(subjects: Any) -> list[str]:
    if not isinstance(subjects, list):
        return []
    return [
        _clean(subject.get("description"))
        for subject in subjects
        if isinstance(subject, dict) and _clean(subject.get("description"))
    ]


def _exact_visible_text_summaries(elements: Any) -> list[str]:
    if not isinstance(elements, list):
        return []
    summaries, seen = [], set()
    for element in elements:
        if not isinstance(element, dict) or not isinstance(element.get("text"), str):
            continue
        literal = element["text"].strip()
        marker = _normalized(literal)
        if not marker or marker in seen:
            continue
        seen.add(marker)
        summaries.append(json.dumps(literal, ensure_ascii=False))
    return summaries


def build_comprehensive_caption(data: dict[str, Any]) -> str:
    aesthetics = data.get("aesthetics") if isinstance(data.get("aesthetics"), dict) else {}
    lighting = data.get("lighting") if isinstance(data.get("lighting"), dict) else {}
    camera = data.get("cinematography") if isinstance(data.get("cinematography"), dict) else {}
    clauses = [
        _clause("Scene", [data.get("background_setting")], 180),
        _clause("Subjects", _subject_summaries(data.get("subjects")), 280),
        _clause("Composition", [aesthetics.get("composition")], 100),
        _clause("Lighting", [lighting.get("conditions"), lighting.get("direction")], 80),
        _clause(
            "Camera",
            [
                camera.get("framing"),
                camera.get("camera_angle"),
                camera.get("depth_of_field"),
                camera.get("focus"),
            ],
            200,
        ),
        _clause("Style", [data.get("style_medium"), data.get("artistic_style")], 90),
        _clause("Purpose", [data.get("context")], 80),
    ]
    caption = " ".join(clause for clause in clauses if clause)
    if not caption:
        raise ValueError("cannot derive caption from empty shard outputs")
    return caption


def build_text_ledger_caption(data: dict[str, Any]) -> str:
    scene = build_comprehensive_caption(data)
    literals = _exact_visible_text_summaries(data.get("text_and_signage_elements"))
    if not literals:
        return f"{scene} The finished image contains no visible glyphs."
    return (
        f"{scene} Visible copy whitelist—render each quoted string exactly once "
        f"and add no other glyphs: {'; '.join(literals)}."
    )


def build_comprehensive_t2i_caption(data: dict[str, Any]) -> str:
    return build_text_ledger_caption(data)


def selected_canvas(data: dict[str, Any]) -> tuple[tuple[int, int], str]:
    resolution = data.get("resolution")
    if not isinstance(resolution, dict):
        raise ValueError("auto canvas resolution must be an object")

    def dimension(name: str) -> int:
        value = resolution.get(name)
        if isinstance(value, bool):
            raise ValueError(f"auto canvas resolution.{name} must be an integer")
        if isinstance(value, int):
            parsed = value
        elif isinstance(value, str) and value.strip().isdigit():
            parsed = int(value.strip())
        else:
            raise ValueError(f"auto canvas resolution.{name} must be an integer")
        if parsed < 1:
            raise ValueError(f"auto canvas resolution.{name} must be positive")
        return parsed

    ratio = data.get("aspect_ratio")
    if not isinstance(ratio, str) or ratio.strip() not in AUTO_CANVAS_PRESETS:
        raise ValueError("auto canvas aspect_ratio is not a supported preset")
    ratio = ratio.strip()
    selected_wh = (dimension("W"), dimension("H"))
    if selected_wh != AUTO_CANVAS_PRESETS[ratio]:
        raise ValueError("auto canvas resolution does not match aspect_ratio preset")
    return selected_wh, ratio


def merge_outputs(
    parts: dict[str, dict[str, Any]],
    output_width: int | None,
    output_height: int | None,
    aspect_ratio: str | None,
    artifact_type: str = DEFAULT_ARTIFACT_TYPE,
) -> dict[str, Any]:
    """合并各分片输出。

    artifact_type=text_led_graphic 时丢弃 c_direction 的输出，改用平面图形中性值：
    信息图/海报/图表等 2D 文字主导产物不需要（且会被）摄影光影、景深、
    写实材质等引导劣化，这里从源头切断该污染。
    """
    model_values: dict[str, Any] = {}
    flat_graphic = artifact_type == ARTIFACT_TEXT_LED
    for shard, expected_keys in SHARD_KEYS.items():
        output = parts[shard]["output"]
        if list(output) != expected_keys:
            raise ValueError(f"{shard} keys {list(output)} != {expected_keys}")
        if flat_graphic and shard == "a_subjects":
            # 以 c_direction 的权威判定兜底：A 若判成 natural_image 而未自行置空，
            # 这里按权威结果统一清空人物字段，避免平面图里混入人体描述。
            cleaned = copy.deepcopy(output)
            subjects = cleaned.get("subjects")
            if isinstance(subjects, list):
                for sub in subjects:
                    if not isinstance(sub, dict):
                        continue
                    for key in PERSON_TEXT_FIELDS:
                        if key in sub:
                            sub[key] = ""
                    for key in PERSON_COUNT_FIELDS:
                        if key in sub:
                            sub[key] = 0
            model_values.update(cleaned)
            continue
        if flat_graphic and shard == "c_direction":
            # 只中和纯摄影先验(光照/摄影机景深镜头)，保留模型产出的 aesthetics
            # (主色调/构图/氛围/母题)与 style_medium/artistic_style(用户显式指定的
            # 平面风格)。键集不变，契约不破。
            merged_c = dict(output)
            for key in FLAT_GRAPHIC_PHOTO_KEYS:
                merged_c[key] = copy.deepcopy(FLAT_GRAPHIC_DIRECTION[key])
            model_values.update(merged_c)
            continue
        model_values.update(output)
    caption = build_comprehensive_t2i_caption(model_values)
    merged = {}
    for key in MERGE_ORDER:
        merged[key] = caption if key == "comprehensive_t2i_caption" else model_values[key]
    explicit_canvas = (output_width, output_height, aspect_ratio)
    if any(value is not None for value in explicit_canvas):
        if not all(value is not None for value in explicit_canvas):
            raise ValueError("explicit canvas requires width, height, and aspect ratio")
        merged["resolution"] = {"H": output_height, "W": output_width}
        merged["aspect_ratio"] = aspect_ratio
    else:
        (selected_width, selected_height), selected_ratio = selected_canvas(merged)
        merged["resolution"] = {"H": selected_height, "W": selected_width}
        merged["aspect_ratio"] = selected_ratio
    if list(merged) != MERGE_ORDER or set(merged) != REQUIRED_KEYS:
        raise ValueError("merged split-3 output violates the canonical 14-key contract")
    return merged


def run_shard(
    *,
    shard: str,
    instruction: str,
    api_key: str,
    base_url: str,
    model: str,
    reasoning_effort: str,
    max_tokens: int,
    service_tier: str = DEFAULT_SERVICE_TIER,
    timeout: int,
    retries: int,
    require_canvas_selection: bool = False,
    system_prompt: str = SYSTEM_PROMPT,
    template: str | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    template = SHARD_TEMPLATES[shard] if template is None else template
    if template.count(USER_MARKER) != 1:
        raise ValueError(f"{shard}: expected exactly one {USER_MARKER} marker")
    user_message = template.replace(USER_MARKER, instruction)
    if shard == "b_spatial" and require_canvas_selection:
        anchor = "CURRENT SHARD TASK: B · SPATIAL"
        if anchor not in user_message:
            raise RuntimeError("b_spatial auto-canvas anchor missing; template drifted")
        user_message = user_message.replace(anchor, f"{AUTO_CANVAS_GUIDANCE}\n\n{anchor}", 1)
    errors = []
    for attempt in range(1, retries + 1):
        try:
            output, usage, finish_reason, raw_response = chat_completion(
                api_key=api_key,
                base_url=base_url,
                model=model,
                reasoning_effort=reasoning_effort,
                max_tokens=max_tokens,
                service_tier=service_tier,
                system_prompt=system_prompt,
                user_message=user_message,
                timeout=timeout,
            )
            artifact_type = None
            if (
                shard in ("a_subjects", "c_direction")
                and isinstance(output, dict)
                and ARTIFACT_TYPE_KEY in output
            ):
                # artifact_type 是控制字段，不属于 14-key 契约：取出后再做严格校验
                output = dict(output)
                artifact_type = _coerce_artifact_type(output.pop(ARTIFACT_TYPE_KEY))
            if list(output) != SHARD_KEYS[shard]:
                raise ValueError(f"{shard} keys {list(output)} != {SHARD_KEYS[shard]}")
            canvas_fallback = False
            canvas_fallback_reason = None
            if shard == "b_spatial" and require_canvas_selection:
                try:
                    selected_canvas(output)
                except ValueError as error:
                    if attempt < retries:
                        raise
                    logger.error(
                        "T2I PE 分片画布无效，已耗尽重试并回退默认画布："
                        "分片=%s，尝试=%d/%d，回退=%dx%d，错误=%s: %s",
                        shard,
                        attempt,
                        retries,
                        DEFAULT_AUTO_CANVAS_WH[0],
                        DEFAULT_AUTO_CANVAS_WH[1],
                        type(error).__name__,
                        error,
                    )
                    output = dict(output)
                    output["resolution"] = {
                        "H": DEFAULT_AUTO_CANVAS_WH[1],
                        "W": DEFAULT_AUTO_CANVAS_WH[0],
                    }
                    output["aspect_ratio"] = DEFAULT_AUTO_CANVAS_RATIO
                    canvas_fallback = True
                    canvas_fallback_reason = str(error)
            return {
                "status": "ok",
                "shard": shard,
                "output": output,
                "template_sha256": sha256_text(template),
                "system_prompt": system_prompt,
                "user_message": user_message,
                "raw_response": raw_response,
                "elapsed_seconds": round(time.perf_counter() - started, 4),
                "attempt": attempt,
                "usage": usage,
                "input_tokens": usage_value(usage, "input"),
                "output_tokens": usage_value(usage, "output"),
                "finish_reason": finish_reason,
                "canvas_fallback": canvas_fallback,
                "canvas_fallback_reason": canvas_fallback_reason,
                "artifact_type": artifact_type,
            }
        except Exception as error:  # noqa: BLE001
            errors.append(f"{type(error).__name__}: {error}")
            permanent, hit = is_permanent_error(error)
            will_retry = attempt < retries and not permanent
            log = logger.warning if will_retry else logger.error
            log(
                "T2I PE 分片失败：分片=%s，尝试=%d/%d，后续=%s，错误=%s: %s",
                shard,
                attempt,
                retries,
                "重试"
                if will_retry
                else (
                    f"永久性错误({hit})，跳过剩余重试并整体 PE 兜底"
                    if permanent
                    else "整体 PE 兜底"
                ),
                type(error).__name__,
                error,
            )
            if permanent:
                break
            if will_retry:
                time.sleep(min(2**attempt, 8))
    raise RuntimeError(f"{shard} failed after {retries} attempts: {errors[-1]}")


def enhance_instruction(
    instruction: str,
    settings: argparse.Namespace,
    *,
    api_key: str | None = None,
    system_prompt: str = SYSTEM_PROMPT,
    templates: dict[str, str] | None = None,
) -> dict[str, Any]:
    started = time.perf_counter()
    api_key = api_key or api_key_from_environment(settings.api_key_env)
    templates = SHARD_TEMPLATES if templates is None else templates
    if set(templates) != set(SHARD_KEYS):
        raise ValueError("all four shard templates are required")
    for shard, template in templates.items():
        if template.count(USER_MARKER) != 1:
            raise ValueError(f"{shard}: expected exactly one {USER_MARKER} marker")
    parts = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {
            pool.submit(
                run_shard,
                shard=shard,
                instruction=instruction,
                api_key=api_key,
                base_url=settings.base_url,
                model=settings.model,
                reasoning_effort=settings.reasoning_effort,
                max_tokens=settings.max_tokens,
                service_tier=settings.service_tier,
                timeout=settings.timeout,
                retries=settings.retries,
                require_canvas_selection=settings.output_width is None,
                system_prompt=system_prompt,
                template=templates[shard],
            ): shard
            for shard in SHARD_KEYS
        }
        for future in as_completed(futures):
            shard = futures[future]
            parts[shard] = future.result()
    # 权威判定取 c_direction（它决定是否替换摄影化指导）；a_subjects 的同名字段
    # 只用于该分片自身置空人物字段，不参与降级决策。
    artifact_type = _coerce_artifact_type(parts["c_direction"].get("artifact_type"))
    a_type = _coerce_artifact_type(parts["a_subjects"].get("artifact_type"))
    if a_type != artifact_type:
        logger.info(
            "T2I PE 分片判定不一致：a_subjects=%s，c_direction=%s（以 c_direction 为准）",
            a_type,
            artifact_type,
        )
    if artifact_type == ARTIFACT_TEXT_LED:
        logger.info(
            "T2I PE 产物类型=文字主导平面图(%s)，已丢弃 c_direction 摄影化指导并替换为 2D 平面中性值",
            artifact_type,
        )
    prompt = merge_outputs(
        parts,
        settings.output_width,
        settings.output_height,
        settings.aspect_ratio,
        artifact_type=artifact_type,
    )
    return {
        "status": "ok",
        "json_valid": True,
        "version": VERSION,
        "arm": ARM,
        "user_prompt": instruction,
        "prompt_sha256": sha256_text(instruction),
        "prompt": prompt,
        "prompt_text": json.dumps(prompt, ensure_ascii=False, separators=(",", ":")),
        "model": settings.model,
        "base_url": settings.base_url,
        "reasoning_effort": settings.reasoning_effort,
        "service_tier": settings.service_tier,
        "system_prompt_sha256": sha256_text(system_prompt),
        "template_sha256": {name: sha256_text(value) for name, value in templates.items()},
        "elapsed_seconds": round(time.perf_counter() - started, 4),
        "shard_elapsed_seconds": {name: parts[name]["elapsed_seconds"] for name in SHARD_KEYS},
        "shard_attempts": {name: parts[name]["attempt"] for name in SHARD_KEYS},
        "artifact_type": artifact_type,
        "c_direction_overridden": artifact_type == ARTIFACT_TEXT_LED,
        "canvas_fallback": parts["b_spatial"].get("canvas_fallback", False),
        "canvas_fallback_reason": parts["b_spatial"].get("canvas_fallback_reason"),
        "input_tokens": sum(parts[name]["input_tokens"] for name in SHARD_KEYS),
        "output_tokens": sum(parts[name]["output_tokens"] for name in SHARD_KEYS),
        "shards": parts,
    }
