from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union


@dataclass
class DVText:
    value: str


@dataclass
class DVQuantity:
    magnitude: float
    units: str


@dataclass
class DVCodedText:
    value: str
    code_string: Optional[str] = None
    terminology_id: Optional[str] = None  # e.g., 'local', 'SNOMED-CT', 'ICD-10'


@dataclass
class FlattenedValue:
    path: str
    archetype_node_id: str
    name: str
    value: Any
    value_type: str


@dataclass
class Element:
    archetype_node_id: str
    name: str
    value: Any

    @staticmethod
    def from_dict(obj: Dict[str, Any]) -> Element:
        return Element(
            archetype_node_id=_archetype_node_id(obj),
            name=_text_value(obj.get('name', {})),
            value=_parse_value(obj.get('value', {})),
        )


@dataclass
class ItemTree:
    archetype_node_id: str
    name: str
    items: List[Union[Element, 'ItemTree']] = field(default_factory=list)

    @staticmethod
    def from_dict(obj: Dict[str, Any]) -> ItemTree:
        items = obj.get('items', [])
        parsed_items: List[Union[Element, ItemTree]] = []

        if isinstance(items, dict):
            items = [items]

        for item in items:
            if not isinstance(item, dict):
                continue
            xsi_type = _object_type(item)
            if xsi_type in {'ITEM_TREE', 'CLUSTER'}:
                parsed_items.append(ItemTree.from_dict(item))
            elif xsi_type == 'ELEMENT':
                parsed_items.append(Element.from_dict(item))
            else:
                parsed_items.append(Element.from_dict(item))

        return ItemTree(
            archetype_node_id=_archetype_node_id(obj),
            name=_text_value(obj.get('name', {})),
            items=parsed_items,
        )


@dataclass
class PointEvent:
    time: Optional[str]
    data: Optional[ItemTree]
    state: Optional[ItemTree]

    @staticmethod
    def from_dict(obj: Dict[str, Any]) -> PointEvent:
        return PointEvent(
            time=obj.get('time', {}).get('value') if isinstance(obj.get('time'), dict) else None,
            data=ItemTree.from_dict(obj.get('data', {})) if isinstance(obj.get('data'), dict) else None,
            state=ItemTree.from_dict(obj.get('state', {})) if isinstance(obj.get('state'), dict) else None,
        )


@dataclass
class History:
    origin: Optional[str]
    events: Optional[PointEvent]

    @staticmethod
    def from_dict(obj: Dict[str, Any]) -> History:
        events = obj.get('events')
        return History(
            origin=obj.get('origin', {}).get('value') if isinstance(obj.get('origin'), dict) else None,
            events=PointEvent.from_dict(events) if isinstance(events, dict) else None,
        )


@dataclass
class ContentItem:
    xsi_type: str
    archetype_node_id: str
    name: str
    data: Optional[History]
    context: Optional[Dict[str, Any]]
    protocol: Optional[ItemTree]
    description: Optional[ItemTree] = None
    items: List[ContentItem] = field(default_factory=list)

    @staticmethod
    def from_dict(obj: Dict[str, Any]) -> ContentItem:
        xsi_type = _object_type(obj)
        content_items: List[ContentItem] = []

        for field_name in ['items', 'content', 'activities']:
            field_value = obj.get(field_name)
            if isinstance(field_value, list):
                for entry in field_value:
                    if isinstance(entry, dict):
                        content_items.append(ContentItem.from_dict(entry))
            elif isinstance(field_value, dict):
                content_items.append(ContentItem.from_dict(field_value))

        data = None
        if isinstance(obj.get('data'), dict):
            data = History.from_dict(obj['data'])

        protocol = None
        if isinstance(obj.get('protocol'), dict):
            protocol = ItemTree.from_dict(obj['protocol'])

        description = None
        if isinstance(obj.get('description'), dict):
            description = ItemTree.from_dict(obj['description'])

        archetype_node_id = _archetype_node_id(obj)
        if xsi_type == 'SECTION':
            return Section(
                xsi_type=xsi_type,
                archetype_node_id=archetype_node_id,
                name=_text_value(obj.get('name', {})),
                data=data,
                context=obj.get('context'),
                protocol=protocol,
                description=description,
                items=content_items,
            )

        return ContentItem(
            xsi_type=xsi_type,
            archetype_node_id=archetype_node_id,
            name=_text_value(obj.get('name', {})),
            data=data,
            context=obj.get('context'),
            protocol=protocol,
            description=description,
            items=content_items,
        )


@dataclass
class Section(ContentItem):
    pass


@dataclass
class CompositionData:
    content: List[ContentItem]

    @staticmethod
    def from_dict(obj: Dict[str, Any]) -> CompositionData:
        content: List[ContentItem] = []
        for item in obj.get('content', []):
            if isinstance(item, dict):
                content.append(ContentItem.from_dict(item))
        return CompositionData(content=content)


