"""Drive the app through the demo story in a headless browser and record it.

Run by demo/record.sh, inside the recorder container. Each `caption` is one beat of the
story, so the captions in order are also the narration: they are written to
output/narration.md with the time each one appears.
"""

import base64
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from playwright.sync_api import Locator, sync_playwright

BASE = os.environ.get("DEMO_URL", "http://demo-web:8000")
OUTPUT = Path(os.environ.get("DEMO_OUTPUT", "/demo/output"))
# Below 1 hurries through the pauses, for checking the script still works.
SPEED = float(os.environ.get("DEMO_SPEED", "1"))
PASSWORD = "demo-password"  # noqa: S105 - local demo accounts only, see seed.py
SIZE = {"width": 1280, "height": 720}

TITLE = {"title": "GitHub Access Requests", "subtitle": "From request to approved YAML change"}


class Recorder:
    """Capture the page as timestamped frames, then join them into a video.

    Playwright's own recorder drifts from real time, which would put the captions and any
    voiceover out of step, and its bitrate is too low for small text.
    """

    def __init__(self, page, directory: Path):
        self.directory = directory
        self.frames = []
        self.session = page.context.new_cdp_session(page)
        self.session.on("Page.screencastFrame", self._frame)

    def start(self):
        options = {"format": "jpeg", "quality": 95, "everyNthFrame": 1}
        self.session.send("Page.startScreencast", {**options, "maxWidth": 1280, "maxHeight": 720})

    def _frame(self, event):
        name = f"{len(self.frames):06d}.jpg"
        (self.directory / name).write_bytes(base64.b64decode(event["data"]))
        # Timed on arrival with the monotonic clock. The browser stamps frames with the wall
        # clock, which can be stepped while recording (it is under WSL2) and squash the video.
        self.frames.append((time.monotonic(), name))
        self.session.send("Page.screencastFrameAck", {"sessionId": event["sessionId"]})

    @property
    def started(self):
        return self.frames[0][0]

    def finish(self, video: Path):
        self.session.send("Page.stopScreencast")
        times = [at for at, _ in self.frames] + [time.monotonic()]
        lines = []
        for index, (_, name) in enumerate(self.frames):
            lines += [
                f"file '{name}'",
                f"duration {max(times[index + 1] - times[index], 0.001):.3f}",
            ]
        # The concat demuxer needs the last frame named again for its duration to count.
        lines.append(f"file '{self.frames[-1][1]}'")
        listing = self.directory / "frames.txt"
        listing.write_text("\n".join(lines) + "\n")
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", listing,
             "-vf", "fps=30,format=yuv420p", "-c:v", "libx264", "-crf", "18",
             "-movflags", "+faststart", video],
            check=True,
        )  # fmt: skip


class Demo:
    def __init__(self, context, page, recorder):
        self.context = context
        self.page = page
        self.recorder = recorder
        self.narration = []
        self.shots = 0

    # Pacing and overlays

    def pause(self, seconds):
        self.page.wait_for_timeout(seconds * 1000 * SPEED)

    def _set(self, **update):
        self.page.evaluate("update => window.__demo.set(update)", update)

    def _note(self, text):
        elapsed = int(time.monotonic() - self.recorder.started)
        self.narration.append((elapsed, text))

    def card(self, title, subtitle="", hold=3.0):
        """A full-screen title card. It stays up, across page loads, until `reveal`."""
        self._set(card={"title": title, "subtitle": subtitle}, caption="")
        self._note(f"**{title}** {subtitle}".strip())
        self.pause(hold)

    def reveal(self):
        self._set(card=None)
        self.pause(0.8)

    def caption(self, text, hold=2.5):
        self._set(caption=text)
        self._note(text)
        self.pause(0.5)
        self.shots += 1
        self.page.screenshot(path=OUTPUT / "shots" / f"{self.shots:02d}.png")
        self.pause(hold)

    # Actions, done at a pace a viewer can follow

    def move(self, target: Locator):
        target.evaluate("e => e.scrollIntoView({block: 'center', behavior: 'smooth'})")
        self.pause(0.5)
        box = target.bounding_box()
        self.page.mouse.move(
            box["x"] + box["width"] / 2, box["y"] + box["height"] / 2, steps=max(2, int(28 * SPEED))
        )
        self.pause(0.35)

    def click(self, target: Locator, after=0.9):
        self.move(target)
        target.click()
        self.pause(after)

    def type(self, target: Locator, text):
        self.move(target)
        target.click()
        target.press_sequentially(text, delay=55 * SPEED)
        self.pause(0.5)

    def choose(self, target: Locator, label):
        self.move(target)
        target.select_option(label=label)
        self.pause(0.7)

    def scroll_to(self, target: Locator, hold=1.0):
        """Bring something into view. Anything too tall to centre is shown from its top."""
        target.evaluate(
            """e => {
                const tall = e.getBoundingClientRect().height > innerHeight * 0.6;
                e.style.scrollMarginTop = "70px";
                e.scrollIntoView({block: tall ? "start" : "center", behavior: "smooth"});
            }"""
        )
        self.pause(hold)

    def open(self, path):
        self.page.goto(BASE + path)

    def sign_in(self, email):
        """Swap user behind a title card, so the recording never shows a login form."""
        self.context.clear_cookies()
        api = self.context.request
        form = api.get(f"{BASE}/admin/login/").text()
        token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', form).group(1)
        api.post(
            f"{BASE}/admin/login/",
            form={"csrfmiddlewaretoken": token, "username": email, "password": PASSWORD},
        )
        if not any(cookie["name"] == "sessionid" for cookie in self.context.cookies()):
            raise RuntimeError(f"Could not sign in as {email}")

    # Page furniture

    def nav(self, name):
        return self.page.locator("nav.navbar").get_by_role("link", name=re.compile(f"^{name}"))

    def formset(self, legend):
        return self.page.locator("fieldset").filter(
            has=self.page.locator("legend", has_text=legend)
        )

    def add_row(self, fieldset: Locator, principal, permission):
        self.click(fieldset.locator("[data-formset-add]"), after=0.4)
        row = fieldset.locator("[data-formset-rows] [data-formset-row]").last
        self.choose(row.locator("select").nth(0), principal)
        self.choose(row.locator("select").nth(1), permission)

    def row_for(self, fieldset: Locator, principal) -> Locator:
        rows = fieldset.locator("[data-formset-rows] [data-formset-row]")
        for index in range(rows.count()):
            if rows.nth(index).locator("select").first.input_value() == principal:
                return rows.nth(index)
        raise RuntimeError(f"No row for {principal}")

    def open_section(self, name):
        self.click(self.page.locator(f'button[data-bs-target="#{name}"]'), after=1.0)


