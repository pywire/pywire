"""Uploads in a real browser: picked files upload at once, submits carry ids."""

from playwright.sync_api import Page, expect


def _file(name: str, body: bytes, mime: str = "text/plain") -> dict:
    return {"name": name, "mimeType": mime, "buffer": body}


def test_file_uploads_when_picked_and_reaches_the_handler(page: Page, pywire_server):
    page.goto(f"{pywire_server}/uploads")
    avatar = page.locator('input[name="avatar"]')
    expect(avatar).to_have_attribute("accept", ".txt")

    with page.expect_response("**/_pywire/upload") as upload:
        avatar.set_input_files(_file("hello.txt", b"hello"))
    assert upload.value.status == 200
    expect(page.locator("progress")).to_have_js_property("value", 1)
    expect(avatar).not_to_have_attribute("data-pw-uploading", "")

    page.fill('input[name="name"]', "Al")
    page.click("#save")
    expect(page.locator("#saved")).to_have_text("Al:hello.txt:hello")


def test_files_are_checked_before_upload(page: Page, pywire_server):
    page.goto(f"{pywire_server}/uploads")
    uploads = []
    page.on(
        "request",
        lambda r: uploads.append(r.url) if "/_pywire/upload" in r.url else None,
    )
    avatar = page.locator('input[name="avatar"]')

    avatar.set_input_files(_file("big.txt", b"x" * 2000))
    expect(avatar).to_have_js_property(
        "validationMessage", "Choose a file no larger than 1 KB"
    )
    avatar.set_input_files(_file("photo.png", b"png", "image/png"))
    expect(avatar).to_have_js_property(
        "validationMessage", "Choose a file of type .txt"
    )
    assert uploads == []
