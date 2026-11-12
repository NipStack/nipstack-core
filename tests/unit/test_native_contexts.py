import json
from dataclasses import FrozenInstanceError, replace

import pytest

from nipstack_core.parsers.native.compiler import compile_native
from nipstack_core.parsers.native.model import NativeError, NativeLimits
from nipstack_core.parsers.native.runtime import parse_native

TEMPLATE = """@record
parent {{ id }}
  owner {{ owner }}
@record children
  child {{ child }}
    value {{ value | required }}
@end
@section details
  details {{ label }}
    note {{ note | phrase | optional }}
@end
@record others
  other {{ other }}
@end
@end
"""


def compile_text(source=TEMPLATE, **limits):
    return compile_native(source.encode(), limits=replace(NativeLimits(), **limits))


def test_parent_and_child_order_duplicates_and_scope_isolation():
    result = parse_native(
        compile_text(),
        "parent A\n  child X\n    value 1\n  child X\n    value 1\n"
        "  owner one\n  other Y\nparent A\n  owner two\nparent B",
    )
    assert result == (
        {
            "id": "A",
            "owner": "one",
            "children": ({"child": "X", "value": "1"}, {"child": "X", "value": "1"}),
            "others": ({"other": "Y"},),
        },
        {"id": "A", "owner": "two", "children": (), "others": ()},
        {"id": "B", "children": (), "others": ()},
    )
    assert all("id" not in child for child in result[0]["children"])


@pytest.mark.parametrize("closing", ["", "\nparent B", "\noutside\n  child hidden\n    value x"])
def test_eof_parent_or_foreign_root_closes_descendants(closing):
    result = parse_native(compile_text(), "parent A\n  child X\n    value 1" + closing)
    assert result[0]["children"] == ({"child": "X", "value": "1"},)
    if "parent B" in closing:
        assert result[1]["children"] == ()
    else:
        assert len(result) == 1


def test_foreign_subtrees_cannot_populate_parent_or_child_fields():
    result = parse_native(
        compile_text(),
        "parent A\n  foreign subtree\n    owner leaked\n    child hidden\n"
        "      value hidden\n  child X\n    foreign nested\n"
        "      value hidden\n    value real\n  owner visible",
    )
    assert result == (
        {
            "id": "A",
            "owner": "visible",
            "children": ({"child": "X", "value": "real"},),
            "others": (),
        },
    )


def test_unselected_section_child_subtree_is_not_reclassified():
    source = """@record
parent {{ id }}
  value {{ value }}
@section details
  details {{ label | regex="selected" }}
    value {{ nested }}
@end
@end"""
    assert parse_native(
        compile_text(source), "parent A\n  details excluded\n    value hidden\n  value visible"
    ) == ({"id": "A", "value": "visible"},)


def test_absent_child_collections_and_sections_are_distinct():
    assert parse_native(compile_text(), "parent A") == ({"id": "A", "children": (), "others": ()},)
    assert parse_native(compile_text(), "foreign") == ()


def test_child_section_occurs_at_most_once_per_parent_and_is_frozen():
    result = parse_native(compile_text(), "parent A\n  details x\n    note \nparent B\n  details y")
    assert result[0]["details"] == {"label": "x", "note": ""}
    assert result[1]["details"] == {"label": "y"}
    with pytest.raises(TypeError):
        result[0]["details"]["label"] = "changed"
    with pytest.raises(NativeError) as caught:
        parse_native(compile_text(), "parent A\n  details x\n  owner z\n  details x")
    assert caught.value.code == "DUPLICATE_SECTION"


@pytest.mark.parametrize("closing", ["", "\nparent B", "\n  other Y", "\nforeign"])
def test_child_required_fields_checked_at_every_closure(closing):
    with pytest.raises(NativeError) as caught:
        parse_native(compile_text(), "parent A\n  child X" + closing)
    assert caught.value.code == "MISSING_REQUIRED"


def test_required_and_duplicate_state_is_local_to_each_occurrence():
    with pytest.raises(NativeError) as caught:
        parse_native(compile_text(), "parent A\n  child X\n    value 1\n  child Y\nparent B")
    assert caught.value.code == "MISSING_REQUIRED"
    with pytest.raises(NativeError) as caught:
        parse_native(compile_text(), "parent A\n  child X\n    value 1\n    value 1")
    assert caught.value.code == "DUPLICATE_CAPTURE"


