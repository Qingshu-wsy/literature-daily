# Literature Daily

[简体中文](README.md) | [English](README.en.md)

A Windows desktop application for literature discovery and screening. It searches OpenAlex and Crossref metadata by research topic, scores matching papers, and creates interactive HTML, Excel, and JSON reports. The GUI is built with PySide6, and the HTML report can also be viewed in the app.

> **Important:** This application searches public metadata from OpenAlex and Crossref. A campus network or publisher login only affects your access to article webpages; the app does not download paywalled full text. Abstract availability depends on the metadata record. Translation cannot recover an English abstract that is not available.

## Run the packaged application

For the folder distribution, run `dist\文献日报\文献日报.exe` and keep the `_internal` directory beside it.

You can also run the single-file distribution at `dist\文献日报单文件\文献日报.exe`. It does not need an `_internal` directory. Keep `config.yaml` beside it if you want to retain your search settings. The app creates its cache and output folders next to the executable, so use a writable location and avoid protected folders such as `Program Files`.

- On first use, open **Search and Settings** in the GUI to configure any portal, translation, or email options you need, then save.
- To search custom terms, select **Custom direction** and enter keywords in the field that appears. Existing topics are not affected.
- A GUI search defaults to the most recent **3 days**. You can also select **7** or **15 days**, and search all topics or one topic.
- Filter papers on the **Search Results** tab and view the full interactive report on the **HTML Report** tab.
- The **About** button displays the app version and author information.
- Reports, caches, state, logs, and `secrets.yaml` are stored beside the executable. Use a folder writable by the current Windows user, such as Documents.
- Portal passwords, translation API keys, and SMTP credentials are encrypted with Windows DPAPI for the current Windows user. Re-enter them when moving the app to a different Windows account or computer.

## Run from source

Install the dependencies and start the GUI:

```bat
python -m pip install -r requirements.txt
python gui.py
```

Run a search from the command line:

```bat
python run_daily.py --days 3 --topic COF
python run_daily.py --days 7 --topic OLED --no-translate
python run_daily.py --days 15
```

Common command-line options:

| Option | Description |
|---|---|
| `--days N` | Search the most recent N days |
| `--topic NAME` | Search only the topic whose name matches |
| `--top N` | Limit the number of papers in the report |
| `--include-reported` | Include papers recorded in previous reports |
| `--no-translate` | Disable translation for this run |
| `--no-open` | Do not open the report after generation |
| `--email` | Try to send email after this run |

