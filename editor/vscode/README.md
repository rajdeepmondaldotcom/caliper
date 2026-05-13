# Caliper Statusbar

Shows local Caliper spend in the VS Code status bar.

The extension shells out to `caliper statusline --format json` and opens
`caliper export receipt --format html` when the statusbar item is clicked.
