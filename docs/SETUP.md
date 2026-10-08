# Setting up

This guide takes you from nothing to working on the project: editing the website, designing in Houdini against the site and
your design, and proposing changes through pull requests. It is written for **macOS**.

Set up only as far as you need:

| Level | You can | You need sections |
|---|---|---|
| **0. Look** | Open the site viewer in a browser | none: open https://ruiw0211.github.io/sci-arc-studio-fall2026/ |
| **1. Website and content** | Change text, views, colours and pages; preview locally; open pull requests | 1–5 |
| **2. 3D model** | Model your design in Houdini and show it on the website | 1–7 |
| **3. Data pipeline** | Re-run the LiDAR / building / tree processing (Rui) | 1–8 |

Most people want level 2. Allow about an hour the first time.

> Every step ends with a **Check**: what you should see if it worked. If you see something else, stop
> there. Ask in the pull request or message Rui, and include a screenshot. These steps have not yet been
> run end to end on a Mac, so tell us whatever differs and we will fix this guide.

---

## 1. Homebrew, git, GitHub CLI and Python

Homebrew installs developer tools on a Mac. Open **Terminal** (Applications → Utilities → Terminal) and
paste:

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

At the end it prints two or three lines under **Next steps**. Copy and run them; they add `brew` to your
PATH. Then install the tools:

```bash
brew install git gh python@3.12
```

**Check:** each of these prints a version number:

```bash
git --version
gh --version
python3 --version
```


## 2. GitHub account and access

1. Create a free account at https://github.com/signup.
2. Turn on email privacy: **Settings → Emails →** tick **Keep my email addresses private** and **Block
   command line pushes that expose my email**. GitHub then shows you a private address like
   `12345678+yourname@users.noreply.github.com`.
3. Send your GitHub username to the repository owner (Rui, GitHub `RuiW0211`). You will get an email
   invitation to `RuiW0211/sci-arc-studio-fall2026`. Accept it.
4. Sign in from Terminal:

   ```bash
   gh auth login --hostname github.com --git-protocol https --web
   ```

   It shows a one-time code and opens the browser. Enter the code and authorize. Wait in Terminal until
   it prints **Logged in as yourname** before closing anything.
5. Tell git who you are (your name, and the private address from step 2):

   ```bash
   git config --global user.name "Your Name"
   git config --global user.email "12345678+yourname@users.noreply.github.com"
   ```

**Check:** `gh auth status` says **Logged in to github.com account yourname**.


## 3. Get the project

```bash
mkdir -p ~/GitHub
gh repo clone RuiW0211/sci-arc-studio-fall2026 ~/GitHub/sci-arc-studio-fall2026
cd ~/GitHub/sci-arc-studio-fall2026
```

Keep the project **outside** iCloud Drive, Dropbox and OneDrive. Sync tools and git interfere with each
other. GitHub is the backup.

**Check:** `git log --oneline -3` lists recent changes.

## 4. Preview the website on your computer

```bash
python3 web/serve.py
```

Open http://localhost:8766/ in your browser and click **Site model viewer**. Stop the server with
**Ctrl + C**.

**Check:** the viewer loads the LiDAR point cloud. Clicking a building shows a tag with its name and address.

`serve.py` serves the model the same way the live site does, so what you see locally is what will be
published.

## 5. Claude

1. Download the Claude desktop app for Mac from https://claude.ai/download and open it.
2. Sign in with your **Syracuse University** account (the Enterprise organisation).
3. Open the **Code** tab and choose the folder `~/GitHub/sci-arc-studio-fall2026`.

Claude reads `CLAUDE.md` in the project automatically, so it already knows the rules: work on a branch,
open a pull request, never push to `main`, never add copyrighted references. You can ask it in plain
language, for example *"make a branch and change the Overview camera so Y-1 is centred, then open a pull
request"*. Claude can run `git` and `gh` for you; you approve each step.

**Check:** ask Claude *"what is this project and what are the rules for contributing?"*. Its answer
should mention branches and pull requests.

---

*Level 1 ends here. Continue with [WORKFLOW.md](WORKFLOW.md) for the day-to-day routine.*

---

## 6. Houdini

All 3D work is done in Houdini (see [site-model/houdini/README.md](../site-model/houdini/README.md)).

1. Create a free SideFX account at https://www.sidefx.com/login/ .
2. Download the **Houdini Launcher** for macOS from https://www.sidefx.com/download/ and open it.
3. In the Launcher: **Installations → Install Houdini**, choose **Houdini 22.0** (production build), then the licence
   **Houdini Apprentice** (free, non-commercial). Use Apprentice, like everyone else on the team: files saved by
   another licence type (Indie, Education) can't be opened in Apprentice.
4. Start Houdini once from the Launcher. If macOS asks for permissions, allow them.

