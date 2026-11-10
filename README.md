# Nation Pulse — India

A phone and tablet app that shows the mood of the nation from free public sources:
Google News (English, Hindi, Punjabi, translated to English), Google Trends, and Indian Reddit communities.

- **Pulse** – overall mood score, emotions, political tone, trends over time
- **Viral** – top Google searches in India and most-upvoted Reddit posts
- **Memes** – top memes from Indian meme communities
- **Politics** – pro-government, independent and anti-government posts, with the words that decided each
- **News** – biggest stories and how each is covered

Political sorting is keyword-based and approximate; every post shows why it was sorted the way it was.

## How it runs
- **Online:** GitHub Actions runs `python server.py --once` every 2 hours and publishes the `app` folder to GitHub Pages.
  Run it by hand from the **Actions** tab → *Update Nation Pulse* → *Run workflow*.
- **At home:** double-click `Start Nation Pulse.bat`, then open the address it prints on your phone (same Wi-Fi).

No installs needed beyond Python 3 — only the standard library is used.
