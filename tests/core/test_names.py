import pytest

from custom_components.scene_setter.core.names import SceneNameError, clean_name, full_name, id_text, same_name, short_name


def test_clean_name_tidies_spacing():
    assert clean_name("  Movie   night ") == "Movie night"


@pytest.mark.parametrize("bad", ["", "   ", None, "x" * 61])
def test_clean_name_refuses(bad):
    with pytest.raises(SceneNameError):
        clean_name(bad)


def test_full_name_puts_the_room_first():
    assert full_name("Kitchen", "Evening") == "Kitchen Evening"


def test_full_name_does_not_repeat_the_room():
    assert full_name("Kitchen", "Kitchen evening") == "Kitchen evening"
    assert full_name("Kitchen", "kitchen") == "kitchen"


def test_short_name_drops_the_room():
    assert short_name("Kitchen", "Kitchen Evening") == "Evening"
    assert short_name("Kitchen", "kitchen evening") == "evening"


def test_short_name_leaves_other_names_alone():
    assert short_name("Kitchen", "Evening") == "Evening"
    assert short_name("Kitchen", "Kitchenette lights") == "Kitchenette lights"
    assert short_name("Kitchen", "Kitchen") == "Kitchen"


def test_names_round_trip():
    for name in ("Evening", "Movie night", "Kitchen", "Kitchen party"):
        assert short_name("Kitchen", full_name("Kitchen", name)) in (name, name[len("Kitchen "):])


def test_same_name_ignores_case_and_spacing():
    assert same_name("Movie  Night", "movie night")
    assert not same_name("Movie", "Movies")


@pytest.mark.parametrize("apostrophe", ["'", "’", "‘", "ʼ", "`"])
def test_id_text_drops_apostrophes(apostrophe):
    assert id_text(f"Oli{apostrophe}s Office Dim") == "Olis Office Dim"


def test_id_text_leaves_other_names_alone():
    assert id_text("Kitchen Evening") == "Kitchen Evening"