**Check:** Houdini opens, and **File → Save As** offers the `.hipnc` file type.

Make your design scene. In Houdini: **Windows → Python Shell**, paste this one line (it is for the folder from §3; change
`you` to your Mac user name):

```python
p = "/Users/you/GitHub/sci-arc-studio-fall2026/site-model/houdini/tools/new_design_scene.py"; exec(open(p).read(), {"__file__": p, "hou": hou})
```

Type your name (lowercase, for example `clark`) when it asks.

**Check:** the scene shows the site point cloud (it takes a few seconds to load), the network has `Site_context` and `Design_<yourname>`, and
`site-model/houdini/designs/<yourname>.hipnc` now exists.


## 7. Let Claude work inside Houdini (Houdini MCP)

Claude talks to Houdini through the **houdini-mcp** server (a community project,
https://github.com/oculairmedia/houdini-mcp) and Houdini's built-in RPC server, `hrpyc`. This setup has not yet been
run on a Mac; tell us what differs.

1. **Install the server** (in Terminal):

   ```bash
   git clone https://github.com/oculairmedia/houdini-mcp.git ~/houdini-mcp
   cd ~/houdini-mcp
   git checkout 7e5cd7a
   python3 -m venv .venv
   .venv/bin/pip install -e .
   ```

   `7e5cd7a` is the version the project uses; don't update it without telling the team.
2. **Register it with Claude.** Paste this in Terminal, or ask Claude in the Code tab to run it for you (if Terminal
   says `claude: command not found`, install Claude Code from https://claude.com/claude-code):

   ```bash
   claude mcp add --scope user houdini -e MCP_TRANSPORT=stdio -e HOUDINI_HOST=127.0.0.1 -e HOUDINI_PORT=18811 -- ~/houdini-mcp/.venv/bin/python -m houdini_mcp
   ```

3. **Start Houdini's side automatically.** In Houdini's **Python Shell**, paste (again with your path):

   ```python
   import os, sys, shutil; d = os.path.join(hou.homeHoudiniDirectory(), "python%d.%dlibs" % sys.version_info[:2]); os.makedirs(d, exist_ok=True); shutil.copy("/Users/you/GitHub/sci-arc-studio-fall2026/site-model/houdini/tools/pythonrc.py", d); print(d)
   ```

   This copies the project's `pythonrc.py` into your Houdini preferences. It starts `hrpyc` on port 18811 whenever
   Houdini opens. (If you already had a `pythonrc.py` there, it is replaced.) Restart Houdini, then restart Claude.

**Check:** with Houdini open, start a new Claude Code session and ask *"what nodes are in /obj of the open Houdini
scene?"*. It should name `Site_context` and `Design_<yourname>`.

Houdini must be open for Claude to reach it. Claude changes your scene only when you ask; save often
(**File → Save**), because the `.hipnc` is not stored in git.

*Level 2 ends here. The design routine is in [WORKFLOW.md](WORKFLOW.md#3-make-the-change).*

---

## 8. Data pipeline (optional)

Only needed to change how the site itself is computed (terrain, buildings, trees, LiDAR labels, building entities).
Everyone else uses the results in `site-model/exports/` and `site-model/houdini/`.

```bash
cd ~/GitHub/sci-arc-studio-fall2026
python3 -m venv .venv
source .venv/bin/activate
pip install -r site-model/requirements.txt
```

The Houdini pipeline and its order are in [site-model/houdini/README.md](../site-model/houdini/README.md#site-pipeline-order);
it needs about 7 GB of downloads and staging.
Run `source .venv/bin/activate` again in each new Terminal window.

**Check:** `python3 -c "import laspy, shapely, sklearn"` prints nothing (no error).


---

## Troubleshooting

| Problem | Try |
|---|---|
| `brew: command not found` | Run the **Next steps** lines Homebrew printed, or open a new Terminal window |
| `gh auth login` returns before you authorized | Run it again and leave Terminal open until it says **Logged in** |
| `Permission denied` when pushing | Accept the repository invitation email, then re-run `gh auth login` |
| Viewer page is blank | Open it through `python3 web/serve.py`, not by double-clicking the HTML file |
| Claude can't see Houdini | Houdini must be open. In its Python Shell, `import hrpyc; hrpyc.start_server(port=18811)` starts the connection by hand; if that works, redo §7 step 3. Restart Claude after `claude mcp add` |
| Houdini says the file is from another licence | Everyone uses **Apprentice** (`.hipnc`); see §6 |
| My design doesn't show on the website | Check that `site-model/exports/design_<name>.glb` exists (Render `/out/export_design`), then reload the viewer |
| Something else | Copy the exact error and the command you ran into a pull request comment, or ask Claude in the Code tab |