def sre_adds_an_organisation(demo: Demo):
    page = demo.page
    demo.card("1. Set up a new organisation", "An SRE adds it in the admin", hold=2.5)
    demo.sign_in("sam.rivera@example.com")
    demo.open("/admin/")
    demo.reveal()
    demo.caption("Organisations are managed in the admin, not inferred from directories.")
    demo.click(page.locator("#content-main").get_by_role("link", name="Organisations", exact=True))
    demo.caption("One organisation, acme, is already managed.", hold=1.5)
    demo.click(page.locator(".object-tools a.addlink"))
    demo.type(page.locator("#id_name"), "gov-recruitment")
    demo.caption("Only the GitHub name is needed. The config directory defaults to it.")
    demo.click(page.locator('input[name="_save"]'))
    demo.caption("That is all the set-up a new organisation needs.", hold=2.0)


def developer_requests_changes(demo: Demo):
    page = demo.page
    demo.card("2. Request a change", "A developer asks for a new repository", hold=2.5)
    demo.sign_in("jo.carter@example.com")
    demo.open("/")
    demo.reveal()
    demo.caption("The new organisation is available to everyone straight away.", hold=2.0)
    demo.click(page.get_by_role("link", name="gov-recruitment"))
    demo.open_section("repositories")
    demo.caption("It has no repositories yet, and no config file on disk.", hold=2.0)
    demo.click(page.get_by_role("link", name="Add repository"))

    demo.type(page.get_by_label("Name", exact=True), "careers-site")
    demo.type(page.get_by_label(re.compile("^Description")), "Public careers and vacancies site")
    demo.caption("Jo names the repository and says who should have access.", hold=1.5)
    users = demo.formset("Users")
    demo.add_row(users, "jdoe", "Admin")
    demo.add_row(users, "kpatel", "Push")
    demo.choose(page.get_by_label("Portfolio", exact=True), "Corporate Services")
    demo.caption("Every request names the portfolio whose approvers sign it off.")
    demo.click(page.get_by_role("button", name="Review request"))
    demo.caption("A plain summary of the change, and who will be asked to approve it.", hold=3.5)
    demo.click(page.get_by_role("button", name="Submit request"))
    demo.caption("Submitted. Jo can track it under My requests.", hold=2.0)

    demo.caption("Existing repositories work the same way.", hold=1.0)
    demo.click(demo.nav("Organisations"))
    demo.click(page.get_by_role("link", name="acme"))
    demo.open_section("repositories")
    trade_api = page.locator("li.list-group-item").filter(has_text="trade-api")
    demo.click(trade_api.get_by_role("link", name="Edit collaborators"))
    demo.caption("The form starts from what is in the YAML today.", hold=2.0)
    teams = demo.formset("Teams")
    demo.choose(demo.row_for(teams, "data-engineering").locator("select").nth(1), "Maintain")
    users = demo.formset("Users")
    demo.click(demo.row_for(users, "old-contractor").locator("[data-formset-delete]"))
    demo.caption("Jo raises one team's permission and removes a contractor who has left.")
    demo.choose(page.get_by_label("Portfolio", exact=True), "Digital Trade")
    demo.click(page.get_by_role("button", name="Review request"))
    demo.caption("Only the differences are recorded: one change, one removal.", hold=3.0)
    demo.click(page.get_by_role("button", name="Submit request"))
    demo.caption("Both requests are now waiting for an approver.", hold=2.5)


