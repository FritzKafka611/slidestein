"""SlotRole enum — semantic roles for editable template slots (M5.2).

Kept separate from the domain-level SlideFunction / CommunicationJob taxonomy:
those describe the slide's overall purpose; SlotRole describes the semantic
function of a single editable shape within that slide.
"""

from __future__ import annotations

from enum import Enum


class SlotRole(str, Enum):
    TITLE = "title"
    SUBTITLE = "subtitle"
    SECTION_LABEL = "section_label"
    BODY_TEXT = "body_text"
    BULLET_LIST = "bullet_list"
    LABEL = "label"
    METRIC = "metric"
    METRIC_LABEL = "metric_label"
    COLUMN_HEADER = "column_header"
    ROW_HEADER = "row_header"
    TABLE_CELL = "table_cell"
    TIMELINE_LABEL = "timeline_label"
    TIMELINE_CONTENT = "timeline_content"
    MILESTONE = "milestone"
    PROCESS_STEP = "process_step"
    HIERARCHY_NODE = "hierarchy_node"
    WORKSTREAM_LABEL = "workstream_label"
    CALLOUT = "callout"
    FOOTNOTE = "footnote"
    SOURCE = "source"
    OTHER_TEXT = "other_text"