@dataclass
class Composition:
    data: CompositionData
    context: Optional[Dict[str, Any]] = None
    uid: Optional[str] = None
    archetype_node_id: Optional[str] = None
    template_id: Optional[str] = None

    @staticmethod
    def from_dict(obj: Dict[str, Any]) -> Composition:
        data_obj = obj.get('data')
        if data_obj is None and isinstance(obj.get('version'), dict):
            data_obj = obj['version'].get('data')
        if data_obj is None and _object_type(obj) == 'COMPOSITION':
            data_obj = obj

        composition_context = None
        if isinstance(data_obj, dict):
            composition_context = data_obj.get('context')

        uid = None
        version = obj.get('version')
        if isinstance(version, dict):
            uid_obj = version.get('uid')
            if isinstance(uid_obj, dict):
                uid = uid_obj.get('value')
        if uid is None and isinstance(data_obj, dict):
            uid_obj = data_obj.get('uid')
            if isinstance(uid_obj, dict):
                uid = uid_obj.get('value')
            elif isinstance(uid_obj, str):
                uid = uid_obj

        archetype_node_id = _archetype_node_id(data_obj) if isinstance(data_obj, dict) else None
        template_id = None
        if isinstance(data_obj, dict) and isinstance(data_obj.get('archetype_details'), dict):
            template_id = data_obj['archetype_details'].get('template_id', {}).get('value')

        return Composition(
            data=CompositionData.from_dict(data_obj or {}),
            context=composition_context,
            uid=uid,
            archetype_node_id=archetype_node_id,
            template_id=template_id,
        )


def flatten_item_tree(item_tree: ItemTree, base_path: str = '') -> List[FlattenedValue]:
    values: List[FlattenedValue] = []

    for item in item_tree.items:
        node_id = item.archetype_node_id or 'unknown'
        item_path = f'{base_path}/items[{node_id}]'

        if isinstance(item, Element):
            values.append(
                FlattenedValue(
                    path=item_path,
                    archetype_node_id=item.archetype_node_id,
                    name=item.name,
                    value=item.value,
                    value_type=_value_type(item.value),
                )
            )
        elif isinstance(item, ItemTree):
            values.extend(flatten_item_tree(item, item_path))

    return values


def _text_value(obj: Any) -> str:
    if isinstance(obj, dict):
        return _repair_text(obj.get('value', ''))
    if isinstance(obj, str):
        return _repair_text(obj)
    return ''


def _repair_text(value: Any) -> Any:
    if not isinstance(value, str):
        return value

    if 'Ã' in value or 'Â' in value:
        try:
            return value.encode('latin-1').decode('utf-8')
        except UnicodeError:
            return value
    return value


def _value_type(value: Any) -> str:
    if isinstance(value, DVQuantity):
        return 'DV_QUANTITY'
    if isinstance(value, DVCodedText):
        return 'DV_CODED_TEXT'
    if isinstance(value, DVText):
        return 'DV_TEXT'
    return type(value).__name__


def _parse_value(obj: Any) -> Any:
    if not isinstance(obj, dict):
        return _repair_text(obj)

    xsi_type = _object_type(obj)
    if xsi_type == 'DV_TEXT':
        return DVText(value=_repair_text(obj.get('value', '')))
    if xsi_type == 'DV_QUANTITY':
        magnitude = obj.get('magnitude')
        if magnitude is not None:
            try:
                magnitude = float(magnitude)
            except (TypeError, ValueError):
                pass
        return DVQuantity(magnitude=magnitude, units=_repair_text(obj.get('units', '')))
    if xsi_type == 'DV_CODED_TEXT':
        defining_code = obj.get('defining_code', {})
        return DVCodedText(
            value=_repair_text(obj.get('value', '')),
            code_string=defining_code.get('code_string'),
            terminology_id=defining_code.get('terminology_id', {}).get('value')
        )
    if xsi_type == 'DV_IDENTIFIER':
        return _repair_text(obj.get('id', ''))
    if xsi_type == 'DV_BOOLEAN':
        return bool(obj.get('value'))
    if xsi_type == 'DV_COUNT':
        return obj.get('magnitude')
    if xsi_type in {'DV_DATE_TIME', 'DV_DATE', 'DV_TIME', 'DV_DURATION'}:
        return _repair_text(obj.get('value', ''))

    return _repair_text(obj.get('value')) if 'value' in obj else obj


def _object_type(obj: Dict[str, Any]) -> str:
    return obj.get('@xsi:type') or obj.get('_type') or ''


def _archetype_node_id(obj: Dict[str, Any]) -> str:
    node_id = obj.get('@archetype_node_id') or obj.get('archetype_node_id')
    if node_id:
        return node_id

    archetype_details = obj.get('archetype_details')
    if isinstance(archetype_details, dict):
        archetype_id = archetype_details.get('archetype_id')
        if isinstance(archetype_id, dict):
            return archetype_id.get('value', '')
    return ''