def test_blank_lines_do_not_close_a_child():
    assert parse_native(compile_text(), "parent A\n  child X\n\n \t\n    value 1")[0][
        "children"
    ] == ({"child": "X", "value": "1"},)


@pytest.mark.parametrize("visual", ["", "  ", "\t", " \t"])
def test_directive_indentation_is_visual_and_does_not_dedent_patterns(visual):
    source = "\n".join(
        visual + line if line.startswith("@") else line for line in TEMPLATE.splitlines()
    )
    assert parse_native(compile_text(source), "parent A\n  child X\n    value 1")[0][
        "children"
    ] == ({"child": "X", "value": "1"},)


def test_literal_tab_hierarchy_is_not_expanded():
    source = "@record\nroot {{ id }}\n@record items\n\titem {{ item }}\n\t\tvalue {{ value }}\n@end\n@end"
    assert parse_native(compile_text(source), "root A\n\titem B\n\t\tvalue C") == (
        {"id": "A", "items": ({"item": "B", "value": "C"},)},
    )
    with pytest.raises(NativeError) as caught:
        parse_native(compile_text(source), "root A\n  item B")
    assert caught.value.code == "INVALID_INDENTATION"


@pytest.mark.parametrize("line", [" child X", "   child X", "\tchild X"])
def test_recognized_wrong_member_indentation_fails(line):
    with pytest.raises(NativeError) as caught:
        parse_native(compile_text(), "parent A\n" + line)
    assert caught.value.code == "INVALID_INDENTATION"


def test_parent_field_and_child_header_have_no_priority():
    source = (
        "@record\nroot {{ id }}\n  item {{ scalar }}\n@record items\n  item {{ child }}\n@end\n@end"
    )
    with pytest.raises(NativeError) as caught:
        parse_native(compile_text(source), "root A\n  item B")
    assert caught.value.code == "AMBIGUOUS_MATCH"


@pytest.mark.parametrize(
    "source",
    [
        "@record named\nroot\n@end",
        "@record\nroot\n@record\n  child\n@end\n@end",
        "@record\nroot\n@record invalid-name\n  child\n@end\n@end",
        "@record\nroot\n@record children\nchild\n@end\n@end",
        "@record\nroot\n@record children\n  child\n@record grandchildren\n    grandchild\n@end\n@end\n@end",
        "@record\nroot {{ items }}\n@record items\n  child\n@end\n@end",
        "@record\nroot\n  value {{ items }}\n@record items\n  child\n@end\n@end",
        "@record\nroot\n@record items\n  child\n@end\n@section items\n  details\n@end\n@end",
        "@record\nroot\n@record items\n  child\n@end",
        "@record\nroot\n@record items\n@end\n@end",
        "@record\nroot\n@record items\n  child {{ id | optional }}\n@end\n@end",
        "@record\nroot\n@record items\n  child {{ id | required }}\n@end\n@end",
        "@record\nroot\n  field {{ value }}\n@record items\n\tchild\n@end\n@end",
    ],
)
def test_invalid_hierarchies_fail_before_runtime(source):
    with pytest.raises(NativeError):
        compile_text(source)


def test_section_root_and_child_record_are_independent_cardinalities():
    source = "@section\nroot\n@record items\n  item {{ id }}\n@end\n@end"
    assert parse_native(compile_text(source), "root\n  item A\n  item A") == {
        "items": ({"id": "A"}, {"id": "A"})
    }
    with pytest.raises(NativeError) as caught:
        parse_native(compile_text(source), "root\nroot")
    assert caught.value.code == "DUPLICATE_SECTION"


def test_selected_block_limit_is_global_not_per_parent():
    assert len(parse_native(compile_text(max_records=2), "parent A\n  other X")) == 1
    with pytest.raises(NativeError) as caught:
        parse_native(compile_text(max_records=2), "parent A\n  other X\nparent B")
    assert caught.value.code == "RESOURCE_LIMIT"


