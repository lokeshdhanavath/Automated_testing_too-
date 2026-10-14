from pathlib import Path
from playwright.sync_api import sync_playwright

LOGIN_URL = "https://oracleapex.com/ords/r/lokesh354/timesheet-application/login"

VIDEO_DIR = Path("videos")
VIDEO_DIR.mkdir(exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)

    context = browser.new_context(
        record_video_dir=str(VIDEO_DIR),
        record_video_size={"width": 1280, "height": 720},
    )

    page = context.new_page()

    print("Opening:", LOGIN_URL)
    page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)

    page.wait_for_timeout(4000)
    page.mouse.move(400, 400)
    page.wait_for_timeout(1000)

    print("Page title:", page.title())

    video = page.video

    context.close()
    browser.close()

    video_path = video.path()
    print("Video saved at:", video_path)
    print("Video file size (bytes):", Path(video_path).stat().st_size)