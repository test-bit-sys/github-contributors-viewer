# GitHub Contributors Viewer

A lightweight contributor explorer for public GitHub repositories, available as both a Python desktop application and a standalone web page. Fetch contributors, search and sort results, inspect profiles, and export the rows you need.

## Features

- Fetch contributors from a GitHub repository, including anonymous contributors when available.
- Search contributor usernames and profile details, and filter by minimum contribution count.
- Sort the contributor table and open GitHub profiles.
- Optionally fetch names, companies, and locations for GitHub accounts.
- Export the currently displayed results as CSV, JSON, or Markdown.
- Cache results and remember recent repositories for quicker repeat use.
- Monitor GitHub API rate limits in the web edition.

## Choose an Edition

| Edition | Entry point | Requirements |
| --- | --- | --- |
| Desktop | [`github.py`](github.py) | Python 3, Tkinter, and `requests` |
| Web | [`github_contributors_viewer.html`](github_contributors_viewer.html) | A modern browser and an internet connection |

Both editions call the GitHub REST API directly. No server or build step is required.

## Desktop Setup

1. Install Python 3. Tkinter is included with most Windows and macOS Python installations. On Linux, install the `python3-tk` system package if needed.
2. From the project directory, install the Python dependency:

   ```bash
   python -m pip install -r requirements.txt
   ```

3. Start the application:

   ```bash
   python github.py
   ```

On Windows, use `py` in place of `python` if that is the Python launcher installed on your system.

## Web Edition

Open `github_contributors_viewer.html` in a modern browser, or publish it with GitHub Pages. The page uses Tailwind CSS and Google Fonts from their CDNs, so those visual resources require an internet connection.

## Using the Viewer

Enter a repository URL or `owner/repo`, then select **Fetch Contributors**. Use the search field and minimum-contributions filter to narrow the table. Select an export format to download the rows currently shown.

A GitHub personal access token is optional and can increase the API rate limit for authenticated requests. Use a token with only the permissions you need; public repository access does not require repository write access.

## Token and Local Data

Both editions save settings locally, including a token if you enter one. The desktop edition stores its configuration under `~/.contributors_viewer/config.json` (on Windows, in your user home directory); the web edition uses browser `localStorage`. These locations are not encrypted by the application. Avoid saving a token on shared devices, and remove it from the application settings and local storage when it is no longer needed. Never commit tokens or other secrets to GitHub.

Contributor data is cached locally by each edition. The desktop cache is stored under `~/.contributors_viewer/cache/`; the web cache is stored in browser `localStorage` and can be cleared from the page.

## Project Files

```text
.
├── github.py                       # Python/Tkinter desktop application
├── github_contributors_viewer.html # Standalone web application
├── requirements.txt                # Python dependencies
├── .gitignore                      # Local and generated files excluded from Git
└── README.md
```

## Publish to GitHub

Create an empty repository on GitHub, then run these commands from the project directory. Replace the URL with the URL of your repository.

```bash
git remote add origin https://github.com/YOUR-USERNAME/YOUR-REPOSITORY.git
git add .
git commit -m "Prepare GitHub Contributors Viewer"
git push -u origin main
```

## GitHub API Notes

Unauthenticated GitHub API requests are subject to a lower rate limit. If requests are limited, wait for the reset time shown by the web edition or provide your own token. The optional profile-detail lookup makes additional API requests and may take longer for repositories with many contributors.

## License

No license is currently specified. Add a license before allowing others to reuse or distribute this project.