def test_nested_json_byte_budget_includes_empty_collections_and_section_keys():
    source = "@record\nparent {{ id }}\n@record items\n  item {{ item }}\n@end\n@section details\n  details {{ label }}\n@end\n@end"
    expected = [{"id": "A", "items": ({"item": "X"},), "details": {"label": "Y"}}]
    size = len(json.dumps(expected, separators=(",", ":")).encode())
    text = "parent A\n  item X\n  details Y"
    assert parse_native(compile_text(source, max_output_bytes=size), text) == tuple(expected)
    with pytest.raises(NativeError) as caught:
        parse_native(compile_text(source, max_output_bytes=size - 1), text)
    assert caught.value.code == "RESOURCE_LIMIT"


def test_compilation_budgets_are_global_and_tree_is_immutable():
    assert compile_text(max_patterns=7, max_captures=7)
    for limits in ({"max_patterns": 6}, {"max_captures": 6}):
        with pytest.raises(NativeError) as caught:
            compile_text(**limits)
        assert caught.value.code == "RESOURCE_LIMIT"
    compiled = compile_text()
    assert isinstance(compiled.root.children, tuple)
    with pytest.raises(FrozenInstanceError):
        compiled.root.children[0].name = "changed"


def test_transformed_element_budget_is_shared_by_descendants():
    source = (
        '@record\nparent {{ id }}\n@record items\n  item {{ numbers | split(",") }}\n@end\n@end'
    )
    with pytest.raises(NativeError) as caught:
        parse_native(
            compile_text(source, max_transformed_items=3),
            "parent A\n  item 1,2\nparent B\n  item 3,4",
        )
    assert caught.value.code == "RESOURCE_LIMIT"


def test_combined_nested_budgets_include_escaping_intermediates_and_ignored_values():
    source = (
        "@record\nparent {{ id }}\n@record items\n"
        '  item {{ numbers | split(",") | expand_ranges("-") | map_int }}\n'
        '    skip {{ ignore | split(",") }}\n@end\n@end'
    )
    text = 'parent A"\\\u03a9\n  item 1-2\n    skip x,y\nparent B\n  item 3-3\n    skip z'
    expected = (
        {"id": 'A"\\\u03a9', "items": ({"numbers": (1, 2)},)},
        {"id": "B", "items": ({"numbers": (3,)},)},
    )
    limits = {
        "max_input_bytes": len(text.encode()),
        "max_output_bytes": len(
            json.dumps(expected, ensure_ascii=False, separators=(",", ":")).encode()
        ),
        "max_records": 4,
        "max_transformed_items": 11,
    }
    compiled = compile_text(source, **limits)
    first = parse_native(compiled, text)
    assert first == expected
    with pytest.raises(TypeError):
        first[0]["items"][0]["numbers"] = ()
    for name in limits:
        with pytest.raises(NativeError) as caught:
            parse_native(compile_text(source, **(limits | {name: limits[name] - 1})), text)
        assert caught.value.code == "RESOURCE_LIMIT"
        again = parse_native(compiled, text)
        assert again == expected
        assert again is not first
        assert again[0] is not first[0]


@pytest.mark.parametrize(
    ("invalid", "code"),
    [
        ("item 2-1", "MALFORMED_LINE"),
        ("item literal X", "AMBIGUOUS_MATCH"),
        ("item 0-10000", "RESOURCE_LIMIT"),
    ],
)
def test_failed_hierarchical_invocation_does_not_leak_contexts_or_budgets(invalid, code):
    source = (
        "@record\nparent {{ id }}\n@record items\n"
        '  item {{ numbers | phrase | split(",") | expand_ranges("-") | map_int }}\n'
        "  item literal {{ label }}\n@end\n@end"
    )
    compiled = compile_text(source, max_records=4, max_transformed_items=10)
    valid = "parent A\n  item 1-2\nparent A\n  item 1-2"
    expected = (
        {"id": "A", "items": ({"numbers": (1, 2)},)},
        {"id": "A", "items": ({"numbers": (1, 2)},)},
    )
    for _ in range(2):
        with pytest.raises(NativeError) as caught:
            parse_native(compiled, "parent A\n  item 1-2\nparent B\n  " + invalid)
        assert caught.value.code == code
        assert caught.value.__context__ is None
        assert parse_native(compiled, valid) == expected
