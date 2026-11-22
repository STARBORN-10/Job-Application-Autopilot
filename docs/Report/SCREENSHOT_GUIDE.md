# Screenshot guide for the report and the presentation

The report and the presentation contain grey frames that say **[ Insert screenshot ]**. Each frame has a figure number and a
caption already. Replace each frame with a real screenshot using this list.

## How to take a good screenshot

1. Run the project (see `docs/RUN_LOCALLY.md`) and sign in. **Use a test account or hide personal details** (your e-mail,
   phone number, resume text): you can sign up a second account just for screenshots.
2. Make the browser window about **1440 × 900** and zoom **100%**. Close other tabs and bookmarks bars if you can.
3. Capture on Windows with **Win + Shift + S** (Snipping Tool), drag a rectangle around the page content, and save it as PNG.
4. Keep the shape close to **16:9** (wide). The frames are 16:9, so a 16:9 screenshot fills them exactly.

## How to replace a picture in Word

1. Click the grey frame in the report.
2. Right-click, then **Change Picture**, then **From a File**, and choose your screenshot.
   Word keeps the same place and size, and the figure number and caption stay.
3. When all screenshots are in, press **Ctrl + A** and then **F9** (choose **Update entire table** if Word asks).
   This refreshes the page numbers in the Table of Contents and the List of Figures.
   Word may also ask "update fields?" when you open the file: click **Yes**.
   Do this once more just before you print or export to PDF, because pictures move the pages.

In PowerPoint: click the picture, right-click, **Change Picture**, **From a File**.

## The screenshots for the report

The report has five grey frames. Four are screenshots of the running website or Telegram, and one is the workflow map.

| Figure | Caption in the report | Open this | What it must show |
|---|---|---|---|
| **Fig 4.3** | The interactive workflow map | `http://localhost:5173/workflow.html` (or double-click `frontend/public/workflow.html`) | Close the welcome box, press the **fit** button (square icon, bottom right) so the whole map is visible. Light theme looks best in print. |
| **Fig 5.1** | Dashboard with live search progress | `http://localhost:5173/` | Press **Find New Jobs** and capture while the progress panel is running: the step bar, one row per source, and the "new jobs" counter. |
| **Fig 5.2** | Job page with score breakdown and cover letter | Open any job from the list (a job scoring below 9 is best) | The score, the colour breakdown ("Why this score", matched and missing skills) and the start of the cover letter. Scroll so these are on screen. |
| **Fig 5.3** | Profile page with Telegram connection | `http://localhost:5173/profile` | The page after pressing **Connect Telegram** (code and "Open Telegram" button), or after connecting (green "Connected"). Hide your e-mail if it is personal. |
| **Fig 5.4** | Telegram alert with Approve and Skip buttons | Telegram on your phone or desktop | One job alert from the bot with the **Approve**, **Skip** and **Cover letter** buttons visible. Hide your name if shown. |

The other figures (3.1, 4.1, 4.2) are diagrams and are already in the report.

## The screenshots for the presentation (slide 9, "Website Tour")

Slide 9 has four frames. Reuse the screenshots above:

| Slide 9 position | Caption | Use this screenshot |
|---|---|---|
| Top left | Dashboard with live progress | Fig 5.1 |
| Top right | Job page: score breakdown + letter | Fig 5.2 |
| Bottom left | Profile with Telegram link | Fig 5.3 |
| Bottom right | Telegram alert with buttons | Fig 5.4 |

## Where to see the workflow map when you present

The workflow map is a normal web page, so you do not need the project running to show it:

- **Without running anything:** double-click `frontend/public/workflow.html`. It opens in the browser and works by itself.
  Press **Walkthrough** for a 9-step tour of the whole system.
- **With the project running:** open `http://localhost:5173/workflow.html`, or **Workflow map** in the sidebar.
- **On the hosted site:** `https://<your-vercel-address>/workflow.html` once the workflow branch is merged and deployed.

All commands to start the project are in `docs/RUN_LOCALLY.md`.
