from src.hit import IconHit, hit_icon

ICONS = (
    IconHit(r"C:\Users\a\Desktop\a.txt", "a.txt", 10, 10, 50, 70),
    IconHit(r"C:\Users\a\Desktop\b.txt", "b.txt", 80, 10, 50, 70),
)


def test_hit_returns_first_containing_icon() -> None:
    overlap = IconHit("", "overlap", 10, 10, 100, 100)
    assert hit_icon((ICONS[0], overlap), 20, 20) is ICONS[0]


def test_hit_uses_half_open_bounds() -> None:
    assert ICONS[0].contains(10, 10)
    assert ICONS[0].contains(59, 79)
    assert not ICONS[0].contains(60, 20)
    assert not ICONS[0].contains(20, 80)


def test_hit_supports_negative_screen_coordinates() -> None:
    icon = IconHit("x", "x", -200, -100, 50, 70)
    assert hit_icon([icon], -175, -50) == icon


def test_miss_and_invalid_rectangle() -> None:
    invalid = IconHit("x", "x", 0, 0, 0, 10)
    assert hit_icon((*ICONS, invalid), 0, 0) is None


def test_center() -> None:
    assert ICONS[0].center == (35, 45)