Results are saved under `out\daily\` and `out\data\`. `latest.html` is the latest HTML report.

## Build the Windows executable

The project includes `文献.ico` and `build_exe.bat`. Double-click the script or run:

```bat
build_exe.bat
```

The script installs build dependencies if needed and creates two icon-enabled distributions:

```text
dist\文献日报\文献日报.exe
dist\文献日报单文件\文献日报.exe
```

The folder distribution must keep its `_internal` directory. The single-file executable does not need that directory, but is larger and takes longer to start because it extracts its runtime files when launched. The build script does not bundle your local `secrets.yaml`. Never publish personal credentials or generated reports. Rebuilding updates the executables and runtime files while preserving existing configuration, credentials, and user data in the distribution folders.

## Search sources and portal settings

- **Sources:** OpenAlex is tried first; the app falls back to Crossref when OpenAlex is unavailable or its quota is exhausted.
- **Publisher links:** Reports include DOI and publisher-page links. Access to paywalled full text still requires an institutional subscription, campus network, or VPN.
- **Abstracts:** The app uses metadata from OpenAlex and Crossref and may try to supplement it from Crossref. Some records do not have an abstract.
- **Portal login:** The GUI can store a campus or database portal URL and credentials and optionally attempt automatic login. Automatic login only supports the portal flows implemented by this project. It is not publisher-page scraping and may not work with every institution's login page.

Portal settings may be left blank. If login is unsupported or fails, the app still attempts to generate a report using OpenAlex and Crossref.

## Topics and date ranges

The topics and date range selected in the GUI apply to both immediate searches and scheduled runs. Selecting one topic, such as COF, limits the report's papers, topic labels, statistics, and HTML filters to that topic. **All topics** uses the topics configured in `config.yaml`.

The topic list includes a fixed **Custom direction** option. Its keyword field is shown only when that option is selected; custom terms are not mixed into existing topics. Enter one keyword per line, or separate terms with commas or semicolons. The app combines the terms into a topic label (for example, `Perovskite, COF` becomes `Perovskite COF`) and searches them with OR logic. Saved custom terms apply only to the selected custom direction, and the actual terms are shown in result details and the HTML report. Search coverage depends primarily on the metadata available from OpenAlex and Crossref.

Search terms are not automatically translated. Chinese terms are sent as entered, but OpenAlex and Crossref records are predominantly in English, so Chinese-only queries may miss relevant papers. Consider including English equivalents and synonyms in the same topic. Translation settings apply to paper titles and abstracts only; they do not translate search terms.

The default search window is 3 days; 7- and 15-day windows are also available. OpenAlex and Crossref may index papers with a delay, so a date window does not guarantee that every paper in that period has been indexed. Longer windows also increase the number of requests. Previously reported papers are deduplicated; use the GUI option to include previously reported papers when you want to review an earlier date range again.

## Translation settings

The GUI supports these translation modes:

- **Titles only**
- **Abstracts only**
- **Titles and abstracts** (default)

When a translation is available, the report displays the Chinese translation alongside the English original. The abstract character limit can be adjusted in the GUI; set it to `0` to skip abstract translation. An English abstract is required for translation.

Available backends are `auto`, Youdao, MyMemory, DeepSeek, Zhipu, and Baidu. Text selected for translation is sent to the chosen provider. Review the provider's privacy terms, pricing, and quotas. Translations are cached in `cache\translate.json`.

X-MOL pages may require human verification. This project does not use an X-MOL official API or attempt to bypass verification. An integration may be considered if an official, authorized API becomes available.

## Email settings

Email is sent through the SMTP account you configure; it is not sent by this application. The GUI needs:

1. An SMTP server and port (for example, `smtp.qq.com:465`; confirm the current settings with your email provider).
2. The sender email address.
3. An SMTP authorization code from the provider (usually not the account login password).
4. One or more recipient email addresses.

To send a report to yourself, use the same address as sender and recipient. Enable **Send email after filtering** and save the settings. Email is sent only when the run has results that meet the sending criteria. Make sure SMTP access is enabled with your email provider before configuring it.

## Daily scheduled task

Choose the topic, date range, and run time in the GUI, then click **Set daily task**. Windows Task Scheduler launches the app under the current account and writes logs to `logs\run.log`. The computer must be on and connected to the network at the scheduled time.

If you move the executable folder, delete the old task in the GUI and create it again. To delete the task from the command line:

```bat
schtasks /Delete /TN "LitDaily" /F
```

## Configuration and data files

| Path | Purpose |
|---|---|
| `config.yaml` | Base settings for topics, search, scoring, translation, and output |
| `secrets.yaml` | Local private settings, usually written by the GUI; do not share it |
| `secrets.example.yaml` | Manual configuration template without real credentials |
| `state\state.json` | Previously reported papers, saved feedback, and deduplication state |
| `state\gui_settings.json` | GUI topic, date range, scheduled task, and custom keyword settings |
| `cache\` | Paper metadata and translation cache |
| `out\daily\` | HTML reports |
| `out\data\` | JSON and Excel reports |
| `logs\` | Runtime logs |

Deleting the state file affects deduplication and may cause previously reported papers to appear again. Deleting the translation cache means existing text may be translated again.

## Troubleshooting

- **OpenAlex returns a 429 or budget error:** The app attempts to fall back to Crossref when the quota is exhausted or requests are rate-limited. You can also request a free OpenAlex API key and add it to the configuration.
- **An abstract is missing:** Check whether the metadata source provides one. Portal login does not guarantee that the API has an abstract.
- **The Windows taskbar icon does not update:** The source sets the window icon and Windows AppUserModelID. Rebuild the app for the change to take effect. Unpin an old taskbar shortcut, then launch and pin the new executable.
- **Translation is empty or fails:** Check the runtime log, translation settings, provider credentials, network connection, and provider quota. You can also disable translation and still generate a report.
- **A site-unavailable message appears at the top of a page or email:** Recent versions no longer show preflight warnings in HTML reports or emails. Detailed diagnostics remain in the runtime log.
- **The scheduled task does not run:** Check its status in Windows Task Scheduler, confirm the executable folder is writable and the computer is on at the scheduled time, and ensure the current user can decrypt DPAPI credentials.
- **The executable fails to start:** Keep the entire folder distribution; do not copy only the EXE. If building from source, run `build_exe.bat` again and check its output.

## Project entry points

| File | Purpose |
|---|---|
| `gui.py` | Desktop GUI and packaged-app entry point |
| `run_daily.py` | Literature search, screening, translation, and report generation |
| `run_scheduled.py` | Scheduled-task entry point |
| `core\sources.py` | OpenAlex and Crossref data collection |
| `core\custom_topics.py` | Parsing and building custom GUI topics |
| `core\translate.py` | Translation backends, mode selection, and cache |
| `core\report.py` | HTML and Excel reports |
| `core\mailer.py` | SMTP email delivery |
| `core\credentials.py` | Windows DPAPI credential protection |
| `build_exe.bat` | Build icon-enabled executable distributions |