def approver_decides(demo: Demo):
    page = demo.page
    demo.card("3. Approve", "The portfolio approver reviews each request", hold=2.5)
    demo.sign_in("priya.shah@example.com")
    demo.open("/")
    demo.reveal()
    demo.caption("Priya is an approver, so she has an Approvals page with two waiting.", hold=2.0)
    demo.click(demo.nav("Approvals"))
    demo.pause(1.0)
    demo.click(page.locator("tr").filter(has_text="careers-site").get_by_role("link"))
    demo.caption("She sees who asked, and what they asked for.", hold=2.0)
    diff = page.locator("pre").filter(has_text="config.yaml")
    demo.scroll_to(diff)
    demo.caption(
        "And the exact change approving will make. Here it creates the organisation's first file.",
        hold=4.5,
    )
    demo.type(page.get_by_label("Comment"), "Agreed with the recruitment team.")
    demo.click(page.get_by_role("button", name="Approve", exact=True))
    demo.caption("Approved, and written into the YAML in the same step.", hold=3.0)

    demo.click(demo.nav("Approvals"))
    demo.click(page.locator("tr").filter(has_text="trade-api").get_by_role("link"))
    demo.scroll_to(page.locator("pre").filter(has_text="config.yaml"))
    demo.caption(
        "For an existing repository only the affected lines change. "
        "Comments and other settings are left alone.",
        hold=5.0,
    )
    demo.click(page.get_by_role("button", name="Approve", exact=True))
    demo.pause(1.5)

    demo.click(demo.nav("Organisations"))
    demo.click(page.get_by_role("link", name="gov-recruitment"))
    demo.open_section("repositories")
    demo.caption("The app reads the YAML, so the new repository is there immediately.", hold=3.0)


def sre_overview(demo: Demo):
    page = demo.page
    demo.card("4. Oversight", "SRE can see every request", hold=2.5)
    demo.sign_in("sam.rivera@example.com")
    demo.open("/admin/change_requests/changerequest/")
    demo.reveal()
    demo.caption("Every request from every portfolio, with filters and search.", hold=3.5)
    demo.click(page.locator("#changelist-filter").get_by_role("link", name="Applied"))
    demo.caption("It is read-only, so the approval trail cannot be bypassed.", hold=2.5)
    demo.click(page.locator("#result_list tr").filter(has_text="careers-site").locator("th a"))
    demo.scroll_to(page.locator("pre"))
    demo.caption("Each record keeps the decision and the diff that was written.", hold=4.0)


def record():
    shots = OUTPUT / "shots"
    shutil.rmtree(shots, ignore_errors=True)
    shots.mkdir(parents=True)
    frames = OUTPUT / "frames"
    shutil.rmtree(frames, ignore_errors=True)
    frames.mkdir()

    overlay = (Path(__file__).parent / "overlay.js").read_text()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(viewport=SIZE, base_url=BASE)
        context.add_init_script(overlay.replace("__FIRST_CARD__", json.dumps(TITLE)))
        page = context.new_page()
        page.set_default_timeout(15000)
        page.goto(f"{BASE}/healthcheck/")
        recorder = Recorder(page, frames)
        demo = Demo(context, page, recorder)
        recorder.start()
        try:
            demo.pause(0.5)
            demo._note(f"**{TITLE['title']}** {TITLE['subtitle']}")
            demo.pause(3.0)
            sre_adds_an_organisation(demo)
            developer_requests_changes(demo)
            approver_decides(demo)
            sre_overview(demo)
            demo.card("Request, approve, applied", "Next: raise the change as a pull request")
            demo.pause(1.0)
            final = OUTPUT / "demo.mp4"
            recorder.finish(final)
        except Exception:
            page.screenshot(path=OUTPUT / "shots" / "failed.png", full_page=True)
            raise
        finally:
            context.close()
            browser.close()

    shutil.rmtree(frames)
    lines = [f"- `{at // 60}:{at % 60:02d}` {text}" for at, text in demo.narration]
    (OUTPUT / "narration.md").write_text("# Narration\n\n" + "\n".join(lines) + "\n")
    print(f"Recorded {final}, {len(recorder.frames)} frames")


if __name__ == "__main__":
    record()
