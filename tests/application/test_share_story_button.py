from src.application.place_page import _share_html


def test_share_row_includes_story_button_when_url_given() -> None:
    html = _share_html(
        {"share_url": "https://x/p", "share_body": "hi"},
        story_image_url="https://x/p/story.png",
    )
    assert 'href="https://x/p/story.png"' in html
    assert 'data-story-save="https://x/p/story.png"' in html
    assert "Сторис" in html


def test_share_row_omits_story_without_url() -> None:
    html = _share_html({"share_url": "https://x/p", "share_body": "hi"})
    assert "data-story-save" not in html
